#!/usr/bin/env python3
"""离线预采样 TCG D/E/F 组 parquet，规避 train_hcg_classifiers.load_dataset 全量 read_parquet 的 OOM。

根因（与 subsample_hcg_c_safe.py 相同）
----
train_hcg_classifiers.py 的 load_dataset() (scripts/train_hcg_classifiers.py:410-420):
    df = pd.read_parquet(path)          # 一次性读全量(D 1.3G / E 1.8G / F 4.4G → 解压数倍)
    if any(n>0 for sample_*):
        df = concat([sample_split(...)]) # 采样发生在读取之后
因此 --sample-train/valid/test 无法缓解 load 阶段内存，7GB 机器必 OOM(-9)。
预采样后让训练脚本读小文件、且不传 --sample-*，即可安全跑通。

本脚本做法
----------
1. 只读 A 组 split 单列，确定每个 split 的全局行号（D/E/F 行顺序与 A 一致，
   check 报告 record_id_order_matches_A=PASS，故"全局行号"在四文件间等价）。
2. 精确复现训练脚本采样语义：RandomState(seed).permutation(len)[:n]，
   seed 序列 train=seed, valid=seed+1, test=seed+2（与 sample_split 对齐）。
3. 对 D/E/F 三个文件用**同一组全局行号**，各自按 row group 流式 Table.take。
   保证三个输出文件 record_id 严格一致、互相可比。
4. 全程峰值 < 1GB：split 单列 ~100MB；逐 row group 解压 ~150-300MB；纯索引运算零额外内存。

用法
----
    PYTHONPATH=src python3 scripts/subsample_tcg_def_safe.py
    # 然后训练：
    PYTHONPATH=src python3 scripts/train_hcg_classifiers.py \
        --dataset-dir data/features/tcg/classification/datasets_safe \
        --output-dir data/features/tcg/classification/results \
        --feature-groups D,E,F --models dummy,logistic_sgd,decision_tree,knn_sample
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

# 与 train_hcg_classifiers.py 默认值及 A/B/C 组成功运行完全对齐
DEFAULT_SEED = 20260525
DEFAULT_N_TRAIN = 100_000
DEFAULT_N_VALID = 10_000
DEFAULT_N_TEST = 20_000
SPLIT_COL = "split"
SPLITS = ("train", "valid", "test")

# (变量名, 文件名) —— 输出文件名与原文件一致，便于 train 脚本按 DATASET_FILES 识别
TCG_FILES = {
    "D": "D_tcg_flow_node2vec_d128_light_shrcr.parquet",
    "E": "E_raw_plus_tcg_d128_light_shrcr.parquet",
    "F": "F_raw_plus_hcg_plus_tcg_d128_light_shrcr.parquet",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="离线预采样 TCG D/E/F 组 parquet，规避全量 read_parquet OOM。")
    here = Path(__file__).resolve().parent.parent
    p.add_argument(
        "--split-src",
        type=Path,
        default=here / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet",
        help="提供 split 列的源文件（默认 A 组，作为全局行号基准）",
    )
    p.add_argument(
        "--tcg-dataset-dir",
        type=Path,
        default=here / "data/features/tcg/classification/datasets",
        help="D/E/F 原始全量 parquet 所在目录",
    )
    p.add_argument(
        "--dst-dir",
        type=Path,
        default=here / "data/features/tcg/classification/datasets_safe",
        help="输出目录（文件名固定为原名以便 train 脚本识别）",
    )
    p.add_argument("--groups", default="D,E,F", help="要预采样的特征组（逗号分隔）")
    p.add_argument("--n-train", type=int, default=DEFAULT_N_TRAIN)
    p.add_argument("--n-valid", type=int, default=DEFAULT_N_VALID)
    p.add_argument("--n-test", type=int, default=DEFAULT_N_TEST)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="与训练脚本 seed 一致(20260525)")
    p.add_argument("--compression", default="zstd", help="写出压缩(zstd/snappy)")
    return p.parse_args()


def row_group_offsets(pf: pq.ParquetFile) -> np.ndarray:
    """每个 row group 的全局起始行号，长度 = num_row_groups + 1（末尾为总行数）。"""
    starts = [0]
    for i in range(pf.metadata.num_row_groups):
        starts.append(starts[-1] + pf.metadata.row_group(i).num_rows)
    return np.asarray(starts, dtype=np.int64)


def choose_global_rows(split_src: Path, want: dict[str, int], seeds: dict[str, int]) -> np.ndarray:
    """读 split 单列，按训练脚本语义选全局行号（物理顺序）。"""
    print(f"[split] {split_src}")
    split_col = pq.read_table(split_src, columns=[SPLIT_COL]).column(0)
    total = len(split_col)
    print(f"        total_rows={total}")

    chosen_global: list[np.ndarray] = []
    for s in SPLITS:
        n = want[s]
        if n <= 0:
            continue
        mask = pc.equal(split_col, s)
        idx = np.nonzero(mask.to_numpy(zero_copy_only=False))[0]  # 该 split 的全局行号(物理顺序)
        avail = len(idx)
        take_n = min(n, avail)
        rng = np.random.RandomState(seeds[s])
        locs = rng.permutation(avail)[:take_n]  # 等价 pandas sample(replace=False, random_state=seed)
        chosen = np.sort(idx[locs])  # 排序后按 row group 顺序取行
        chosen_global.append(chosen)
        print(f"        split={s:5s} available={avail} -> picked={take_n} (seed={seeds[s]})")

    all_chosen = np.concatenate(chosen_global) if chosen_global else np.array([], dtype=np.int64)
    all_chosen.sort(kind="stable")
    print(f"        total picked rows = {len(all_chosen)}")
    return all_chosen


def take_rows(src: Path, all_chosen: np.ndarray, dst: Path, compression: str) -> tuple[int, int]:
    """对单个 parquet 文件按全局行号流式 take，写出小 parquet。返回 (行数, 列数)。"""
    pf = pq.ParquetFile(src)
    columns = [pf.schema_arrow.field(i).name for i in range(len(pf.schema_arrow))]
    total_rows = pf.metadata.num_rows
    num_rg = pf.metadata.num_row_groups
    offsets = row_group_offsets(pf)

    if total_rows != len(all_chosen) and total_rows < all_chosen.max(initial=0) + 1:
        # 防御：行号越界说明 D/E/F 行顺序与 split-src 不一致
        raise RuntimeError(
            f"{src.name} rows={total_rows} 与采样行号上界不匹配，可能行顺序与 split-src 不一致"
        )

    # 把全局行号定位到各自的 row group
    rg_of = np.searchsorted(offsets, all_chosen, side="right") - 1
    local_of = all_chosen - offsets[rg_of]
    buckets: dict[int, list[int]] = {}
    for rg, lo in zip(rg_of.tolist(), local_of.tolist()):
        buckets.setdefault(rg, []).append(lo)

    parts: list[pa.Table] = []
    for rg in range(num_rg):
        local_idxs = buckets.get(rg)
        if not local_idxs:
            continue
        tbl = pf.read_row_group(rg, columns=columns)  # 仅当前 row group，峰值可控
        sub = tbl.take(pa.array(local_idxs, type=pa.int64()))
        parts.append(sub)
        del tbl

    out_table = pa.concat_tables(parts) if parts else pa.table({col: [] for col in columns})
    dst.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(out_table, dst, compression=compression)

    size_mb = dst.stat().st_size / 1024 / 1024
    print(f"  [ok] {dst.name}: rows={out_table.num_rows} cols={out_table.num_columns} size={size_mb:.1f}MB")
    return out_table.num_rows, out_table.num_columns


def main() -> int:
    args = parse_args()
    want = {"train": args.n_train, "valid": args.n_valid, "test": args.n_test}
    seeds = {"train": args.seed, "valid": args.seed + 1, "test": args.seed + 2}
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]

    # 1) 选全局行号（三组共享）
    all_chosen = choose_global_rows(args.split_src, want, seeds)

    # 2) 对每个组流式 take
    print(f"\n[take] 输出目录 {args.dst_dir}")
    summary = {}
    for g in groups:
        fname = TCG_FILES.get(g)
        if fname is None:
            print(f"  [skip] 未知特征组 {g}")
            continue
        src = args.tcg_dataset_dir / fname
        if not src.exists():
            print(f"  [skip] 源文件不存在: {src}")
            continue
        dst = args.dst_dir / fname
        nrows, ncols = take_rows(src, all_chosen, dst, args.compression)
        summary[g] = (src, dst, nrows, ncols)

    # 3) 自检：三组行数一致、split 分布、record_id 对齐
    print("\n[check]")
    row_counts = {g: v[2] for g, v in summary.items()}
    align_ok = len(set(row_counts.values())) <= 1
    print(f"  行数一致(D=E=F): {align_ok}  {row_counts}")
    for g, (src, dst, nrows, ncols) in summary.items():
        chk_split = pq.read_table(dst, columns=[SPLIT_COL]).column(0)
        dist = {s: int(pc.sum(pc.equal(chk_split, s)).as_py()) for s in SPLITS}
        print(f"  {g}: split分布={dist}")
        # record_id 对齐校验（与 D 比对）
        if g != "D" and "D" in summary:
            d_rids = pq.read_table(summary["D"][1], columns=["record_id"]).column(0).to_numpy()
            g_rids = pq.read_table(dst, columns=["record_id"]).column(0).to_numpy()
            same = bool(np.array_equal(d_rids, g_rids))
            print(f"  {g} record_id 与 D 完全一致: {same}")
    print("\n[done] 安全预采样完成。训练时 --dataset-dir 指向该目录，且不要传 --sample-*。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
