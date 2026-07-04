#!/usr/bin/env python3
"""Upload classification datasets A/B/C/D/E/F to HuggingFace Hub or ModelScope."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_REPO_ID = "MarkTom/IP-Network-Flow-Graph"

DATASET_DESCRIPTIONS = {
    "A_raw_flow_features.parquet": "Dataset A: raw flow statistical features",
    "B_hcg_flow_emb_256.parquet": "Dataset B: HCG graph embedding flow features",
    "C_raw_plus_hcg_flow_emb.parquet": "Dataset C: raw + HCG features",
    "D_tcg_flow_node2vec_d128_light_shrcr.parquet": "Dataset D: TCG graph embedding flow features",
    "E_raw_plus_tcg_d128_light_shrcr.parquet": "Dataset E: raw + TCG features",
    "F_raw_plus_hcg_plus_tcg_d128_light_shrcr.parquet": "Dataset F: raw + HCG + TCG features",
}


def collect_upload_files(dataset_dir: Path, include_derived: bool) -> list[tuple[str, str]]:
    files = []
    for filename, description in DATASET_DESCRIPTIONS.items():
        if not include_derived and filename.startswith(("C_", "E_", "F_")):
            continue
        if (dataset_dir / filename).exists():
            files.append((filename, description))
    return files


def render_readme(files_to_upload: list[tuple[str, str]]) -> str:
    rows = []
    for filename, description in DATASET_DESCRIPTIONS.items():
        rows.append(f"| `{filename}` | {description} |")
    file_table = "\n".join(rows) if rows else "| _No parquet files uploaded_ | - |"
    return f"""---
license: apache-2.0
task_categories:
- tabular-classification
tags:
- network-traffic
- graph-embedding
- tugraph
size_categories:
- 1M<n<10M
---

# IP Network Flow Graph Classification Datasets

This dataset contains classification feature tables derived from the Unicauca/IP Network Traffic Flows dataset and graph embeddings built with TuGraph.

## Files

| File | Description |
| --- | --- |
{file_table}

## Feature Groups

- A: raw flow statistical features.
- B: HCG embedding features.
- C: A + B fused features.
- D: TCG embedding features.
- E: A + D fused features.
- F: C + D fused features.

Derived groups C/E/F can be regenerated locally from A/B/D with the project scripts, but may also be hosted directly for convenience.

## Usage

```bash
PYTHONPATH=src python3 scripts/download_datasets_from_hub.py \\
  --hub modelscope \\
  --repo-id MarkTom/IP-Network-Flow-Graph \\
  --dataset-kind hcg

PYTHONPATH=src python3 scripts/download_datasets_from_hub.py \\
  --hub modelscope \\
  --repo-id MarkTom/IP-Network-Flow-Graph \\
  --dataset-kind tcg
```

## Citation

If you use this dataset, please cite the original Unicauca dataset:

- Rojas, J. S., et al. "IP Network Traffic Flows Labeled with 87 Apps." Kaggle, 2018.

## License

Apache 2.0
"""


def upload_to_huggingface(dataset_dir: Path, repo_id: str, private: bool, include_derived: bool) -> None:
    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:
        print("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    files_to_upload = collect_upload_files(dataset_dir, include_derived)
    if not files_to_upload:
        print(f"ERROR: No known dataset files found in {dataset_dir}")
        sys.exit(1)

    create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)
    api = HfApi()
    print(f"Repository {repo_id} ready")

    for filename, description in files_to_upload:
        filepath = dataset_dir / filename
        print(f"Uploading {filename} ({filepath.stat().st_size / 1024 / 1024:.1f} MB)...")
        api.upload_file(
            path_or_fileobj=str(filepath),
            path_in_repo=filename,
            repo_id=repo_id,
            repo_type="dataset",
        )
        print(f"  Uploaded {filename}: {description}")

    api.upload_file(
        path_or_fileobj=render_readme(files_to_upload).encode(),
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="dataset",
    )
    print(f"\nUpload complete! View at: https://huggingface.co/datasets/{repo_id}")


def upload_to_modelscope(dataset_dir: Path, repo_id: str, include_derived: bool) -> None:
    try:
        from modelscope.hub.api import HubApi
    except ImportError:
        print("ERROR: modelscope not installed. Run: pip install modelscope")
        sys.exit(1)

    files_to_upload = collect_upload_files(dataset_dir, include_derived)
    if not files_to_upload:
        print(f"ERROR: No known dataset files found in {dataset_dir}")
        sys.exit(1)

    api = HubApi()
    if not api.repo_exists(repo_id, repo_type="dataset"):
        print(f"ERROR: Dataset repo {repo_id} not found on ModelScope.")
        print(f"Create it at: https://modelscope.cn/datasets/{repo_id}")
        sys.exit(1)

    print(f"Dataset repo {repo_id} found, uploading files...")
    for filename, description in files_to_upload:
        filepath = dataset_dir / filename
        size_mb = filepath.stat().st_size / 1024 / 1024
        print(f"Uploading {filename} ({size_mb:.1f} MB)...")
        api.upload_file(
            path_or_fileobj=str(filepath),
            path_in_repo=filename,
            repo_id=repo_id,
            repo_type="dataset",
            commit_message=f"Upload {filename}",
        )
        print(f"  Uploaded {filename}: {description}")

    api.upload_file(
        path_or_fileobj=render_readme(files_to_upload).encode(),
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="dataset",
        commit_message="Update dataset README",
    )
    print(f"\nUpload complete! View at: https://modelscope.cn/datasets/{repo_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload classification datasets to Hub")
    parser.add_argument("--hub", choices=["huggingface", "modelscope"], default="modelscope")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--dataset-dir", default="data/features/hcg/classification/datasets")
    parser.add_argument("--private", action="store_true", help="Make repository private (HuggingFace only)")
    parser.add_argument(
        "--include-derived",
        action="store_true",
        help="Also upload derived C/E/F files when present. By default only source groups A/B/D are uploaded.",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    if not dataset_dir.exists():
        print(f"ERROR: Dataset directory not found: {dataset_dir}")
        return 1

    print(f"Hub: {args.hub}")
    print(f"Repository: {args.repo_id}")
    print(f"Dataset dir: {dataset_dir}")
    print(f"Include derived: {args.include_derived}")
    print()

    if args.hub == "huggingface":
        upload_to_huggingface(dataset_dir, args.repo_id, args.private, args.include_derived)
    else:
        upload_to_modelscope(dataset_dir, args.repo_id, args.include_derived)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
