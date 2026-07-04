#!/usr/bin/env python3
"""双端点 target encoding + D/E/F 融合：TCG 建模的有效替代（保持 SHR 思路，绕开 node2vec 坍塌）。

SHR=同 src_endpoint、CR=五元组反转（含 dst）。端点纯度 0.757 是最强信号，但 node2vec
把它绕进图嵌入后坍塌。本脚本对 src_endpoint + dst_endpoint 各做 K-fold target encoding
（78+78=156 维），与 A(raw)/C(raw+hcg) 融合得 D_te/E_te/F_te，对照 node2vec D/E/F 与 HCG A/B/C。

仍属 TCG 建模范畴：直接利用 SHR/CR 关系的端点 key，用监督标签统计替代坍塌的无监督嵌入。
"""
from __future__ import annotations

from pathlib import Path

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
    """对该端点列做 K-fold target encoding，返回全量 te (n × n_classes)。"""
    eps = a[col].values
    tr_mask = splits == "train"
    tr_idx = np.where(tr_mask)[0]
    rng = np.random.RandomState(seed)
    fold_labels = rng.randint(0, n_folds, size=len(tr_idx))
    te = np.zeros((len(a), n_classes), dtype=np.float32)
    # global（valid/test 用）
    tr_df = a[tr_mask]
    g_counts = (tr_df.groupby(col)["y"].value_counts().unstack(fill_value=0)
                .reindex(columns=range(n_classes), fill_value=0))
    g_prior = np.bincount(y[tr_mask], minlength=n_classes).astype(float)
    g_prior /= g_prior.sum()
    g_te = smooth(g_counts, g_prior)
    g_map = {ep: i for i, ep in enumerate(g_counts.index)}
    # K-fold（train）
    for f in range(n_folds):
        other = tr_idx[fold_labels != f]
        other_df = a.iloc[other]
        fc = (other_df.groupby(col)["y"].value_counts().unstack(fill_value=0)
              .reindex(columns=range(n_classes), fill_value=0))
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


def train_eval(name: str, Xtr, ytr, Xtest, ytest, knn_train_sample: int = 60000) -> None:
    ref = {"D": {"dummy": 0.0095, "dt": 0.0216, "logistic": 0.0154, "knn": 0.0440, "rf": "-", "nb": "-"},
           "E": {"dummy": 0.0095, "dt": 0.1651, "logistic": 0.1113, "knn": 0.2069, "rf": "-", "nb": "-"},
           "F": {"dummy": 0.0095, "dt": 0.2245, "logistic": 0.1715, "knn": 0.4220, "rf": "-", "nb": "-"}}
    hcg = {"A": 0.261, "B": 0.447, "C": 0.451}  # knn 参考
    print(f"\n--- {name} (shape train={Xtr.shape}) ---")
    scaler = StandardScaler(with_mean=False).fit(Xtr)  # fit on train，修复 raw(bytes~1e6) 淹没 TE(0~1) 的尺度问题
    Xtr_s, Xtest_s = scaler.transform(Xtr), scaler.transform(Xtest)
    models = [
        ("dummy", DummyClassifier(strategy="most_frequent")),
        ("dt", DecisionTreeClassifier(max_depth=20, random_state=SEED)),
        ("logistic", SGDClassifier(loss="log_loss", max_iter=20, random_state=SEED, n_jobs=-1)),
        ("rf", RandomForestClassifier(n_estimators=50, max_depth=20, n_jobs=-1, random_state=SEED)),
        ("nb", GaussianNB()),
    ]
    for mname, clf in models:
        clf.fit(Xtr_s, ytr)
        pred = clf.predict(Xtest_s)
        mf1 = f1_score(ytest, pred, average="macro", zero_division=0)
        acc = accuracy_score(ytest, pred)
        grp = name[0]
        r = ref[grp].get(mname, "-")
        rstr = f"{r:.4f}" if isinstance(r, float) else r
        print(f"  {mname:9s} macro_f1={mf1:.4f} acc={acc:.4f}   node2vec {grp}={rstr}")
    # knn（采样 train 加速 + batch predict）
    if len(Xtr_s) > knn_train_sample:
        rng = np.random.RandomState(SEED)
        sidx = rng.choice(len(Xtr_s), knn_train_sample, replace=False)
        knn = KNeighborsClassifier(n_neighbors=5).fit(Xtr_s[sidx], ytr[sidx])
    else:
        knn = KNeighborsClassifier(n_neighbors=5).fit(Xtr_s, ytr)
    preds = [knn.predict(Xtest_s[s:s + 5000]) for s in range(0, len(Xtest_s), 5000)]
    pred = np.concatenate(preds)
    mf1 = f1_score(ytest, pred, average="macro", zero_division=0)
    acc = accuracy_score(ytest, pred)
    grp = name[0]
    extra = f"  HCG {grp}={hcg.get(grp,'-')}" if grp in hcg else ""
    print(f"  knn       macro_f1={mf1:.4f} acc={acc:.4f}   node2vec {grp}={ref[grp]['knn']:.4f}{extra}")


def main() -> None:
    print("读 A 全量...", flush=True)
    a = pq.read_table(A_PATH, columns=["record_id", "src_endpoint", "dst_endpoint", "target", "split"]).to_pandas()
    a["record_id"] = a["record_id"].astype(str)
    for c in ("src_endpoint", "dst_endpoint"):
        a[c] = a[c].astype(str)
    le = LabelEncoder()
    a["y"] = le.fit_transform(a["target"].astype(str))
    n_classes = len(le.classes_)
    splits = a["split"].values
    ys = a["y"].values
    print(f"  行数={len(a):,} 类别={n_classes}", flush=True)

    print("K-fold target encoding: src_endpoint...", flush=True)
    te_src = kfold_te(a, "src_endpoint", ys, splits, n_classes)
    print("K-fold target encoding: dst_endpoint...", flush=True)
    te_dst = kfold_te(a, "dst_endpoint", ys, splits, n_classes)
    # 不构建全量 te_all（避免峰值 OOM），下面在 C_safe 级 concat 后释放全量

    print("读 C_safe（raw+hcg 预采样 130k）...", flush=True)
    cs = pq.read_table(C_SAFE).to_pandas()
    cs["record_id"] = cs["record_id"].astype(str)
    raw_cols = [c for c in cs.columns if c.startswith("raw_")]
    hcg_cols = [c for c in cs.columns if c.startswith("hcg_")]
    print(f"  C_safe={len(cs):,} raw={len(raw_cols)} hcg={len(hcg_cols)}", flush=True)

    rid2idx = {r: i for i, r in enumerate(a["record_id"].values)}
    idx = np.array([rid2idx[r] for r in cs["record_id"]])
    y_s = ys[idx]
    sp_s = splits[idx]
    te_s = np.concatenate([te_src[idx], te_dst[idx]], axis=1)  # 130k × 156
    del te_src, te_dst
    import gc; gc.collect()
    raw_s = cs[raw_cols].values.astype(np.float32)   # 130k × 91
    hcg_s = cs[hcg_cols].values.astype(np.float32)   # 130k × 258

    Xtr_mask = sp_s == "train"
    Xva_mask = sp_s == "valid"  # noqa  (未单独用，test 评估)
    Xte_mask = sp_s == "test"

    groups = {
        "D_te (src+dst TE, 156维)": te_s,
        "E_te (raw + TE, 247维)": np.concatenate([raw_s, te_s], axis=1),
        "F_te (raw+hcg+TE, 505维)": np.concatenate([raw_s, hcg_s, te_s], axis=1),
    }
    print("\n" + "=" * 72)
    print("双端点 target encoding D/E/F vs node2vec D/E/F + HCG A/B/C (knn Macro-F1)")
    print("=" * 72)
    for name, X in groups.items():
        train_eval(name, X[Xtr_mask], y_s[Xtr_mask], X[Xte_mask], y_s[Xte_mask])
    print("=" * 72)


if __name__ == "__main__":
    main()
