#!/usr/bin/env python3
"""
Download HCG classification datasets from HuggingFace Hub or ModelScope.

Dataset C is automatically synthesized from A + B after download.

Usage:
    # Download from HuggingFace
    PYTHONPATH=src python3 scripts/download_datasets_from_hub.py --hub huggingface --repo-id MarkTom/IP-Network-Flow-HCG

    # Download from ModelScope
    PYTHONPATH=src python3 scripts/download_datasets_from_hub.py --hub modelscope --repo-id MarkTom/IP-Network-Flow-HCG
"""

import argparse
import hashlib
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# MD5 checksums for dataset files (generated once, embedded for offline verification)
DATASET_MD5 = {
    "A_raw_flow_features.parquet": "50072934250a8524bf160e0b287712b8",
    "B_hcg_flow_emb_256.parquet": "4b34e01f91ac37f186bb2eaf3e345258",
}


def _md5(filepath: Path) -> str:
    """Compute MD5 hash of a file (streaming, memory-safe)."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_md5(dataset_dir: Path, filename: str):
    """Verify MD5 of a downloaded file against the embedded checksum."""
    expected = DATASET_MD5.get(filename)
    if not expected:
        return  # no reference hash, skip
    filepath = dataset_dir / filename
    actual = _md5(filepath)
    if actual != expected:
        print(f"  WARNING: MD5 mismatch for {filename}")
        print(f"    expected: {expected}")
        print(f"    actual:   {actual}")
    else:
        print(f"  MD5 verified: {filename}")


def _need_download(dataset_dir: Path, filename: str) -> bool:
    """Return True if the file needs to be downloaded."""
    filepath = dataset_dir / filename
    if not filepath.exists():
        return True
    print(f"  {filename} already exists, skipping download")
    _verify_md5(dataset_dir, filename)
    return False


def download_from_huggingface(dataset_dir: Path, repo_id: str):
    """Download datasets from HuggingFace Hub."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    dataset_dir.mkdir(parents=True, exist_ok=True)

    files_to_download = [
        "A_raw_flow_features.parquet",
        "B_hcg_flow_emb_256.parquet",
    ]

    for filename in files_to_download:
        if not _need_download(dataset_dir, filename):
            continue

        print(f"  Downloading {filename}...")
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            repo_type="dataset",
            local_dir=str(dataset_dir),
        )
        print(f"  Downloaded {filename}")
        _verify_md5(dataset_dir, filename)


def download_from_modelscope(dataset_dir: Path, repo_id: str):
    """Download datasets from ModelScope."""
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError:
        print("ERROR: modelscope not installed. Run: pip install modelscope")
        sys.exit(1)

    dataset_dir.mkdir(parents=True, exist_ok=True)

    files_to_download = [
        "A_raw_flow_features.parquet",
        "B_hcg_flow_emb_256.parquet",
    ]

    need_files = [f for f in files_to_download if _need_download(dataset_dir, f)]
    if not need_files:
        return

    print(f"  Downloading from ModelScope: {repo_id}...")
    snapshot_download(
        repo_id,
        local_dir=str(dataset_dir),
        allow_file_pattern=need_files,
        repo_type="dataset",
    )
    print(f"  Downloaded to {dataset_dir}")

    for filename in files_to_download:
        _verify_md5(dataset_dir, filename)


def synthesize_dataset_c(dataset_dir: Path):
    """Synthesize dataset C from A and B."""
    import pandas as pd

    a_path = dataset_dir / "A_raw_flow_features.parquet"
    b_path = dataset_dir / "B_hcg_flow_emb_256.parquet"
    c_path = dataset_dir / "C_raw_plus_hcg_flow_emb.parquet"

    if c_path.exists():
        print("  Dataset C already exists, skipping synthesis")
        return

    if not a_path.exists() or not b_path.exists():
        print("  WARNING: Cannot synthesize C - A or B missing")
        return

    print("  Synthesizing dataset C from A + B...")
    a = pd.read_parquet(a_path)
    b = pd.read_parquet(b_path)

    meta_cols = ['record_id', 'target', 'split', 'src_endpoint', 'dst_endpoint']
    b_feat = b.drop(columns=meta_cols)
    c = pd.concat([a, b_feat], axis=1)

    c.to_parquet(c_path, compression='snappy', index=False)
    print(f"  Synthesized C: {len(c)} rows, {len(c.columns)} columns")


def main():
    parser = argparse.ArgumentParser(description="Download HCG classification datasets from Hub")
    parser.add_argument(
        "--hub",
        choices=["huggingface", "modelscope"],
        default="huggingface",
        help="Source hub (default: huggingface)",
    )
    parser.add_argument(
        "--repo-id",
        required=True,
        help="Repository ID (e.g., username/tugraph-hcg-classification)",
    )
    parser.add_argument(
        "--dataset-dir",
        default="data/features/hcg/classification/datasets",
        help="Directory to save datasets",
    )
    parser.add_argument(
        "--skip-synthesis",
        action="store_true",
        help="Skip automatic synthesis of dataset C",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)

    print(f"Hub: {args.hub}")
    print(f"Repository: {args.repo_id}")
    print(f"Dataset dir: {dataset_dir}")
    print()

    print("Downloading datasets A and B...")
    if args.hub == "huggingface":
        download_from_huggingface(dataset_dir, args.repo_id)
    else:
        download_from_modelscope(dataset_dir, args.repo_id)

    if not args.skip_synthesis:
        print("\nSynthesizing dataset C...")
        synthesize_dataset_c(dataset_dir)

    print("\nDownload complete!")
    print(f"Datasets saved to: {dataset_dir}")
    print("\nAvailable files:")
    for f in sorted(dataset_dir.glob("*.parquet")):
        print(f"  - {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
