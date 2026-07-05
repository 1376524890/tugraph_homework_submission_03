#!/usr/bin/env python3
"""构建 D_te / E_te / F_te parquet：双端点 K-fold target encoding 替代 node2vec 嵌入。

SHR(src_endpoint) + CR(含 dst) = TCG 核心关系。node2vec 在这类端点内小团图中坍塌（D knn 0.044），
但端点标签统计本身极强（同质性 0.694→0.757）。本脚本用 K-fold target encoding 编码端点标签分布，
替代无监督 node2vec。

产出 D_te(156维) / E_te(247维=raw+TE) / F_te(505维=raw+hcg+TE)，格式与 A/B/C/D/E/F 兼容，
train_hcg_classifiers.py 可直接加载。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.preprocessing import LabelEncoder

ROOT = Path(__file__).resolve().parents[1]
A_PATH = ROOT / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet"
C_PATH = ROOT / "data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet"
OUT_DIR = ROOT / "data/features/tcg/classification/datasets_te"
SEED = 20260525
N_FOLDS = 5
SMOOTH_M = 10.0


def smooth(counts_df: pd.DataFrame, prior: np.ndarray, m: float = SMOOTH_M) -> np.ndarray:
    n = counts_df.sum(axis=1).values[:, None]
    return (counts_df.values + m * prior[None, :]) / (n + m)


def kfold_te(
    a: pd.DataFrame, col: str, y: np.ndarray, splits: np.ndarray,
    n_classes: int, n_folds: int = N_FOLDS, seed: int = SEED,
) -> np.ndarray:
    """K-fold target encoding for 该端点列，返回 (n, n_classes) float32."""
    eps = a[col].values
    tr_mask = splits == "train"
    tr_idx = np.where(tr_mask)[0]
    rng = np.random.RandomState(seed)
    fold_labels = rng.randint(0, n_folds, size=len(tr_idx))

    te = np.zeros((len(a), n_classes), dtype=np.float32)

    # global prior/encoding（valid/test 用）
    tr_df = a[tr_mask]
    g_counts = (
        tr_df.groupby(col)["y"]
        .value_counts()
        .unstack(fill_value=0)
        .reindex(columns=range(n_classes), fill_value=0)
    )
    g_prior = np.bincount(y[tr_mask], minlength=n_classes).astype(float)
    g_prior /= g_prior.sum()
    g_te = smooth(g_counts, g_prior)
    g_map = {ep: i for i, ep in enumerate(g_counts.index)}

    # K-fold（train 内）
    for f in range(n_folds):
        other = tr_idx[fold_labels != f]
        other_df = a.iloc[other]
        fc = (
            other_df.groupby(col)["y"]
            .value_counts()
            .unstack(fill_value=0)
            .reindex(columns=range(n_classes), fill_value=0)
        )
        fp = np.bincount(y[other], minlength=n_classes).astype(float)
        fp /= fp.sum()
        fte = smooth(fc, fp)
        f_map = {ep: i for i, ep in enumerate(fc.index)}
        test_f = tr_idx[fold_labels == f]
        for i in test_f:
            ep = eps[i]
            te[i] = fte[f_map[ep]] if ep in f_map else fp

    for i in range(len(a)):
        if not tr_mask[i]:
            ep = eps[i]
            te[i] = g_te[g_map[ep]] if ep in g_map else g_prior

    return te


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("读 A 全量（record_id/target/split/endpoints/raw）...", flush=True)
    a_cols = ["record_id", "target", "split", "src_endpoint", "dst_endpoint"]
    a_meta = pq.read_table(A_PATH, columns=a_cols).to_pandas()
    for c in a_cols:
        a_meta[c] = a_meta[c].astype(str)

    # raw feature columns
    pf_a = pq.ParquetFile(A_PATH)
    raw_cols = [c for c in pf_a.schema_arrow.names if c.startswith("raw_")]
    print(f"  raw 特征列: {len(raw_cols)}", flush=True)

    le = LabelEncoder()
    a_meta["y"] = le.fit_transform(a_meta["target"])
    n_classes = len(le.classes_)
    splits = a_meta["split"].values
    ys = a_meta["y"].values
    n_total = len(a_meta)
    print(f"  总行数={n_total:,}  类别数={n_classes}  训练行数={(splits=='train').sum():,}", flush=True)

    # ── K-fold target encoding ──
    print("K-fold TE: src_endpoint ...", flush=True)
    te_src = kfold_te(a_meta, "src_endpoint", ys, splits, n_classes)
    print(f"  src TE shape={te_src.shape}  unique src_endpoints={a_meta['src_endpoint'].nunique():,}", flush=True)

    print("K-fold TE: dst_endpoint ...", flush=True)
    te_dst = kfold_te(a_meta, "dst_endpoint", ys, splits, n_classes)
    print(f"  dst TE shape={te_dst.shape}  unique dst_endpoints={a_meta['dst_endpoint'].nunique():,}", flush=True)

    te_all = np.concatenate([te_src, te_dst], axis=1)  # (n, 156)
    n_te = te_all.shape[1]
    print(f"  TE 总计: {n_te} 维 (src={te_src.shape[1]} + dst={te_dst.shape[1]})", flush=True)

    del te_src, te_dst

    # ── 读 raw + hcg ──
    print("读 raw features...", flush=True)
    a_raw = pq.read_table(A_PATH, columns=raw_cols).to_pandas().values.astype(np.float32)
    print(f"  raw shape={a_raw.shape}", flush=True)

    print("读 C（hcg features）...", flush=True)
    hcg_cols = [c for c in pf_a.schema_arrow.names if c.startswith("hcg_")]
    if not hcg_cols:
        pf_c = pq.ParquetFile(C_PATH)
        hcg_cols = [c for c in pf_c.schema_arrow.names if c.startswith("hcg_")]
    c_hcg = pq.read_table(C_PATH, columns=hcg_cols).to_pandas().values.astype(np.float32)
    print(f"  hcg shape={c_hcg.shape}", flush=True)

    # ── 构建 meta table ──
    meta_table = pa.table({
        "record_id": pa.array(a_meta["record_id"].values, type=pa.string()),
        "target": pa.array(a_meta["target"].values, type=pa.string()),
        "split": pa.array(a_meta["split"].values, type=pa.string()),
    })

    # ── D_te (156 维纯 TE) ──
    print("\n写 D_te (纯 target encoding, 156 维)...", flush=True)
    te_col_names = [f"te_src_{i:03d}" for i in range(n_classes)] + [f"te_dst_{i:03d}" for i in range(n_classes)]
    d_te_columns = [
        pa.array(te_all[:, i], type=pa.float32()) for i in range(n_te)
    ]
    d_table = pa.table(
        [meta_table.column(0), meta_table.column(1), meta_table.column(2)] + d_te_columns,
        names=["record_id", "target", "split"] + te_col_names,
    )
    d_path = OUT_DIR / "D_te_src_dst_target_encoding.parquet"
    pq.write_table(d_table, d_path, compression="zstd", compression_level=3)
    d_sz = d_path.stat().st_size / 1e9
    print(f"  → {d_path} ({d_sz:.2f} GB)", flush=True)

    # ── E_te (raw + TE, 247 维) ──
    print("写 E_te (raw + TE, 247 维)...", flush=True)
    e_columns = []
    e_names = []
    for i, cn in enumerate(raw_cols):
        e_columns.append(pa.array(a_raw[:, i], type=pa.float32()))
        e_names.append(cn)
    for i in range(n_te):
        e_columns.append(pa.array(te_all[:, i], type=pa.float32()))
        e_names.append(te_col_names[i])
    e_table = pa.table(
        [meta_table.column(0), meta_table.column(1), meta_table.column(2)] + e_columns,
        names=["record_id", "target", "split"] + e_names,
    )
    e_path = OUT_DIR / "E_te_raw_plus_target_encoding.parquet"
    pq.write_table(e_table, e_path, compression="zstd", compression_level=3)
    e_sz = e_path.stat().st_size / 1e9
    print(f"  → {e_path} ({e_sz:.2f} GB)", flush=True)

    # ── F_te (raw + hcg + TE, 505 维) ──
    print("写 F_te (raw + hcg + TE, 505 维)...", flush=True)
    f_columns = list(e_columns)  # copy raw + te
    f_names = list(e_names)
    for i, cn in enumerate(hcg_cols):
        f_columns.append(pa.array(c_hcg[:, i], type=pa.float32()))
        f_names.append(cn)
    f_table = pa.table(
        [meta_table.column(0), meta_table.column(1), meta_table.column(2)] + f_columns,
        names=["record_id", "target", "split"] + f_names,
    )
    f_path = OUT_DIR / "F_te_raw_hcg_plus_target_encoding.parquet"
    pq.write_table(f_table, f_path, compression="zstd", compression_level=3)
    f_sz = f_path.stat().st_size / 1e9
    print(f"  → {f_path} ({f_sz:.2f} GB)", flush=True)

    # ── 摘要 ──
    n_raw = a_raw.shape[1]
    n_hcg = c_hcg.shape[1]
    n_f_te = len(e_names) + len(hcg_cols)
    print(f"\n{'='*60}")
    print(f"D_te: {n_te} 维 (src TE {n_classes} + dst TE {n_classes})")
    print(f"E_te: {n_raw + n_te} 维 (raw {n_raw} + TE {n_te})")
    print(f"F_te: {n_raw + n_hcg + n_te} 维 (raw {n_raw} + hcg {n_hcg} + TE {n_te})")
    print(f"全量行数: {n_total:,}  split: train={(splits=='train').sum():,} valid={(splits=='valid').sum():,} test={(splits=='test').sum():,}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
