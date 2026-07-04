#!/usr/bin/env python3
"""src_endpoint target encoding 基线：验证 SHR 信号有效，node2vec 坍塌是方法问题。

SHR 关系 = 同 src_endpoint，端点纯度 0.757（最强同质性）。但 TCG+node2vec 把这个
信号绕进图嵌入后坍塌（D knn 0.044）。本脚本对 src_endpoint 直接做 K-fold target
encoding（78 维标签概率）作为 D_te 特征，用与 node2vec D 组**相同的预采样 flow 与
分类器**对照。若 D_te knn >> 0.044，证明 SHR 信号本身有效，问题在 node2vec。

target encoding 仍属于 TCG 建模范畴：它直接利用 SHR 关系的 key（src_endpoint），
只是用监督标签统计替代了坍塌的无监督图嵌入。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import LabelEncoder
from sklearn.tree import DecisionTreeClassifier

ROOT = Path(__file__).resolve().parents[1]
A_PATH = ROOT / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet"
SAFE_D = ROOT / "data/features/tcg/classification/datasets_safe/D_tcg_flow_node2vec_d128_light_shrcr.parquet"
SEED = 20260525
N_FOLDS = 5
SMOOTH_M = 10.0


def smooth(counts_df: pd.DataFrame, prior: np.ndarray, m: float = SMOOTH_M) -> np.ndarray:
    """(counts + m*prior) / (n + m)，n=0 时退化为 prior。"""
    n = counts_df.sum(axis=1).values[:, None]
    return (counts_df.values + m * prior[None, :]) / (n + m)


def main() -> None:
    print("读 A 全量(record_id/src_endpoint/target/split)...", flush=True)
    a = pq.read_table(A_PATH, columns=["record_id", "src_endpoint", "target", "split"]).to_pandas()
    a["record_id"] = a["record_id"].astype(str)
    a["src_endpoint"] = a["src_endpoint"].astype(str)
    le = LabelEncoder()
    a["y"] = le.fit_transform(a["target"].astype(str))
    n_classes = len(le.classes_)
    print(f"  行数={len(a):,}  类别={n_classes}  端点={a['src_endpoint'].nunique():,}", flush=True)

    eps = a["src_endpoint"].values
    ys = a["y"].values
    splits = a["split"].values
    tr_mask = splits == "train"

    # 全 train 统计（valid/test 用，避免泄漏）
    tr = a[tr_mask]
    global_counts = (tr.groupby("src_endpoint")["y"].value_counts().unstack(fill_value=0)
                     .reindex(columns=range(n_classes), fill_value=0))
    global_prior = np.bincount(ys[tr_mask], minlength=n_classes).astype(float)
    global_prior /= global_prior.sum()
    global_te = smooth(global_counts, global_prior)
    g_ep2row = {ep: i for i, ep in enumerate(global_counts.index)}

    # K-fold target encoding（train 内部，避免 train 自泄漏）
    print(f"K-fold({N_FOLDS}) target encoding on train...", flush=True)
    rng = np.random.RandomState(SEED)
    tr_idx_all = np.where(tr_mask)[0]
    fold_labels = rng.randint(0, N_FOLDS, size=len(tr_idx_all))
    te = np.zeros((len(a), n_classes), dtype=np.float32)
    for f in range(N_FOLDS):
        test_f = tr_idx_all[fold_labels == f]
        other = tr_idx_all[fold_labels != f]
        other_df = a.iloc[other]
        fc = (other_df.groupby("src_endpoint")["y"].value_counts().unstack(fill_value=0)
              .reindex(columns=range(n_classes), fill_value=0))
        fp = np.bincount(ys[other], minlength=n_classes).astype(float)
        fp /= fp.sum()
        fte = smooth(fc, fp)
        f_ep2row = {ep: i for i, ep in enumerate(fc.index)}
        for i in test_f:
            ep = eps[i]
            te[i] = fte[f_ep2row[ep]] if ep in f_ep2row else fp

    # valid/test 用 global_te
    for i in range(len(a)):
        if not tr_mask[i]:
            ep = eps[i]
            te[i] = global_te[g_ep2row[ep]] if ep in g_ep2row else global_prior

    # 预采样 flow（与 D_node2vec 完全相同 record_id，对照公平）
    print("读预采样 record_id(与 D_node2vec 相同 flow)...", flush=True)
    safe = pq.read_table(SAFE_D, columns=["record_id"]).to_pandas()
    safe["record_id"] = safe["record_id"].astype(str)
    rid2idx = {r: i for i, r in enumerate(a["record_id"].values)}
    sample_idx = np.array([rid2idx[r] for r in safe["record_id"] if r in rid2idx])
    X = te[sample_idx]
    y_s = ys[sample_idx]
    sp_s = splits[sample_idx]
    print(f"  匹配 {len(sample_idx):,}: train={sum(sp_s=='train')} valid={sum(sp_s=='valid')} test={sum(sp_s=='test')}", flush=True)

    Xtr, ytr = X[sp_s == "train"], y_s[sp_s == "train"]
    Xtest, ytest = X[sp_s == "test"], y_s[sp_s == "test"]

    print("\n" + "=" * 72)
    print("D_te (src_endpoint target encoding, 78维) vs D_node2vec (128维, 已坍塌)")
    print("=" * 72)
    print(f"{'model':22s} {'macro_f1':>10s} {'weighted_f1':>12s} {'accuracy':>10s}   vs node2vec")
    ref = {"dummy_most_frequent": 0.0095, "decision_tree": 0.0216,
           "logistic_sgd": 0.0154, "knn_sample": 0.0440}
    models = [
        ("dummy_most_frequent", DummyClassifier(strategy="most_frequent")),
        ("decision_tree", DecisionTreeClassifier(max_depth=20, random_state=SEED)),
        ("logistic_sgd", SGDClassifier(loss="log_loss", max_iter=20, random_state=SEED, n_jobs=-1)),
    ]
    for name, clf in models:
        clf.fit(Xtr, ytr)
        pred = clf.predict(Xtest)
        mf1 = f1_score(ytest, pred, average="macro", zero_division=0)
        wf1 = f1_score(ytest, pred, average="weighted", zero_division=0)
        acc = accuracy_score(ytest, pred)
        print(f"{name:22s} {mf1:>10.4f} {wf1:>12.4f} {acc:>10.4f}   node2vec={ref[name]:.4f}")

    # knn batch predict
    print("  knn_sample 训练中(batch predict)...", flush=True)
    knn = KNeighborsClassifier(n_neighbors=5)
    knn.fit(Xtr, ytr)
    preds = [knn.predict(Xtest[s:s + 5000]) for s in range(0, len(Xtest), 5000)]
    pred = np.concatenate(preds)
    mf1 = f1_score(ytest, pred, average="macro", zero_division=0)
    wf1 = f1_score(ytest, pred, average="weighted", zero_division=0)
    acc = accuracy_score(ytest, pred)
    print(f"{'knn_sample':22s} {mf1:>10.4f} {wf1:>12.4f} {acc:>10.4f}   node2vec=0.0440")
    print("=" * 72)


if __name__ == "__main__":
    main()
