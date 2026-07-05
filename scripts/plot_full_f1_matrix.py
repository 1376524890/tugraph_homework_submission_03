#!/usr/bin/env python3
"""全部 Macro-F1 / Weighted-F1 heatmap + 各类 F1 对比（不重训，用缓存数据）"""
from __future__ import annotations
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt; import numpy as np; import json

_OUT = Path(__file__).resolve().parents[1] / "docs/figures"; _OUT.mkdir(exist_ok=True)

# ---- Macro-F1 矩阵（来自 compare_all_features 完成实验）----
gnames = ["A","B","C","D_te","E_te","F_te"]
glabels = ["A\nraw","B\nHCG","C\nraw+HCG","D_te\nTE","E_te\nraw+TE","F_te\nraw+HCG+TE"]
cnames = ["dummy","tree","logistic","rf","nb","lgbm","knn"]
clabels = ["dummy","tree","logistic","rf","nb","lgbm","knn"]

macro = {
    "A": [0.010,0.283,0.030,0.333,0.059,0.022,0.201],
    "B": [0.010,0.311,0.291,0.414,0.208,0.089,0.294],
    "C": [0.010,0.387,0.097,0.463,0.093,0.041,0.376],
    "D_te":[0.010,0.343,0.674,0.520,0.284,0.028,0.634],
    "E_te":[0.010,0.370,0.089,0.484,0.251,0.041,0.590],
    "F_te":[0.010,0.382,0.175,0.476,0.247,0.029,0.600],
}

# Weighted-F1: HCG from classifier_summary, TCG-te from compare_all_features results
weighted = {
    "A": [0.111,0.642,0.487,0.596,0.158,0.120,0.592],
    "B": [0.111,0.492,0.394,0.547,0.320,0.165,0.576],
    "C": [0.111,0.680,0.474,0.645,0.210,0.098,0.662],
    "D_te":[0.111,0.572,0.765,0.692,0.381,0.095,0.770],
    "E_te":[0.111,0.639,0.112,0.665,0.342,0.091,0.728],
    "F_te":[0.111,0.678,0.362,0.688,0.330,0.088,0.793],
}

# ---- 双栏 heatmap ----
macro_mat = np.array([[macro[g][i] for g in gnames] for i in range(len(cnames))])
wei_mat   = np.array([[weighted[g][i] for g in gnames] for i in range(len(cnames))])

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
for ax, mat, title in [(ax1, macro_mat, "Macro-F1"), (ax2, wei_mat, "Weighted-F1")]:
    im = ax.imshow(mat, cmap="YlOrRd", vmin=0, vmax=max(mat.max(), 0.8), aspect="auto")
    for i in range(len(cnames)):
        for j in range(len(gnames)):
            ax.text(j, i, f"{mat[i,j]:.3f}", ha="center", va="center", fontsize=8,
                    color="white" if mat[i,j] > 0.35 else "black")
    ax.set_xticks(range(len(gnames))); ax.set_xticklabels(glabels, fontsize=9)
    ax.set_yticks(range(len(cnames))); ax.set_yticklabels(clabels, fontsize=9)
    ax.set_title(title, fontsize=12, weight="bold")
    plt.colorbar(im, ax=ax, shrink=0.82)
fig.suptitle("All Classifiers x All Feature Groups: F1 Matrix", fontsize=14, weight="bold")
fig.tight_layout(); fig.savefig(_OUT / "full_f1_matrix.png", dpi=150); plt.close()
print("-> docs/figures/full_f1_matrix.png", flush=True)

# ---- 各类 F1: D_te vs A (knn) ----
# 从 compare_all_features 重新跑 knn 在 D_te 和 A 上取 per-class F1
import pyarrow.parquet as pq; from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import f1_score

_RO = Path(__file__).resolve().parents[1]
a = pq.read_table(_RO/"data/features/hcg/classification/datasets/A_raw_flow_features.parquet",
                  columns=["record_id","src_endpoint","dst_endpoint","target","split"]).to_pandas()
a["record_id"]=a["record_id"].astype(str)
for c in ("src_endpoint","dst_endpoint"): a[c]=a[c].astype(str)
le=LabelEncoder(); a["y"]=le.fit_transform(a["target"].astype(str)); n_cls=len(le.classes_)
def smooth(c,p,m=10.0): n=c.sum(1).values[:,None]; return (c.values+m*p[None,:])/(n+m)
def kfold_te(col):
    eps=a[col].values; splits=a["split"].values; ys=a["y"].values; trm=splits=="train"
    tri=np.where(trm)[0]; rng=np.random.RandomState(20260525); fl=rng.randint(0,5,size=len(tri))
    te=np.zeros((len(a),n_cls),dtype=np.float32)
    td=a[trm]; gc=td.groupby(col)["y"].value_counts().unstack(fill_value=0).reindex(columns=range(n_cls),fill_value=0)
    gp=np.bincount(ys[trm],minlength=n_cls).astype(float); gp/=gp.sum(); gte=smooth(gc,gp); gm={e:i for i,e in enumerate(gc.index)}
    for f in range(5):
        o=tri[fl!=f]; od=a.iloc[o]; fc=od.groupby(col)["y"].value_counts().unstack(fill_value=0).reindex(columns=range(n_cls),fill_value=0)
        fp=np.bincount(ys[o],minlength=n_cls).astype(float); fp/=fp.sum(); fte=smooth(fc,fp); fm={e:i for i,e in enumerate(fc.index)}
        for i in tri[fl==f]: te[i]=fte[fm[eps[i]]] if eps[i] in fm else fp
    for i in range(len(a)):
        if not trm[i]: te[i]=gte[gm[eps[i]]] if eps[i] in gm else gp
    return te

cs=pq.read_table(_RO/"data/features/hcg/classification/datasets_c_safe/C_raw_plus_hcg_flow_emb.parquet").to_pandas()
cs["record_id"]=cs["record_id"].astype(str); rid2idx={r:i for i,r in enumerate(a["record_id"].values)}
idx=np.array([rid2idx[r] for r in cs["record_id"]]); y_s=a["y"].values[idx]; sp_s=a["split"].values[idx]
tm_mask=sp_s=="train"; tt_mask=sp_s=="test"

raw=cs[[c for c in cs.columns if c.startswith("raw_")]].values.astype(np.float32)
# knn on A (raw only)
sA=StandardScaler(with_mean=False).fit(raw[tm_mask]); XtrA=sA.transform(raw[tm_mask]); XttA=sA.transform(raw[tt_mask])
knnA=KNeighborsClassifier(n_neighbors=5).fit(XtrA,y_s[tm_mask]); predA=knnA.predict(XttA)
f1A=f1_score(y_s[tt_mask],predA,average=None,zero_division=0)
# knn on D_te
te_src=kfold_te("src_endpoint"); te_dst=kfold_te("dst_endpoint")
te_s=np.concatenate([te_src[idx],te_dst[idx]],axis=1)
sD=StandardScaler(with_mean=False).fit(te_s[tm_mask]); XtrD=sD.transform(te_s[tm_mask]); XttD=sD.transform(te_s[tt_mask])
knnD=KNeighborsClassifier(n_neighbors=5).fit(XtrD,y_s[tm_mask]); predD=knnD.predict(XttD)
f1D=f1_score(y_s[tt_mask],predD,average=None,zero_division=0)

top30=np.argsort(f1D)[-min(30,len(f1D)):][::-1]; x=np.arange(len(top30)); w=0.35
fig,ax=plt.subplots(figsize=(16,5))
ax.bar(x-w/2,f1D[top30],w,label="D_te (TE 156d) knn",color="#C4826E")
ax.bar(x+w/2,f1A[top30],w,label="A (raw 91d) knn",color="#7B9EB3")
ax.set_xticks(x); ax.set_xticklabels([le.classes_[i] for i in top30],rotation=90,fontsize=7)
ax.set_ylabel("Per-class F1"); ax.legend(); ax.set_title("Per-class F1: D_te vs A (knn, top-30)")
fig.tight_layout(); fig.savefig(_OUT/"per_class_f1_dte_vs_a.png",dpi=150); plt.close()
print("-> docs/figures/per_class_f1_dte_vs_a.png", flush=True)

# ---- 缓存全部 F1 数据供后续绘图用 ----
cache = {"macro": {f"{g}_{c}": macro[g][i] for g in gnames for i,c in enumerate(cnames)},
         "weighted": {f"{g}_{c}": weighted[g][i] for g in gnames for i,c in enumerate(cnames)}}
cache_path = _RO / "data/features/reports/f1_cache.json"
cache_path.parent.mkdir(parents=True, exist_ok=True)
with open(cache_path, "w") as f: json.dump(cache, f, indent=2)
print(f"Cache saved: {cache_path}", flush=True)
print("Done.", flush=True)
