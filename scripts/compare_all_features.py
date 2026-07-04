#!/usr/bin/env python3
"""A-F 统一对比：HCG A/B/C + TCG target-encoding D/E/F × 7 分类器（含 CPU lightgbm）。

相同预采样 130k record_id（C_safe）+ 相同 seed + 相同分类器，统一对比矩阵。
D/E/F 用双端点 target encoding（保持 TCG 建图思路，绕开 node2vec 坍塌）。
所有特征 StandardScaler（fit on train），消除 raw 尺度淹没。
"""
from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier

ROOT = Path(__file__).resolve().parents[1]
A_PATH = ROOT / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet"
C_SAFE = ROOT / "data/features/hcg/classification/datasets_c_safe/C_raw_plus_hcg_flow_emb.parquet"
SEED = 20260525
N_FOLDS = 5
SMOOTH_M = 10.0


def smooth(counts_df: pd.DataFrame, prior: np.ndarray, m: float = SMOOTH_M) -> np.ndarray:
    n = counts_df.sum(axis=1).values[:, None]
    return (counts_df.values + m * prior[None, :]) / (n + m)


def kfold_te(a: pd.DataFrame, col: str, y: np.ndarray, splits: np.ndarray,
             n_classes: int, n_folds: int = N_FOLDS, seed: int = SEED) -> np.ndarray:
    eps = a[col].values
    tr_mask = splits == "train"
    tr_idx = np.where(tr_mask)[0]
    rng = np.random.RandomState(seed)
    fold_labels = rng.randint(0, n_folds, size=len(tr_idx))
    te = np.zeros((len(a), n_classes), dtype=np.float32)
    tr_df = a[tr_mask]
    g_counts = (tr_df.groupby(col)["y"].value_counts().unstack(fill_value=0)
                .reindex(columns=range(n_classes), fill_value=0))
    g_prior = np.bincount(y[tr_mask], minlength=n_classes).astype(float); g_prior /= g_prior.sum()
    g_te = smooth(g_counts, g_prior)
    g_map = {ep: i for i, ep in enumerate(g_counts.index)}
    for f in range(n_folds):
        other = tr_idx[fold_labels != f]
        other_df = a.iloc[other]
        fc = (other_df.groupby(col)["y"].value_counts().unstack(fill_value=0)
              .reindex(columns=range(n_classes), fill_value=0))
        fp = np.bincount(y[other], minlength=n_classes).astype(float); fp /= fp.sum()
        fte = smooth(fc, fp)
        f_map = {ep: i for i, ep in enumerate(fc.index)}
        for i in tr_idx[fold_labels == f]:
            te[i] = fte[f_map[eps[i]]] if eps[i] in f_map else fp
    for i in range(len(a)):
        if not tr_mask[i]:
            te[i] = g_te[g_map[eps[i]]] if eps[i] in g_map else g_prior
    return te


def main() -> None:
    print("读 A 全量...", flush=True)
    a = pq.read_table(A_PATH, columns=["record_id", "src_endpoint", "dst_endpoint", "target", "split"]).to_pandas()
    a["record_id"] = a["record_id"].astype(str)
    for c in ("src_endpoint", "dst_endpoint"):
        a[c] = a[c].astype(str)
    le = LabelEncoder()
    a["y"] = le.fit_transform(a["target"].astype(str))
    n_classes = len(le.classes_)
    splits, ys = a["split"].values, a["y"].values
    print(f"  行数={len(a):,} 类别={n_classes}", flush=True)

    print("K-fold target encoding: src + dst...", flush=True)
    te_src = kfold_te(a, "src_endpoint", ys, splits, n_classes)
    te_dst = kfold_te(a, "dst_endpoint", ys, splits, n_classes)

    print("读 C_safe（raw+hcg 预采样 130k）...", flush=True)
    cs = pq.read_table(C_SAFE).to_pandas()
    cs["record_id"] = cs["record_id"].astype(str)
    raw_cols = [c for c in cs.columns if c.startswith("raw_")]
    hcg_cols = [c for c in cs.columns if c.startswith("hcg_")]
    rid2idx = {r: i for i, r in enumerate(a["record_id"].values)}
    idx = np.array([rid2idx[r] for r in cs["record_id"]])
    y_s, sp_s = ys[idx], splits[idx]
    raw_s = cs[raw_cols].values.astype(np.float32)
    hcg_s = cs[hcg_cols].values.astype(np.float32)
    te_s = np.concatenate([te_src[idx], te_dst[idx]], axis=1)
    del te_src, te_dst
    import gc; gc.collect()

    groups = [
        ("A (raw, 91维)", raw_s),
        ("B (HCG emb, 258维)", hcg_s),
        ("C (raw+hcg, 349维)", np.concatenate([raw_s, hcg_s], axis=1)),
        ("D_te (TE, 156维)", te_s),
        ("E_te (raw+TE, 247维)", np.concatenate([raw_s, te_s], axis=1)),
        ("F_te (raw+hcg+TE, 505维)", np.concatenate([raw_s, hcg_s, te_s], axis=1)),
    ]
    # 7 分类器（含 CPU lightgbm）
    def make_models():
        return [
            ("dummy", DummyClassifier(strategy="most_frequent")),
            ("dt", DecisionTreeClassifier(max_depth=20, random_state=SEED)),
            ("logistic", SGDClassifier(loss="log_loss", max_iter=100, random_state=SEED, n_jobs=-1)),
            ("rf", RandomForestClassifier(n_estimators=50, max_depth=20, n_jobs=-1, random_state=SEED)),
            ("nb", GaussianNB()),
            ("lightgbm", lgb.LGBMClassifier(n_estimators=100, num_leaves=31, n_jobs=-1, random_state=SEED, verbose=-1)),
        ]

    tr_mask = sp_s == "train"
    te_mask = sp_s == "test"
    clf_names = ["dummy", "dt", "logistic", "rf", "nb", "lgbm", "knn"]

    print("\n" + "=" * 90)
    print("A-F 统一对比矩阵（macro_f1 / accuracy），相同 130k 预采样 + StandardScaler")
    print("=" * 90)
    header = f"{'组':24s}" + "".join(f"{c:>8s}" for c in clf_names)
    print(header)
    print("-" * 90)
    for gname, X in groups:
        scaler = StandardScaler(with_mean=False).fit(X[tr_mask])
        Xtr = scaler.transform(X[tr_mask])
        Xtest = scaler.transform(X[te_mask])
        ytr, ytest = y_s[tr_mask], y_s[te_mask]
        row = f"{gname:24s}"
        for cname, clf in make_models():
            clf.fit(Xtr, ytr)
            pred = clf.predict(Xtest)
            mf1 = f1_score(ytest, pred, average="macro", zero_division=0)
            row += f"{mf1:>8.3f}"
        # knn（采样 train + batch predict）
        rng = np.random.RandomState(SEED)
        sidx = rng.choice(len(Xtr), min(60000, len(Xtr)), replace=False)
        knn = KNeighborsClassifier(n_neighbors=5).fit(Xtr[sidx], ytr[sidx])
        preds = [knn.predict(Xtest[s:s + 5000]) for s in range(0, len(Xtest), 5000)]
        pred = np.concatenate(preds)
        mf1 = f1_score(ytest, pred, average="macro", zero_division=0)
        row += f"{mf1:>8.3f}"
        print(row, flush=True)
    print("=" * 90)
    print("列：dummy/dt/logistic/rf/nb/lightgbm(CPU)/knn")
    print("A/B/C=HCG（raw/HCG emb/raw+hcg）；D_te/E_te/F_te=TCG target encoding（TE/raw+TE/raw+hcg+TE）")


if __name__ == "__main__":
    main()
