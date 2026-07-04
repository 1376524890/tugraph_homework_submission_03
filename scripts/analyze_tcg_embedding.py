#!/usr/bin/env python3
"""分析 TCG flow 嵌入的最近邻到底编码了什么：端点身份 / 应用类别 / 时间局部。

回答"为什么 TCG 嵌入是噪声而非有效信息"：
- 若同 src_endpoint 率高 + 同 target 率高 → 嵌入编码端点→应用（应有效）
- 若同 target 率低（接近基线）+ record_id 差小 → 嵌入学时间局部，非类别语义（噪声）
"""
from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from gensim.models import Word2Vec

ROOT = Path(__file__).resolve().parents[1]
EMB_MODEL = ROOT / "data/features/tcg/node2vec/tcg_flow_node2vec_d128_light_shrcr.model"
A_PATH = ROOT / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet"
N_SAMPLE = 3000
TOPN = 5


def main() -> None:
    print("加载 d128_light_shrcr model...", flush=True)
    model = Word2Vec.load(str(EMB_MODEL))
    wv = model.wv
    print(f"  vocab={len(wv):,}", flush=True)

    print("加载 A 元信息(record_id/src_endpoint/target/timestamp)...", flush=True)
    a = pq.read_table(A_PATH, columns=["record_id", "src_endpoint", "target", "raw_timestamp_epoch"]).to_pandas()
    a["record_id"] = a["record_id"].astype(str)
    a["rid_num"] = a["record_id"].str.extract(r"rec_(\d+)").astype("int64")
    info = a.set_index("record_id")[["src_endpoint", "target", "raw_timestamp_epoch", "rid_num"]]

    random.seed(42)
    vocab = [r for r in wv.key_to_index if r in info.index]
    sample = random.sample(vocab, min(N_SAMPLE, len(vocab)))
    print(f"采样 {len(sample)} flow 分析 top-{TOPN} 最近邻...", flush=True)

    same_ep = same_target = total = 0
    rid_diffs: list[int] = []
    ts_diffs: list[int] = []
    sims: list[float] = []
    for rid in sample:
        me = info.loc[rid]
        try:
            nbrs = wv.most_similar(rid, topn=TOPN)
        except Exception:
            continue
        for nrid, sim in nbrs:
            if nrid not in info.index:
                continue
            nb = info.loc[nrid]
            total += 1
            sims.append(sim)
            if nb["src_endpoint"] == me["src_endpoint"]:
                same_ep += 1
            if nb["target"] == me["target"]:
                same_target += 1
            rid_diffs.append(abs(int(nb["rid_num"]) - int(me["rid_num"])))
            ts_diffs.append(abs(int(nb["raw_timestamp_epoch"]) - int(me["raw_timestamp_epoch"])))

    maj = a["target"].value_counts().iloc[0] / len(a)
    # 端点内 target 纯度（理论上界，SHR 同质性）
    ep_purity = a.groupby("src_endpoint")["target"].agg(lambda s: s.value_counts().iloc[0] / len(s))
    print(f"\n{'=' * 64}")
    print(f"d128_light_shrcr 嵌入最近邻统计（{total:,} 对，top-{TOPN}）")
    print(f"{'=' * 64}")
    print(f"平均 cosine 相似度:   {np.mean(sims):.4f}")
    print(f"同 src_endpoint 率:   {same_ep / total:.3f}   <- 嵌入是否编码端点身份")
    print(f"同 target(应用) 率:   {same_target / total:.3f}   <- 嵌入是否编码应用类别")
    print(f"  全局多数类基线:     {maj:.3f}")
    print(f"  端点内 target 纯度: {ep_purity.mean():.3f}  (SHR 同质性理论上界)")
    print(f"record_id 差 中位数:  {np.median(rid_diffs):.0f}   p90={np.percentile(rid_diffs, 90):.0f}   <- 时间局部性(越小越局部)")
    print(f"timestamp 差 中位数:  {np.median(ts_diffs):.0f}s   p90={np.percentile(ts_diffs, 90):.0f}s")
    print(f"{'=' * 64}")
    print("\n解读：")
    if same_target / total < maj * 1.2:
        print(f"  同 target 率 {same_target/total:.3f} 仅接近基线 {maj:.3f} → 嵌入几乎不编码应用类别（噪声）")
    if np.median(rid_diffs) < 100:
        print(f"  record_id 差中位数 {np.median(rid_diffs):.0f} 极小 → 嵌入强时间局部性（record_id 连续=捕获顺序相邻）")


if __name__ == "__main__":
    main()
