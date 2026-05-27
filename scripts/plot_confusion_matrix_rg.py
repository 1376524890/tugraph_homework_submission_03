#!/usr/bin/env python3
"""Red/Green confusion matrix: diagonal=green (correct), off-diagonal=red (error)."""
import argparse, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np


def plot_confusion_matrix(cm_path: str, output_path: str | None = None,
                          top_n: int = 20, dpi: int = 180):
    cm = pd.read_csv(cm_path, index_col=0)
    top = cm.sum(axis=1).sort_values(ascending=False).head(top_n).index
    sub = cm.loc[top, top].astype(float)
    denom = sub.sum(axis=1).replace(0, 1)
    norm = sub.div(denom, axis=0)
    n = len(top)

    # Build separate layers: diagonal (green) and off-diagonal (red)
    diag = np.zeros((n, n))
    offdiag = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                diag[i, j] = norm.iloc[i, j]
            else:
                offdiag[i, j] = norm.iloc[i, j]

    fig, ax = plt.subplots(figsize=(12, 10))

    # Red layer for off-diagonal (errors)
    if offdiag.max() > 0:
        red_cmap = plt.cm.Reds
        ax.imshow(offdiag, aspect="auto", cmap=red_cmap, vmin=0, vmax=0.3)

    # Green layer for diagonal (correct) — rendered on top via masked array
    diag_masked = np.ma.masked_where(diag == 0, diag)
    green_cmap = plt.cm.Greens
    ax.imshow(diag_masked, aspect="auto", cmap=green_cmap, vmin=0, vmax=1.0)

    # Diagonal marker for emphasis
    for i in range(n):
        v = diag[i, i]
        color = plt.cm.Greens(min(v, 1.0))
        ax.add_patch(plt.Rectangle((i - 0.5, i - 0.5), 1, 1, fill=False,
                                    edgecolor="limegreen" if v > 0.5 else "darkgreen",
                                    linewidth=1.5))

    ax.set_xticks(range(n))
    ax.set_xticklabels(top, rotation=90, fontsize=7)
    ax.set_yticks(range(n))
    ax.set_yticklabels(top, fontsize=7)
    ax.set_xlabel("Predicted", fontsize=11)
    ax.set_ylabel("True", fontsize=11)
    ax.set_title(f"Confusion Matrix Top {n} — Green=Correct (diagonal), Red=Errors", fontsize=12)

    model_name = Path(cm_path).parent.parent.name if Path(cm_path).parent.parent.name != "results" else ""
    plt.tight_layout()

    out = Path(output_path) if output_path else Path(cm_path).parent / "figures" / "confusion_matrix_rg.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=dpi)
    plt.close()
    print(f"Saved: {out}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Red/Green confusion matrix plot")
    parser.add_argument("cm_csv", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("-n", "--top-n", type=int, default=20)
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--all", action="store_true", help="Regenerate for all completed tasks")
    args = parser.parse_args()

    if args.all:
        results = Path("data/features/hcg/classification/results")
        for cm in sorted(results.glob("*/*/confusion_matrix.csv")):
            plot_confusion_matrix(str(cm), top_n=args.top_n, dpi=args.dpi)
    else:
        plot_confusion_matrix(str(args.cm_csv), str(args.output) if args.output else None,
                              top_n=args.top_n, dpi=args.dpi)
