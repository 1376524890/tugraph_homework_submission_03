#!/usr/bin/env python3
"""
Upload HCG classification datasets (A and B) to HuggingFace Hub or ModelScope.

Dataset C is derived from A + B and does not need to be uploaded.

Usage:
    # Upload to HuggingFace
    PYTHONPATH=src python3 scripts/upload_datasets_to_hub.py --hub huggingface --repo-id <username>/tugraph-hcg-classification

    # Upload to ModelScope
    PYTHONPATH=src python3 scripts/upload_datasets_to_hub.py --hub modelscope --repo-id <username>/tugraph-hcg-classification
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def upload_to_huggingface(dataset_dir: Path, repo_id: str, private: bool = False):
    """Upload datasets to HuggingFace Hub."""
    try:
        from huggingface_hub import HfApi, create_repo
    except ImportError:
        print("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    api = HfApi()

    # Create repo if it doesn't exist
    try:
        create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)
        print(f"Repository {repo_id} ready")
    except Exception as e:
        print(f"ERROR creating repository: {e}")
        sys.exit(1)

    # Upload files
    files_to_upload = [
        ("A_raw_flow_features.parquet", "Dataset A: Raw flow statistical features (91 features)"),
        ("B_hcg_flow_emb_256.parquet", "Dataset B: HCG graph embedding features (258 features)"),
    ]

    for filename, description in files_to_upload:
        filepath = dataset_dir / filename
        if not filepath.exists():
            print(f"WARNING: {filepath} not found, skipping")
            continue

        print(f"Uploading {filename} ({filepath.stat().st_size / 1024 / 1024:.1f} MB)...")
        api.upload_file(
            path_or_fileobj=str(filepath),
            path_in_repo=filename,
            repo_id=repo_id,
            repo_type="dataset",
        )
        print(f"  Uploaded {filename}")

    # Upload README
    readme_content = f"""---
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

# TuGraph HCG Classification Datasets

This dataset contains features for network traffic flow classification using Host Communication Graph (HCG) embeddings.

## Dataset Description

Based on the Unicauca 87-attribute network flow dataset (3,577,296 flows, 78 protocol classes).

### Dataset A: Raw Flow Features
- **File**: `A_raw_flow_features.parquet`
- **Size**: ~562 MB
- **Rows**: 3,577,296
- **Features**: 91 raw statistical features extracted from network flow attributes
- **Columns**: 5 metadata + 91 features

### Dataset B: HCG Embedding Features
- **File**: `B_hcg_flow_emb_256.parquet`
- **Size**: ~2.7 GB
- **Rows**: 3,577,296
- **Features**: 258 HCG graph embedding features (Node2Vec + Word2Vec)
- **Columns**: 5 metadata + 258 features (4 groups × 64 dimensions)

### Dataset C: Combined Features (Not uploaded, can be synthesized)
- Synthesized by concatenating A and B
- 91 raw + 258 HCG = 349 features

## Metadata Columns

| Column | Description |
|--------|-------------|
| `record_id` | Unique flow identifier |
| `target` | Protocol name (classification target, 78 classes) |
| `split` | Data split: train/valid/test |
| `src_endpoint` | Source endpoint identifier |
| `dst_endpoint` | Destination endpoint identifier |

## Usage

```python
import pandas as pd

# Load dataset A
df_a = pd.read_parquet("A_raw_flow_features.parquet")

# Load dataset B
df_b = pd.read_parquet("B_hcg_flow_emb_256.parquet")

# Synthesize dataset C
meta_cols = ['record_id', 'target', 'split', 'src_endpoint', 'dst_endpoint']
df_c = pd.concat([df_a, df_b.drop(columns=meta_cols)], axis=1)
```

## Citation

If you use this dataset, please cite the original Unicauca dataset:
- Rojas, J. S., et al. "IP Network Traffic Flows Labeled with 87 Apps." Kaggle, 2018.

## License

Apache 2.0
"""

    api.upload_file(
        path_or_fileobj=readme_content.encode(),
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="dataset",
    )
    print("  Uploaded README.md")

    print(f"\nUpload complete! View at: https://huggingface.co/datasets/{repo_id}")


def upload_to_modelscope(dataset_dir: Path, repo_id: str):
    """Upload datasets to ModelScope."""
    try:
        from modelscope.hub.api import HubApi
        from modelscope.hub.constants import ModelScopeConfig
    except ImportError:
        print("ERROR: modelscope not installed. Run: pip install modelscope")
        sys.exit(1)

    api = HubApi()

    # Note: ModelScope dataset upload requires different API
    # This is a simplified version - may need adjustment based on ModelScope SDK version
    print("ModelScope upload requires manual setup:")
    print(f"1. Create dataset repo at: https://modelscope.cn/datasets/{repo_id}")
    print(f"2. Upload files from: {dataset_dir}")
    print()
    print("Files to upload:")
    for f in ["A_raw_flow_features.parquet", "B_hcg_flow_emb_256.parquet"]:
        fp = dataset_dir / f
        if fp.exists():
            print(f"  - {f} ({fp.stat().st_size / 1024 / 1024:.1f} MB)")
        else:
            print(f"  - {f} (NOT FOUND)")


def main():
    parser = argparse.ArgumentParser(description="Upload HCG classification datasets to Hub")
    parser.add_argument(
        "--hub",
        choices=["huggingface", "modelscope"],
        default="huggingface",
        help="Target hub (default: huggingface)",
    )
    parser.add_argument(
        "--repo-id",
        required=True,
        help="Repository ID (e.g., username/tugraph-hcg-classification)",
    )
    parser.add_argument(
        "--dataset-dir",
        default="data/features/hcg/classification/datasets",
        help="Directory containing dataset files",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Make repository private (HuggingFace only)",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    if not dataset_dir.exists():
        print(f"ERROR: Dataset directory not found: {dataset_dir}")
        sys.exit(1)

    print(f"Hub: {args.hub}")
    print(f"Repository: {args.repo_id}")
    print(f"Dataset dir: {dataset_dir}")
    print()

    if args.hub == "huggingface":
        upload_to_huggingface(dataset_dir, args.repo_id, args.private)
    else:
        upload_to_modelscope(dataset_dir, args.repo_id)


if __name__ == "__main__":
    main()
