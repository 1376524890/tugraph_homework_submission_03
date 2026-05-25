#!/usr/bin/env python3
"""Prepare a portable bundle for HCG classification training without TuGraph."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path
from typing import Any

from tugraph_homework.common import ROOT


DATASET_FILES = {
    "A": "A_raw_flow_features.parquet",
    "B": "B_hcg_flow_emb_256.parquet",
    "C": "C_raw_plus_hcg_flow_emb.parquet",
}
TRAINING_SCRIPTS = [
    "scripts/train_hcg_classifiers.py",
    "scripts/check_hcg_classifier_results.py",
    "scripts/render_hcg_classification_figures.py",
    "scripts/check_hcg_classification_features.py",
    "scripts/prepare_hcg_classification_training_bundle.py",
    "scripts/run_hcg_classification_all.sh",
    "scripts/run_hcg_classification_smoke.sh",
]
DOC_FILES = [
    "README.md",
    "AGENTS.md",
    "docs/experiment_record.md",
    "data/features/hcg/classification/reports/hcg_classification_feature_check_report.md",
    "data/features/hcg/classification/reports/hcg_classification_feature_check_report.json",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare portable HCG classification training bundle.")
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "data/features/hcg/classification/datasets")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/exports/hcg_classification_training_bundle")
    parser.add_argument("--feature-groups", default="A,B,C")
    parser.add_argument("--include-smoke-datasets", action="store_true")
    parser.add_argument("--link", action="store_true", help="Hardlink files when possible instead of copying.")
    parser.add_argument("--archive", action="store_true", help="Create a tar archive next to output-dir.")
    parser.add_argument("--compress", choices=["none", "gz"], default="none")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def sha256_file(path: Path, chunk_size: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def copy_or_link(src: Path, dst: Path, link: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    if link:
        try:
            dst.hardlink_to(src)
            return
        except OSError:
            pass
    shutil.copy2(src, dst)


def add_file(manifest: list[dict[str, Any]], src: Path, dst_root: Path, rel: Path, link: bool) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    dst = dst_root / rel
    copy_or_link(src, dst, link)
    manifest.append(
        {
            "path": str(rel),
            "bytes": dst.stat().st_size,
            "sha256": sha256_file(dst),
        }
    )


def write_requirements(output_dir: Path) -> None:
    text = "\n".join(
        [
            "numpy",
            "pandas",
            "pyarrow",
            "scikit-learn",
            "joblib",
            "lightgbm",
            "matplotlib",
            "rich",
            "tqdm",
            "tensorboard",
            "tensorboardX",
            "",
        ]
    )
    (output_dir / "requirements-classification.txt").write_text(text, encoding="utf-8")


def write_readme(output_dir: Path, feature_groups: list[str]) -> None:
    groups = ",".join(feature_groups)
    text = f"""# HCG Classification Training Bundle

This bundle is enough to run classifier training on a machine without TuGraph.
It contains generated A/B/C parquet feature datasets, training scripts, shared
Python helpers, and experiment documentation. It does not contain raw CSV data,
TuGraph database files, Node2Vec walks, or Word2Vec models.

## Environment

```bash
python3 -m pip install -r requirements-classification.txt
```

## Smoke Run

```bash
PYTHONPATH=src python3 scripts/train_hcg_classifiers.py \\
  --dataset-dir data/features/hcg/classification/datasets \\
  --output-dir data/features/hcg/classification/results_smoke \\
  --runs-dir runs/hcg_classification_smoke \\
  --feature-groups {groups} \\
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \\
  --sample-train 100000 \\
  --sample-valid 20000 \\
  --sample-test 20000 \\
  --knn-train-sample 50000 \\
  --knn-test-sample 20000 \\
  --tensorboard \\
  --progress \\
  --render-figures \\
  --seed 20260525 \\
  --resume
```

## Full Run

```bash
PYTHONPATH=src python3 scripts/train_hcg_classifiers.py \\
  --dataset-dir data/features/hcg/classification/datasets \\
  --output-dir data/features/hcg/classification/results \\
  --runs-dir runs/hcg_classification \\
  --feature-groups {groups} \\
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \\
  --tensorboard \\
  --progress \\
  --render-figures \\
  --seed 20260525 \\
  --resume
```

Memory guard and task isolation are enabled by default. Tasks estimated to be
too large for the target machine will be marked as skipped instead of loading
the parquet dataset.
"""
    (output_dir / "README_BUNDLE.md").write_text(text, encoding="utf-8")


def create_archive(output_dir: Path, compress: str) -> Path:
    suffix = ".tar.gz" if compress == "gz" else ".tar"
    archive_path = output_dir.with_suffix(suffix)
    mode = "w:gz" if compress == "gz" else "w"
    if archive_path.exists():
        archive_path.unlink()
    with tarfile.open(archive_path, mode) as tar:
        tar.add(output_dir, arcname=output_dir.name)
    return archive_path


def main() -> int:
    args = parse_args()
    args.dataset_dir = resolve_path(args.dataset_dir)
    args.output_dir = resolve_path(args.output_dir)
    feature_groups = parse_csv_list(args.feature_groups)
    unknown = [group for group in feature_groups if group not in DATASET_FILES]
    if unknown:
        raise ValueError(f"Unknown feature groups: {', '.join(unknown)}")
    if args.output_dir.exists():
        if not args.force:
            raise FileExistsError(f"{args.output_dir} already exists. Use --force to replace it.")
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    for rel in TRAINING_SCRIPTS:
        add_file(manifest, ROOT / rel, args.output_dir, Path(rel), args.link)
    for src in (ROOT / "src/tugraph_homework").glob("*.py"):
        add_file(manifest, src, args.output_dir, Path("src/tugraph_homework") / src.name, args.link)
    for rel in DOC_FILES:
        src = ROOT / rel
        if src.exists():
            add_file(manifest, src, args.output_dir, Path(rel), args.link)
    for group in feature_groups:
        filename = DATASET_FILES[group]
        add_file(
            manifest,
            args.dataset_dir / filename,
            args.output_dir,
            Path("data/features/hcg/classification/datasets") / filename,
            args.link,
        )
    if args.include_smoke_datasets:
        smoke_dir = args.dataset_dir.parent / "datasets_smoke"
        for group in feature_groups:
            filename = DATASET_FILES[group]
            src = smoke_dir / filename
            if src.exists():
                add_file(
                    manifest,
                    src,
                    args.output_dir,
                    Path("data/features/hcg/classification/datasets_smoke") / filename,
                    args.link,
                )

    write_requirements(args.output_dir)
    write_readme(args.output_dir, feature_groups)
    summary = {
        "feature_groups": feature_groups,
        "file_count": len(manifest),
        "total_bytes": sum(int(row["bytes"]) for row in manifest),
        "total_gib": sum(int(row["bytes"]) for row in manifest) / (1024**3),
        "files": manifest,
    }
    (args.output_dir / "bundle_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.archive:
        archive = create_archive(args.output_dir, args.compress)
        print(f"Archive: {archive}")
    print(f"Bundle: {args.output_dir}")
    print(f"Files: {summary['file_count']}")
    print(f"Size GiB: {summary['total_gib']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
