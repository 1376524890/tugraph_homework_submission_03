#!/usr/bin/env python3
"""重绘混淆矩阵：magma + LogNorm + 0值浅灰背景 + seaborn heatmap"""
from __future__ import annotations
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt; import numpy as np
import pyarrow.parquet as pq; import seaborn as sns
from matplotlib.colors import LogNorm
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import confusion_matrix
from sklearn.preprocessing import LabelEncoder, StandardScaler

_RO = Path(__file__).resolve().parents[1]; _OUT = _RO / "docs/figures"; _OUT.mkdir(exist_ok=True)
_SEED = 20260525

def draw_confusion(cm, labels, title, outpath, top_n=20):
    """Seaborn heatmap with LogNorm + magma + 0 as light-gray"""
    cm = cm.astype(float); cm[cm == 0] = np.nan
    cmap = plt.get_cmap("magma").copy(); cmap.set_bad("#eeeeee")
    fig, ax = plt.subplots(figsize=(13, 10))
    sns.heatmap(cm, cmap=cmap, norm=LogNorm(vmin=1, vmax=np.nanmax(cm)),
                annot=True, fmt=".0f", xticklabels=labels, yticklabels=labels,
                linewidths=0.4, linecolor="white", ax=ax,
                cbar_kws={"label": "Count (log scale)", "shrink": 0.8})
    ax.set_title(title, fontsize=15); ax.set_xlabel("Predicted"); ax.set_ylabel("True")
    plt.xticks(rotation=90); plt.yticks(rotation=0)
    fig.tight_layout(); fig.savefig(outpath, dpi=150); plt.close()
    print(f"-> {outpath}", flush=True)

# ---- 加载数据（与 generate_report_figures 一致）----
print("加载 A + C_safe + K-fold TE...", flush=True)
a = pq.read_table(_RO/"data/features/hcg/classification/datasets/A_raw_flow_features.parquet",
                  columns=["record_id","src_endpoint","dst_endpoint","target","split"]).to_pandas()
a["record_id"] = a["record_id"].astype(str)
for c in ("src_endpoint","dst_endpoint"): a[c] = a[c].astype(str)
le = LabelEncoder(); a["y"] = le.fit_transform(a["target"].astype(str)); n_cls = len(le.classes_)
splits, ys = a["split"].values, a["y"].values

def smooth(c,p,m=10.0): n=c.sum(1).values[:,None]; return (c.values+m*p[None,:])/(n+m)
def kfold_te(col):
    eps=a[col].values; trm=splits=="train"; tri=np.where(trm)[0]
    rng=np.random.RandomState(_SEED); fl=rng.randint(0,5,size=len(tri))
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

te_src=kfold_te("src_endpoint"); te_dst=kfold_te("dst_endpoint")
cs=pq.read_table(_RO/"data/features/hcg/classification/datasets_c_safe/C_raw_plus_hcg_flow_emb.parquet").to_pandas()
cs["record_id"]=cs["record_id"].astype(str); rid2idx={r:i for i,r in enumerate(a["record_id"].values)}
idx=np.array([rid2idx[r] for r in cs["record_id"]]); y_s,sp_s=ys[idx],splits[idx]
raw_s=cs[[c for c in cs.columns if c.startswith("raw_")]].values.astype(np.float32)
hcg_s=cs[[c for c in cs.columns if c.startswith("hcg_")]].values.astype(np.float32)
te_s=np.concatenate([te_src[idx],te_dst[idx]],axis=1); del te_src,te_dst
C_X=np.concatenate([raw_s,hcg_s],axis=1); D_te_X=te_s
tr_mask=sp_s=="train"; te_mask=sp_s=="test"; y_tr,y_test=y_s[tr_mask],y_s[te_mask]

# ---- 混淆矩阵1: C组 RandomForest ----
print("C组 rf...", flush=True)
sC=StandardScaler(with_mean=False); Xtr=sC.fit_transform(C_X[tr_mask]); Xtest=sC.transform(C_X[te_mask])
clf_rf=RandomForestClassifier(n_estimators=50,max_depth=20,n_jobs=-1,random_state=_SEED).fit(Xtr,y_tr)
pred=clf_rf.predict(Xtest)
top20=np.argsort(np.bincount(y_test))[-20:]; mask=np.isin(y_test,top20)&np.isin(pred,top20)
cm=confusion_matrix(y_test[mask],pred[mask],labels=top20)
draw_confusion(cm,[le.classes_[i] for i in top20],"HCG C Group RF Confusion (top-20, log-scale)",_OUT/"h3_c_rf_confusion.png")

# ---- 混淆矩阵2: D_te Logistic ----
print("D_te logistic...", flush=True)
sD=StandardScaler(with_mean=False); Xtr=sD.fit_transform(D_te_X[tr_mask]); Xtest=sD.transform(D_te_X[te_mask])
clf_lr=SGDClassifier(loss="log_loss",max_iter=100,random_state=_SEED).fit(Xtr,y_tr)
pred2=clf_lr.predict(Xtest)
cm2=confusion_matrix(y_test[mask],pred2[mask],labels=top20)
draw_confusion(cm2,[le.classes_[i] for i in top20],"D_te Group Logistic Confusion (top-20, log-scale)",_OUT/"h4_dte_logistic_confusion.png")

print("Done.", flush=True)
