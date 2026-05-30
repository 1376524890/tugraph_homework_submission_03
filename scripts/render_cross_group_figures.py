#!/usr/bin/env python3
"""Render cross-group (A–F) comparison figures for the comprehensive analysis section."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
HCG_SUMMARY = ROOT / "data/features/hcg/classification/results/classifier_summary.json"
TCG_SUMMARY = ROOT / "data/features/tcg/classification/results/classifier_summary.json"
FIG_DIR = ROOT / "data/features/cross_group/figures"


def require_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError as exc:
        raise SystemExit("matplotlib is required. Install with: python3 -m pip install matplotlib") from exc


def load_combined() -> pd.DataFrame:
    rows = []
    for path in (HCG_SUMMARY, TCG_SUMMARY):
        if path.exists():
            for rec in json.loads(path.read_text()):
                rows.append(rec)
    df = pd.DataFrame(rows)
    return df


def main() -> int:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt = require_matplotlib()
    df = load_combined()
    if df.empty:
        print("No data found.", file=sys.stderr)
        return 1

    completed = df[df["status"].fillna("") == "completed"].copy()
    if completed.empty:
        print("No completed tasks.", file=sys.stderr)
        return 1

    feature_order = ["A", "B", "C", "D", "E", "F"]
    model_order = ["lightgbm", "knn_sample", "decision_tree", "logistic_sgd", "dummy_stratified", "dummy_most_frequent"]

    # ── 1. Combined A-F Macro-F1 bar chart ──
    pivot_mf1 = completed.pivot_table(
        index="model_name", columns="feature_group", values="macro_f1", aggfunc="max"
    )
    pivot_mf1 = pivot_mf1.reindex(index=model_order, columns=feature_order)
    ax = pivot_mf1.plot(kind="bar", figsize=(14, 6), width=0.78)
    ax.set_title("Macro-F1 by Model and Feature Group (A–F)", fontsize=13)
    ax.set_xlabel("Model")
    ax.set_ylabel("Macro-F1")
    ax.legend(title="Feature group", ncol=6, fontsize=8)
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "cross_group_macro_f1.png", dpi=180)
    plt.close()
    print("✓ cross_group_macro_f1.png")

    # ── 2. Combined A-F Weighted-F1 bar chart ──
    pivot_wf1 = completed.pivot_table(
        index="model_name", columns="feature_group", values="weighted_f1", aggfunc="max"
    )
    pivot_wf1 = pivot_wf1.reindex(index=model_order, columns=feature_order)
    ax = pivot_wf1.plot(kind="bar", figsize=(14, 6), width=0.78)
    ax.set_title("Weighted-F1 by Model and Feature Group (A–F)", fontsize=13)
    ax.set_xlabel("Model")
    ax.set_ylabel("Weighted-F1")
    ax.legend(title="Feature group", ncol=6, fontsize=8)
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "cross_group_weighted_f1.png", dpi=180)
    plt.close()
    print("✓ cross_group_weighted_f1.png")

    # ── 3. Combined A-F Accuracy bar chart ──
    pivot_acc = completed.pivot_table(
        index="model_name", columns="feature_group", values="accuracy", aggfunc="max"
    )
    pivot_acc = pivot_acc.reindex(index=model_order, columns=feature_order)
    ax = pivot_acc.plot(kind="bar", figsize=(14, 6), width=0.78)
    ax.set_title("Accuracy by Model and Feature Group (A–F)", fontsize=13)
    ax.set_xlabel("Model")
    ax.set_ylabel("Accuracy")
    ax.legend(title="Feature group", ncol=6, fontsize=8)
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "cross_group_accuracy.png", dpi=180)
    plt.close()
    print("✓ cross_group_accuracy.png")

    # ── 4. TCG negative gain: A→E and C→F ──
    mf1 = completed.pivot_table(index="model_name", columns="feature_group", values="macro_f1", aggfunc="max")
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    if "A" in mf1.columns and "E" in mf1.columns:
        gain_AE = (mf1["E"] - mf1["A"]).dropna().sort_values()
        colors = ["#d62728" if v < 0 else "#2ca02c" for v in gain_AE.values]
        axes[0].barh(gain_AE.index, gain_AE.values, color=colors)
        axes[0].axvline(0, color="black", linewidth=0.8)
        axes[0].set_xlabel("Macro-F1 Change")
        axes[0].set_title("A → E (add TCG to raw features)")

    if "C" in mf1.columns and "F" in mf1.columns:
        gain_CF = (mf1["F"] - mf1["C"]).dropna().sort_values()
        colors = ["#d62728" if v < 0 else "#2ca02c" for v in gain_CF.values]
        axes[1].barh(gain_CF.index, gain_CF.values, color=colors)
        axes[1].axvline(0, color="black", linewidth=0.8)
        axes[1].set_xlabel("Macro-F1 Change")
        axes[1].set_title("C → F (add TCG to fusion features)")

    fig.suptitle("TCG Embedding Impact: Macro-F1 Change", fontsize=13)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "tcg_negative_gain.png", dpi=180)
    plt.close()
    print("✓ tcg_negative_gain.png")

    # ── 5. Best model-feature ranking (LightGBM Macro-F1 sorted) ──
    lgb = completed[completed["model_name"] == "lightgbm"].copy()
    if not lgb.empty:
        lgb_rank = lgb.sort_values("macro_f1", ascending=True)
        colors = []
        for fg in lgb_rank["feature_group"]:
            if fg == "C":
                colors.append("#2ca02c")  # green for best
            elif fg in ("D",):
                colors.append("#d62728")  # red for worst
            else:
                colors.append("#1f77b4")  # default blue
        fig, ax = plt.subplots(figsize=(10, 5))
        bars = ax.barh(lgb_rank["feature_group"], lgb_rank["macro_f1"], color=colors)
        for bar, val in zip(bars, lgb_rank["macro_f1"]):
            ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height() / 2,
                    f"{val:.4f}", va="center", fontsize=10)
        ax.set_xlabel("Macro-F1")
        ax.set_title("LightGBM Macro-F1 Ranking (A–F)")
        ax.axvline(x=0.006, color="gray", linestyle="--", alpha=0.5, label="dummy baseline")
        ax.legend()
        plt.tight_layout()
        plt.savefig(FIG_DIR / "lightgbm_macro_f1_ranking.png", dpi=180)
        plt.close()
        print("✓ lightgbm_macro_f1_ranking.png")

    # ── 6. Training time by feature group (LightGBM) ──
    lgb_time = completed[completed["model_name"] == "lightgbm"].copy()
    if not lgb_time.empty:
        lgb_time = lgb_time.sort_values("train_seconds", ascending=True)
        fig, ax = plt.subplots(figsize=(10, 4.5))
        bars = ax.barh(lgb_time["feature_group"], lgb_time["train_seconds"] / 3600, color="#ff7f0e")
        for bar, val, fc in zip(bars, lgb_time["train_seconds"] / 3600, lgb_time["feature_count"]):
            ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                    f"{val:.1f}h ({fc}d)", va="center", fontsize=9)
        ax.set_xlabel("Training time (hours)")
        ax.set_title("LightGBM Training Time vs Feature Count (A–F)")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "lightgbm_train_time_vs_features.png", dpi=180)
        plt.close()
        print("✓ lightgbm_train_time_vs_features.png")

    # ── 7. Weighted-F1 vs Macro-F1 divergence ──
    div_data = []
    for fg in feature_order:
        part = completed[completed["feature_group"] == fg]
        if part.empty:
            continue
        best = part.sort_values("macro_f1", ascending=False).iloc[0]
        div_data.append({
            "feature_group": fg,
            "macro_f1": best["macro_f1"],
            "weighted_f1": best["weighted_f1"],
            "diff": best["weighted_f1"] - best["macro_f1"],
        })
    if div_data:
        div_df = pd.DataFrame(div_data)
        fig, ax = plt.subplots(figsize=(10, 5))
        x = range(len(div_df))
        width = 0.35
        bars1 = ax.bar([i - width / 2 for i in x], div_df["macro_f1"], width, label="Macro-F1", color="#1f77b4")
        bars2 = ax.bar([i + width / 2 for i in x], div_df["weighted_f1"], width, label="Weighted-F1", color="#ff7f0e")
        for i, (_, row) in enumerate(div_df.iterrows()):
            diff = row["diff"]
            color = "#d62728" if diff < 0 else "#2ca02c"
            ax.annotate(f"{diff:+.4f}", (i, max(row["macro_f1"], row["weighted_f1"]) + 0.02),
                        ha="center", fontsize=9, color=color, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(div_df["feature_group"])
        ax.set_xlabel("Feature Group")
        ax.set_ylabel("F1 Score")
        ax.set_title("Macro-F1 vs Weighted-F1: Class Imbalance Indicator")
        ax.legend()
        plt.tight_layout()
        plt.savefig(FIG_DIR / "weighted_vs_macro_f1_divergence.png", dpi=180)
        plt.close()
        print("✓ weighted_vs_macro_f1_divergence.png")

    # ── 8. Macro-F1 vs train time scatter (all models, all groups) ──
    fig, ax = plt.subplots(figsize=(12, 6.5))
    group_colors = {"A": "#1f77b4", "B": "#ff7f0e", "C": "#2ca02c",
                    "D": "#d62728", "E": "#9467bd", "F": "#8c564b"}
    for fg, part in completed.groupby("feature_group"):
        color = group_colors.get(fg, "#7f7f7f")
        ax.scatter(part["train_seconds"] / 3600, part["macro_f1"], label=fg, s=80, color=color, edgecolors="black", linewidth=0.5)
        for _, row in part.iterrows():
            ax.annotate(row["model_name"][:12], (row["train_seconds"] / 3600, row["macro_f1"]),
                        fontsize=7, xytext=(4, 3), textcoords="offset points", alpha=0.8)
    ax.set_xlabel("Training time (hours)")
    ax.set_ylabel("Macro-F1")
    ax.set_title("Macro-F1 vs Training Time (All Models, A–F)")
    ax.legend(title="Feature group", ncol=3)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "cross_group_macro_f1_vs_time.png", dpi=180)
    plt.close()
    print("✓ cross_group_macro_f1_vs_time.png")

    # ── 9. Feature importance distribution comparison (D vs B) ──
    d_imp_path = ROOT / "data/features/tcg/classification/results/D/lightgbm/feature_importance_gain.csv"
    b_imp_path = ROOT / "data/features/hcg/classification/results/B/lightgbm/feature_importance_gain.csv"
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for ax_i, (path, label, color) in enumerate([
        (d_imp_path, "D/lightgbm (TCG, 65 features)", "#d62728"),
        (b_imp_path, "B/lightgbm (HCG, 258 features)", "#2ca02c"),
    ]):
        if path.exists():
            imp = pd.read_csv(path)
            if not imp.empty:
                imp = imp.sort_values("importance", ascending=False)
                axes[ax_i].bar(range(len(imp)), imp["importance"], color=color, alpha=0.8, width=1.0)
                axes[ax_i].set_title(f"Feature Importance: {label}")
                axes[ax_i].set_xlabel("Feature rank")
                axes[ax_i].set_ylabel("Gain importance")
                # Add stats annotation
                top_val = imp["importance"].iloc[0]
                ratio = imp["importance"].iloc[0] / max(imp["importance"].iloc[-1], 1)
                axes[ax_i].text(0.95, 0.90,
                                f"max/min ratio: {top_val / max(imp['importance'].iloc[-1], 1):.1f}×\n"
                                f"CV: {imp['importance'].std() / max(imp['importance'].mean(), 1):.3f}",
                                transform=axes[ax_i].transAxes, ha="right", va="top",
                                fontsize=9, bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.7))
    fig.suptitle("Feature Importance Distribution: TCG vs HCG Embeddings", fontsize=13)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "feature_importance_comparison_D_vs_B.png", dpi=180)
    plt.close()
    print("✓ feature_importance_comparison_D_vs_B.png")

    # ── 10. Model ranking consistency across feature groups ──
    mf1_pivot = completed.pivot_table(index="model_name", columns="feature_group", values="macro_f1", aggfunc="max")
    mf1_pivot = mf1_pivot.reindex(index=[m for m in model_order if m in mf1_pivot.index],
                                  columns=[c for c in feature_order if c in mf1_pivot.columns])
    if not mf1_pivot.empty:
        fig, ax = plt.subplots(figsize=(12, 6))
        im = ax.imshow(mf1_pivot.values, aspect="auto", cmap="RdYlGn")
        ax.set_xticks(range(len(mf1_pivot.columns)))
        ax.set_xticklabels(mf1_pivot.columns, fontsize=11)
        ax.set_yticks(range(len(mf1_pivot.index)))
        ax.set_yticklabels(mf1_pivot.index, fontsize=10)
        for i in range(len(mf1_pivot.index)):
            for j in range(len(mf1_pivot.columns)):
                val = mf1_pivot.values[i, j]
                text_color = "white" if val < 0.4 else "black"
                ax.text(j, i, f"{val:.3f}", ha="center", va="center", fontsize=8, color=text_color, fontweight="bold")
        ax.set_title("Model × Feature Group Macro-F1 Heatmap")
        plt.colorbar(im, ax=ax, label="Macro-F1")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "cross_group_macro_f1_heatmap.png", dpi=180)
        plt.close()
        print("✓ cross_group_macro_f1_heatmap.png")

    # ── 11. Per-class F1 distribution comparison (D vs B best models) ──
    d_report = ROOT / "data/features/tcg/classification/results/D/lightgbm/classification_report.csv"
    b_report = ROOT / "data/features/hcg/classification/results/B/lightgbm/classification_report.csv"
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for ax_i, (path, label, color) in enumerate([
        (d_report, "D/lightgbm (TCG emb only)", "#d62728"),
        (b_report, "B/lightgbm (HCG emb only)", "#2ca02c"),
    ]):
        if path.exists():
            cr = pd.read_csv(path, index_col=0)
            if "f1-score" in cr.columns and not cr.empty:
                cls_f1 = cr[cr.index != "weighted avg"]["f1-score"].dropna().sort_values(ascending=False)
                f1_vals = cls_f1.values
                axes[ax_i].bar(range(len(f1_vals)), f1_vals, color=color, alpha=0.8, width=1.0)
                axes[ax_i].axhline(y=0.05, color="gray", linestyle="--", alpha=0.5)
                zero_count = (f1_vals < 0.01).sum()
                nonzero_count = (f1_vals >= 0.01).sum()
                axes[ax_i].set_title(f"Per-class F1: {label}\n({nonzero_count} classes ≥0.01, {zero_count} near-zero)")
                axes[ax_i].set_xlabel("Class rank (sorted by F1)")
                axes[ax_i].set_ylabel("F1-score")
    fig.suptitle("Per-Class F1 Distribution: TCG vs HCG Embeddings", fontsize=13)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "per_class_f1_D_vs_B.png", dpi=180)
    plt.close()
    print("✓ per_class_f1_D_vs_B.png")

    print(f"\nAll figures saved to {FIG_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
