#!/usr/bin/env python3
"""Render static Matplotlib figures for HCG classifier results."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from tugraph_homework.common import ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render HCG classification result figures.")
    parser.add_argument("--results-dir", type=Path, default=ROOT / "data/features/hcg/classification/results")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def load_summary(results_dir: Path) -> pd.DataFrame:
    path = results_dir / "classifier_summary.csv"
    if path.exists():
        return pd.read_csv(path)
    live = results_dir / "metrics_live.csv"
    if live.exists():
        return pd.read_csv(live)
    rows = []
    for metrics_path in sorted(results_dir.glob("*/*/metrics.json")):
        metrics = pd.read_json(metrics_path, typ="series").to_dict()
        rows.append(
            {
                "feature_group": metrics_path.parents[1].name,
                "model_name": metrics_path.parent.name,
                "status": "completed",
                **metrics,
                "metrics_path": str(metrics_path),
            }
        )
    return pd.DataFrame(rows)


def require_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError as exc:
        raise SystemExit("matplotlib is required for rendering figures. Install with: python3 -m pip install matplotlib") from exc


def grouped_bar(plt, df: pd.DataFrame, metric: str, output: Path, title: str, ylabel: str) -> None:
    completed = df[df["status"].fillna("") == "completed"].copy()
    if completed.empty or metric not in completed:
        return
    pivot = completed.pivot_table(index="model_name", columns="feature_group", values=metric, aggfunc="max")
    ax = pivot.plot(kind="bar", figsize=(10, 5.5), width=0.78)
    ax.set_title(title)
    ax.set_xlabel("Model")
    ax.set_ylabel(ylabel)
    ax.legend(title="Feature group")
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(output, dpi=180)
    plt.close()


def scatter_time(plt, df: pd.DataFrame, output: Path) -> None:
    completed = df[df["status"].fillna("") == "completed"].copy()
    if completed.empty or "macro_f1" not in completed or "train_seconds" not in completed:
        return
    plt.figure(figsize=(8, 5.2))
    for fg, part in completed.groupby("feature_group"):
        plt.scatter(part["train_seconds"], part["macro_f1"], label=fg, s=60)
        for _, row in part.iterrows():
            plt.annotate(str(row["model_name"]), (row["train_seconds"], row["macro_f1"]), fontsize=8, xytext=(4, 3), textcoords="offset points")
    plt.xlabel("Train seconds")
    plt.ylabel("Macro-F1")
    plt.title("Macro-F1 vs train time")
    plt.legend(title="Feature group")
    plt.tight_layout()
    plt.savefig(output, dpi=180)
    plt.close()


def gain_plot(plt, df: pd.DataFrame, base: str, output: Path, title: str) -> None:
    completed = df[df["status"].fillna("") == "completed"].copy()
    if completed.empty:
        return
    pivot = completed.pivot_table(index="model_name", columns="feature_group", values="macro_f1", aggfunc="max")
    if "C" not in pivot or base not in pivot:
        return
    gain = (pivot["C"] - pivot[base]).dropna().sort_values(ascending=False)
    if gain.empty:
        return
    plt.figure(figsize=(8, 4.8))
    plt.bar(gain.index, gain.values)
    plt.axhline(0, color="black", linewidth=0.8)
    plt.xlabel("Model")
    plt.ylabel("Macro-F1 gain")
    plt.title(title)
    plt.xticks(rotation=35, ha="right")
    plt.tight_layout()
    plt.savefig(output, dpi=180)
    plt.close()


def copy_learning_curves(plt, results_dir: Path, fig_dir: Path, model: str, prefix: str) -> None:
    for fg in ("A", "B", "C"):
        path = results_dir / fg / model / "eval_history.csv"
        if not path.exists():
            continue
        hist = pd.read_csv(path)
        if hist.empty:
            continue
        plt.figure(figsize=(8, 4.8))
        x = hist["iteration"] if "iteration" in hist else hist.index + 1
        cols = ["valid_multi_logloss", "valid_macro_f1", "valid_weighted_f1", "valid_accuracy"] if model == "lightgbm" else [
            "valid_macro_f1",
            "valid_weighted_f1",
            "valid_accuracy",
        ]
        for col in cols:
            if col in hist:
                plt.plot(x, hist[col], label=col)
        plt.xlabel("Iteration")
        plt.ylabel("Metric")
        plt.title(f"{model} learning curve {fg}")
        plt.legend()
        plt.tight_layout()
        plt.savefig(fig_dir / f"{prefix}_learning_curve_{fg}.png", dpi=180)
        plt.close()


def best_confusion_matrix(plt, df: pd.DataFrame, results_dir: Path, fig_dir: Path) -> None:
    completed = df[df["status"].fillna("") == "completed"].copy()
    if completed.empty or "macro_f1" not in completed:
        return
    row = completed.sort_values("macro_f1", ascending=False).iloc[0]
    cm_path = results_dir / str(row["feature_group"]) / str(row["model_name"]) / "confusion_matrix.csv"
    if not cm_path.exists():
        return
    cm = pd.read_csv(cm_path, index_col=0)
    top = cm.sum(axis=1).sort_values(ascending=False).head(20).index
    sub = cm.loc[top, top].astype(float)
    norm = sub.div(sub.sum(axis=1).replace(0, 1), axis=0)
    plt.figure(figsize=(10, 8))
    plt.imshow(norm.to_numpy(), aspect="auto", cmap="Blues")
    plt.xticks(range(len(top)), top, rotation=90, fontsize=7)
    plt.yticks(range(len(top)), top, fontsize=7)
    plt.colorbar(label="Row-normalized count")
    plt.title(f"Best model confusion matrix: {row['feature_group']}/{row['model_name']}")
    plt.tight_layout()
    plt.savefig(fig_dir / "confusion_matrix_best_model.png", dpi=180)
    plt.close()


def lightgbm_importance(plt, results_dir: Path, fig_dir: Path) -> None:
    path = results_dir / "C" / "lightgbm" / "feature_importance_gain.csv"
    if not path.exists():
        return
    imp = pd.read_csv(path)
    if imp.empty:
        return
    top = imp.sort_values("importance", ascending=False).head(30)
    plt.figure(figsize=(9, 7))
    plt.barh(top["feature"][::-1], top["importance"][::-1])
    plt.xlabel("Gain importance")
    plt.title("C LightGBM feature importance top 30")
    plt.tight_layout()
    plt.savefig(fig_dir / "lightgbm_feature_importance_C_top30.png", dpi=180)
    plt.close()

    def group_name(feature: str) -> str:
        if feature in {"hcg_src_emb_missing", "hcg_dst_emb_missing"}:
            return "hcg_missing_flags"
        if feature.startswith("raw_"):
            return "raw_*"
        if feature.startswith("hcg_src_emb_"):
            return "hcg_src_emb_*"
        if feature.startswith("hcg_dst_emb_"):
            return "hcg_dst_emb_*"
        if feature.startswith("hcg_absdiff_emb_"):
            return "hcg_absdiff_emb_*"
        if feature.startswith("hcg_prod_emb_"):
            return "hcg_prod_emb_*"
        return "other"

    grouped = imp.assign(group=imp["feature"].map(group_name)).groupby("group", as_index=False)["importance"].sum()
    grouped = grouped.sort_values("importance", ascending=False)
    plt.figure(figsize=(8, 4.8))
    plt.bar(grouped["group"], grouped["importance"])
    plt.xlabel("Feature group")
    plt.ylabel("Gain importance")
    plt.title("C LightGBM raw vs HCG feature importance")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    plt.savefig(fig_dir / "raw_vs_hcg_feature_importance_C.png", dpi=180)
    plt.close()


def main() -> int:
    args = parse_args()
    results_dir = resolve_path(args.results_dir)
    fig_dir = results_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    plt = require_matplotlib()
    df = load_summary(results_dir)
    if df.empty:
        return 0
    grouped_bar(plt, df, "macro_f1", fig_dir / "macro_f1_by_model_feature_group.png", "Macro-F1 by model and feature group", "Macro-F1")
    grouped_bar(plt, df, "weighted_f1", fig_dir / "weighted_f1_by_model_feature_group.png", "Weighted-F1 by model and feature group", "Weighted-F1")
    grouped_bar(plt, df, "accuracy", fig_dir / "accuracy_by_model_feature_group.png", "Accuracy by model and feature group", "Accuracy")
    grouped_bar(plt, df, "train_seconds", fig_dir / "train_time_by_model_feature_group.png", "Train time by model and feature group", "Seconds")
    grouped_bar(plt, df, "inference_seconds", fig_dir / "inference_time_by_model_feature_group.png", "Inference time by model and feature group", "Seconds")
    scatter_time(plt, df, fig_dir / "macro_f1_vs_train_time.png")
    gain_plot(plt, df, "A", fig_dir / "C_vs_A_macro_f1_gain.png", "C vs A Macro-F1 gain")
    gain_plot(plt, df, "B", fig_dir / "C_vs_B_macro_f1_gain.png", "C vs B Macro-F1 gain")
    copy_learning_curves(plt, results_dir, fig_dir, "lightgbm", "lightgbm")
    copy_learning_curves(plt, results_dir, fig_dir, "logistic_sgd", "logistic")
    best_confusion_matrix(plt, df, results_dir, fig_dir)
    lightgbm_importance(plt, results_dir, fig_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
