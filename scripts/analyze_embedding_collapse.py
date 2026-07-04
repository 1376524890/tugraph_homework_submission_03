#!/usr/bin/env python3
"""量化 TCG flow 嵌入的坍塌程度：PCA 方差分布 + 随机对 cosine。

嵌入坍塌 = 所有向量几乎同方向（cosine→1，PCA top-1 主成分占绝大部分方差），
knn/线性模型无法区分 → 对分类是噪声。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from sklearn.decomposition import PCA

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/features/tcg/node2vec/tcg_flow_node2vec_d128_light_shrcr.parquet"


def main() -> None:
    pf = pq.ParquetFile(PATH)
    emb_cols = sorted(c for c in pf.schema_arrow.names if c.startswith("emb_"))
    print(f"读 {len(emb_cols)} 维 embedding...", flush=True)
    df = pq.read_table(PATH, columns=emb_cols).to_pandas()
    X = df.values.astype(np.float32)
    print(f"  X shape: {X.shape}", flush=True)

    rng = np.random.RandomState(42)
    idx = rng.choice(len(X), min(100_000, len(X)), replace=False)
    Xs = X[idx]

    pca = PCA(n_components=min(10, Xs.shape[1]))
    pca.fit(Xs)
    vr = pca.explained_variance_ratio_
    print(f"\n{'='*60}")
    print("PCA 方差占比（坍塌诊断）")
    print(f"{'='*60}")
    print(f"top-10: {[f'{v:.3f}' for v in vr]}")
    print(f"top-1:   {vr[0]:.3f}   <- >0.8 表示严重坍塌（有效维度≈1）")
    print(f"top-2 累计: {vr[:2].sum():.3f}")
    print(f"top-10 累计: {vr.sum():.3f}  <- 理想≈1.0（128 维应分散）")

    a = Xs[rng.choice(len(Xs), 5000)]
    an = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    cos = an @ an.T
    off = cos[np.triu_indices(5000, k=1)]
    print(f"\n随机 flow 对 cosine: 中位 {np.median(off):.4f}, mean {np.mean(off):.4f}")
    print(f"  理想（不坍塌）≈0；坍塌接近 1")

    norms = np.linalg.norm(Xs, axis=1)
    print(f"\n向量范数: 中位 {np.median(norms):.4f}, std {np.std(norms):.4f}")
    print(f"{'='*60}")
    print("\n结论：")
    if vr[0] > 0.8:
        print(f"  top-1 PCA = {vr[0]:.3f} > 0.8 → 严重坍塌，128 维嵌入有效维度≈1，无判别力")
        print(f"  这是 D 组 knn 0.044 的根因：嵌入近乎常数，分类器无法利用")


if __name__ == "__main__":
    main()
