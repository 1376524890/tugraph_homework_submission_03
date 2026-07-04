#!/usr/bin/env python3
"""离线预采样 C 组 parquet,规避 train_hcg_classifiers.load_dataset 全量 read_parquet 的 OOM。

根因
----
train_hcg_classifiers.py 的 load_dataset():
    df = pd.read_parquet(path)          # 一次性读全量(C 组 3.2GB 压缩 → 解压 ~9GB)
    if sample_* > 0:
        df = concat([sample_split(...)]) # 采样发生在读取之后
因此 --sample-train/valid/test 无法缓解 load_data 阶段内存,7GB 机器必 OOM。
memory_guard 又按"采样后行数"估算峰值(误判为 ~2.5GB 安全)而放行,实际 load 阶段被 SIGKILL(-9)。

本脚本做法
----------
精确复现训练脚本的采样语义,先把 C 组裁成小 parquet,再让训练脚本读小文件即可安全跑通。

精确复现依据:pandas DataFrame.sample(replace=False, random_state=seed) 内部等价于
    locs = np.random.RandomState(seed).permutation(len(part))[:n]
    part.iloc[locs]
其中 part = df[df[split_col]==split],df 顺序 = read_parquet 物理顺序。
因此本脚本对每个 split 的"全局行号序列"做同样的 RandomState(seed).permutation 取前 n,
即可得到与训练脚本全量采样完全一致的 record_id,保证 A/B/C 三组严格可比。

内存安全
--------
1. 只读 split 单列确定每个 split 的全局行号(单列 357 万 ~100MB)。
2. 用 RandomState.permutation 选位置(纯索引运算,零额外内存)。
3. 逐 row group 读全列、Table.take 取被选行(峰值 ≈ 单 row group 解压 ~150MB)。
4. concat 13 万行写出。全程峰值 < 1GB,在 5GB 可用内存下绝对安全。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

# 与 train_hcg_classifiers.py 默认值及 A/B 组成功运行完全对齐
DEFAULT_SEED = 20260525
DEFAULT_N_TRAIN = 100_000
DEFAULT_N_VALID = 10_000
DEFAULT_N_TEST = 20_000
SPLIT_COL = "split"
SPLITS = ("train", "valid", "test")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="离线预采样 C 组 parquet,规避全量 read_parquet OOM。")
    here = Path(__file__).resolve().parent.parent
    p.add_argument(
        "--src",
        type=Path,
        default=here / "data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet",
        help="原始 C 组全量 parquet 路径",
    )
    p.add_argument(
        "--dst-dir",
        type=Path,
        default=here / "data/features/hcg/classification/datasets_c_safe",
        help="输出目录(文件名固定为 C_raw_plus_hcg_flow_emb.parquet 以便训练脚本识别)",
    )
    p.add_argument("--n-train", type=int, default=DEFAULT_N_TRAIN)
    p.add_argument("--n-valid", type=int, default=DEFAULT_N_VALID)
    p.add_argument("--n-test", type=int, default=DEFAULT_N_TEST)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="与训练脚本 seed 一致(20260525)")
    p.add_argument("--compression", default="zstd", help="写出压缩(zstd/snappy)")
    return p.parse_args()


def row_group_offsets(pf: pq.ParquetFile) -> np.ndarray:
    """每个 row group 的全局起始行号,长度 = num_row_groups + 1(末尾为总行数)。"""
    starts = [0]
    for i in range(pf.metadata.num_row_groups):
        starts.append(starts[-1] + pf.metadata.row_group(i).num_rows)
    return np.asarray(starts, dtype=np.int64)


def main() -> int:
    args = parse_args()
    src: Path = args.src
    if not src.exists():
        raise FileNotFoundError(src)

    pf = pq.ParquetFile(src)
    columns = pf.schema_arrow.names
    total_rows = pf.metadata.num_rows
    offsets = row_group_offsets(pf)
    num_rg = pf.metadata.num_row_groups
    print(f"[src] {src}")
    print(f"      total_rows={total_rows} row_groups={num_rg} columns={len(columns)}")

    # 1) 只读 split 单列,确定每个 split 的全局行号(物理顺序)
    split_table = pq.read_table(src, columns=[SPLIT_COL])
    split_col = split_table.column(0)

    # 2) 精确复现训练脚本 sample_split:RandomState(seed).permutation(len)[:n]
    want = {"train": args.n_train, "valid": args.n_valid, "test": args.n_test}
    # seed 序列与 load_dataset 一致:train=seed, valid=seed+1, test=seed+2
    seeds = {"train": args.seed, "valid": args.seed + 1, "test": args.seed + 2}

    chosen_global: list[np.ndarray] = []
    picked_counts: dict[str, int] = {}
    for s in SPLITS:
        n = want[s]
        if n <= 0:
            picked_counts[s] = 0
            continue
        mask = pc.equal(split_col, s)
        idx = np.nonzero(mask.to_numpy(zero_copy_only=False))[0]  # 该 split 的全局行号(物理顺序)
        avail = len(idx)
        take_n = min(n, avail)
        rng = np.random.RandomState(seeds[s])
        locs = rng.permutation(avail)[:take_n]  # 等价 pandas sample(replace=False)
        chosen = np.sort(idx[locs])  # 排序后按 row group 顺序取行
        chosen_global.append(chosen)
        picked_counts[s] = take_n
        print(f"      split={s:5s} available={avail} -> picked={take_n} (seed={seeds[s]})")

    all_chosen = np.concatenate(chosen_global) if chosen_global else np.array([], dtype=np.int64)
    print(f"      total picked rows = {len(all_chosen)}")

    # 3) 按全局行号定位所属 row group,分桶
    #    searchsorted(offsets, idx, side='right')-1 给出 idx 落在第几个 row group
    rg_of = np.searchsorted(offsets, all_chosen, side="right") - 1
    local_of = all_chosen - offsets[rg_of]
    buckets: dict[int, list[int]] = {}
    for rg, lo in zip(rg_of.tolist(), local_of.tolist()):
        buckets.setdefault(rg, []).append(lo)

    # 4) 逐 row group 读全列、Table.take 取被选行
    parts: list[pa.Table] = []
    for rg in range(num_rg):
        local_idxs = buckets.get(rg)
        if not local_idxs:
            continue
        tbl = pf.read_row_group(rg, columns=columns)  # 仅当前 row group,峰值可控
        sub = tbl.take(pa.array(local_idxs, type=pa.int64()))
        parts.append(sub)
        del tbl

    out_table = pa.concat_tables(parts) if parts else pa.table({col: [] for col in columns})

    # 5) 写出(列顺序/类型完全继承原文件)
    args.dst_dir.mkdir(parents=True, exist_ok=True)
    dst = args.dst_dir / "C_raw_plus_hcg_flow_emb.parquet"
    pq.write_table(out_table, dst, compression=args.compression)
    dst_size_mb = dst.stat().st_size / 1024 / 1024
    print(f"[dst] {dst}")
    print(f"      rows={out_table.num_rows} cols={out_table.num_columns} size={dst_size_mb:.1f}MB")

    # 6) 自检:行数、列、split 分布
    chk = pq.ParquetFile(dst)
    chk_split = pq.read_table(dst, columns=[SPLIT_COL]).column(0)
    print("[check]")
    print(f"      rows_match={chk.metadata.num_rows == len(all_chosen)} "
          f"cols_match={chk.metadata.num_columns == len(columns)}")
    for s in SPLITS:
        cnt = int(pc.sum(pc.equal(chk_split, s)).as_py())
        print(f"      split={s:5s} count={cnt}")
    print("[done] 安全预采样完成,可用 --dataset-dir 指向该目录运行 C 组。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
