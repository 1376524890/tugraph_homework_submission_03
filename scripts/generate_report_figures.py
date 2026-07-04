#!/usr/bin/env python3
"""生成作业3/作业4的图表：混淆矩阵、对比柱状图、PCA、cosine分布。

输出到 docs/figures/，不干扰任何正在运行的任务。
"""
from __future__ import annotations
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np, pandas as pd, pyarrow.parquet as pq
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay
from sklearn.preprocessing import LabelEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/figures"; OUT.mkdir(parents=True, exist_ok=True)
A_PATH = ROOT / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet"
C_SAFE = ROOT / "data/features/hcg/classification/datasets_c_safe/C_raw_plus_hcg_flow_emb.parquet"
N2V_PATH = ROOT / "data/features/tcg/node2vec/tcg_flow_node2vec_d128_light_shrcr.parquet"
SEED = 20260525

plt.rcParams.update({"font.size":9, "axes.titlesize":11, "axes.labelsize":10})

# ---------- 公用数据 ----------
print("读 A 全量 (K-fold target encoding)...", flush=True)
a = pq.read_table(A_PATH, columns=["record_id","src_endpoint","dst_endpoint","target","split"]).to_pandas()
a["record_id"] = a["record_id"].astype(str)
for c in ("src_endpoint","dst_endpoint"): a[c] = a[c].astype(str)
le = LabelEncoder(); a["y"] = le.fit_transform(a["target"].astype(str))
n_classes = len(le.classes_); splits, ys = a["split"].values, a["y"].values

def smooth(counts_df, prior, m=10.0):
    n = counts_df.sum(axis=1).values[:, None]
    return (counts_df.values + m*prior[None,:]) / (n+m)
def kfold_te(col):
    eps = a[col].values; tr_mask = splits=="train"; tr_idx = np.where(tr_mask)[0]
    rng = np.random.RandomState(SEED); fold_labels = rng.randint(0,5,size=len(tr_idx))
    te = np.zeros((len(a),n_classes), dtype=np.float32)
    tr_df = a[tr_mask]; gc = tr_df.groupby(col)["y"].value_counts().unstack(fill_value=0).reindex(columns=range(n_classes),fill_value=0)
    gp = np.bincount(ys[tr_mask],minlength=n_classes).astype(float); gp/=gp.sum()
    gte = smooth(gc,gp); gm = {ep:i for i,ep in enumerate(gc.index)}
    for f in range(5):
        other=tr_idx[fold_labels!=f]; od=a.iloc[other]
        fc=od.groupby(col)["y"].value_counts().unstack(fill_value=0).reindex(columns=range(n_classes),fill_value=0)
        fp=np.bincount(ys[other],minlength=n_classes).astype(float); fp/=fp.sum()
        fte=smooth(fc,fp); fm={ep:i for i,ep in enumerate(fc.index)}
        for i in tr_idx[fold_labels==f]: te[i]=fte[fm[eps[i]]] if eps[i] in fm else fp
    for i in range(len(a)):
        if not tr_mask[i]: te[i]=gte[gm[eps[i]]] if eps[i] in gm else gp
    return te

te_src = kfold_te("src_endpoint"); te_dst = kfold_te("dst_endpoint")

print("读 C_safe...", flush=True)
cs = pq.read_table(C_SAFE).to_pandas(); cs["record_id"] = cs["record_id"].astype(str)
raw_cols = [c for c in cs.columns if c.startswith("raw_")]
hcg_cols = [c for c in cs.columns if c.startswith("hcg_")]
rid2idx = {r:i for i,r in enumerate(a["record_id"].values)}
idx = np.array([rid2idx[r] for r in cs["record_id"]])
y_s, sp_s = ys[idx], splits[idx]
raw_s = cs[raw_cols].values.astype(np.float32)
hcg_s = cs[hcg_cols].values.astype(np.float32)
te_s = np.concatenate([te_src[idx], te_dst[idx]], axis=1)
C_X = np.concatenate([raw_s, hcg_s], axis=1)   # C组
D_te_X = te_s                                    # D_te组

tr_mask = sp_s=="train"; te_mask = sp_s=="test"
y_tr, y_test = y_s[tr_mask], y_s[te_mask]

def scaler_fit(X): s=StandardScaler(with_mean=False); s.fit(X[tr_mask]); return s.transform(X[tr_mask]), s.transform(X[te_mask])

# ========== 作业3-7: C组 rf 混淆矩阵 ==========
print("作业3-7: C组 rf 混淆矩阵...", flush=True)
Xtr, Xtest = scaler_fit(C_X)
clf = RandomForestClassifier(n_estimators=50, max_depth=20, n_jobs=-1, random_state=SEED).fit(Xtr, y_tr)
pred = clf.predict(Xtest)
top20 = np.argsort(np.bincount(y_test))[-20:]  # top-20 类
mask = np.isin(y_test, top20) & np.isin(pred, top20)
cm = confusion_matrix(y_test[mask], pred[mask], labels=top20)
fig, ax = plt.subplots(figsize=(10,9))
ConfusionMatrixDisplay(cm, display_labels=[le.classes_[i] for i in top20]).plot(ax=ax, xticks_rotation="vertical", values_format="d", cmap="YlOrRd")
ax.set_title("HCG C Group RandomForest Confusion (top-20 classes)")
fig.tight_layout(); fig.savefig(OUT/"h3_c_rf_confusion.png", dpi=150); plt.close()
print("  -> docs/figures/h3_c_rf_confusion.png", flush=True)

# ========== 作业3-8: A/B/C Macro-F1 对比柱状图 ==========
print("作业3-8: A/B/C 对比柱状图...", flush=True)
data = {
    "A": dict(dummy=0.010, dt=0.283, logistic=0.030, rf=0.333, nb=0.059, lgbm=0.022, knn=0.201),
    "B": dict(dummy=0.010, dt=0.311, logistic=0.291, rf=0.414, nb=0.208, lgbm=0.089, knn=0.294),
    "C": dict(dummy=0.010, dt=0.387, logistic=0.097, rf=0.463, nb=0.093, lgbm=0.041, knn=0.376),
}
models = ["dummy","dt","logistic","rf","nb","lgbm","knn"]; model_labels = ["dummy","dec.tree","logistic","rand.forest","naive_bayes","lightgbm","knn"]
x = np.arange(len(model_labels)); w = 0.22
fig, ax = plt.subplots(figsize=(11,5))
for i,(grp,vals) in enumerate([("A",data["A"]),("B",data["B"]),("C",data["C"])]):
    ax.bar(x+i*w, [vals[m] for m in models], w, label=f"{grp} ({'raw' if grp=='A' else 'HCG emb' if grp=='B' else 'raw+HCG'})", zorder=3)
ax.set_xticks(x+w); ax.set_xticklabels(model_labels)
ax.set_ylabel("Macro-F1"); ax.set_title("A/B/C Group Comparison by Classifier"); ax.legend(); ax.grid(axis="y",alpha=0.3)
fig.tight_layout(); fig.savefig(OUT/"h3_abc_comparison.png", dpi=150); plt.close()
print("  -> docs/figures/h3_abc_comparison.png", flush=True)

# ========== 作业4-5: PCA 对比（各自拟合）==========
print("作业4-5: PCA 对比...", flush=True)
pf = pq.ParquetFile(N2V_PATH); emb_cols = sorted(c for c in pf.schema_arrow.names if c.startswith("emb_"))
n2v_rids = pq.read_table(N2V_PATH, columns=["record_id"]).column("record_id").to_pylist()
n2v_r2i = {r:i for i,r in enumerate(n2v_rids)}
n2v_idx = np.array([n2v_r2i[r] for r in cs["record_id"] if r in n2v_r2i])
n2v_sub = pq.read_table(N2V_PATH, columns=emb_cols).to_pandas().values.astype(np.float32)[n2v_idx]
te_sub = D_te_X
rng = np.random.RandomState(42)
s_n2v = rng.choice(len(n2v_sub), min(2000,len(n2v_sub)), replace=False)
s_te = rng.choice(len(te_sub), min(2000,len(te_sub)), replace=False)

def pca_plot(ax, X, idx, title):
    pca = PCA(n_components=2).fit(X[idx])
    pts = pca.transform(X[idx]); labs = y_s[idx]
    for c in np.unique(labs):
        ax.scatter(pts[labs==c,0], pts[labs==c,1], s=3, alpha=0.4, edgecolors="none")
    ax.set_title(title); ax.set_xlabel("PC1"); ax.set_ylabel("PC2")

fig, (ax1,ax2) = plt.subplots(1,2,figsize=(14,6))
pca_plot(ax1, n2v_sub, s_n2v, "node2vec Embeddings (D group, 128d)")
pca_plot(ax2, te_sub, s_te, "Target Encoding Features (D_te group, 156d)")
fig.suptitle("PCA Comparison: node2vec Collapse vs. Target Encoding")
fig.tight_layout(); fig.savefig(OUT/"h4_pca_comparison.png", dpi=150); plt.close()
print("  -> docs/figures/h4_pca_comparison.png", flush=True)

# ========== 作业4-6: cosine 分布 ==========
print("作业4-6: cosine 分布...", flush=True)
for label, X, color in [("node2vec", n2v_sub, "tab:red"), ("target encoding", te_sub, "tab:blue")]:
    rng=np.random.RandomState(42); s=rng.choice(len(X),min(5000,len(X)),replace=False)
    x=X[s]; xn=x/(np.linalg.norm(x,axis=1,keepdims=True)+1e-9); c=xn@xn.T
    off=c[np.triu_indices(len(x),k=1)]
    plt.hist(off, bins=60, alpha=0.6, density=True, color=color, edgecolor="white", linewidth=0.3, label=f"{label}\n(中位 {np.median(off):.3f})")
plt.axvline(0, color="gray", ls="--", lw=0.8); plt.xlabel("cosine similarity"); plt.ylabel("density")
plt.title("Pairwise Cosine Distribution: node2vec vs. Target Encoding"); plt.legend()
plt.tight_layout(); plt.savefig(OUT/"h4_cosine_dist.png", dpi=150); plt.close()
print("  -> docs/figures/h4_cosine_dist.png", flush=True)

# ========== 作业4-7: D组 node2vec vs TE 柱状图 ==========
print("作业4-7: D组 node2vec vs TE 柱状图...", flush=True)
d_n2v = dict(dummy=0.010, dt=0.0216, logistic=0.0154, rf="-", nb="-", lgbm="-", knn=0.0440)
d_te  = dict(dummy=0.010, dt=0.343, logistic=0.674, rf=0.520, nb=0.284, lgbm=0.028, knn=0.634)
models_comp = ["dummy","dt","logistic","rf","nb","lgbm","knn"]
x = np.arange(len(models_comp)); w = 0.3
fig, ax = plt.subplots(figsize=(11,5))
te_vals = [d_te[m] for m in models_comp]; n2v_vals = [d_n2v[m] if isinstance(d_n2v[m],float) else 0 for m in models_comp]
b1 = ax.bar(x-w/2, te_vals, w, label="target encoding D_te", color="tab:blue", zorder=3)
b2 = ax.bar(x+w/2, n2v_vals, w, label="node2vec D", color="tab:red", zorder=3)
for bar, val in zip(b1, te_vals):
    if val>0.05: ax.text(bar.get_x()+bar.get_width()/2, val+0.01, f"{val:.3f}", ha="center", fontsize=7)
for bar, val in zip(b2, n2v_vals):
    if val > 0.02: ax.text(bar.get_x() + bar.get_width() / 2, val + 0.01, f"{val:.3f}", ha="center", fontsize=7)
ax.set_xticks(x); ax.set_xticklabels(["dummy","dec.tree","logistic","rand.forest","naive_bayes","lightgbm","knn"])
ax.set_ylabel("Macro-F1"); ax.set_title("D Group: node2vec vs. Target Encoding Macro-F1")
ax.legend(); ax.grid(axis="y",alpha=0.3)
fig.tight_layout(); fig.savefig(OUT/"h4_d_comparison.png", dpi=150); plt.close()
print("  -> docs/figures/h4_d_comparison.png", flush=True)

# ========== 作业4-8: D_te logistic 混淆矩阵 ==========
print("作业4-8: D_te logistic 混淆矩阵...", flush=True)
Xtr, Xtest = scaler_fit(D_te_X)
clf2 = SGDClassifier(loss="log_loss", max_iter=100, random_state=SEED, n_jobs=-1).fit(Xtr, y_tr)
pred2 = clf2.predict(Xtest)
top20 = np.argsort(np.bincount(y_test))[-20:]
mask = np.isin(y_test, top20) & np.isin(pred2, top20)
cm2 = confusion_matrix(y_test[mask], pred2[mask], labels=top20)
fig, ax = plt.subplots(figsize=(10,9))
ConfusionMatrixDisplay(cm2, display_labels=[le.classes_[i] for i in top20]).plot(ax=ax, xticks_rotation="vertical", values_format="d", cmap="YlOrRd")
ax.set_title("D_te Group Logistic Confusion Matrix (top-20 classes)")
fig.tight_layout(); fig.savefig(OUT/"h4_dte_logistic_confusion.png", dpi=150); plt.close()
print("  -> docs/figures/h4_dte_logistic_confusion.png", flush=True)

print("\n全部图表生成完毕。", flush=True)
