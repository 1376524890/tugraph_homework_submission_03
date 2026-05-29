#!/usr/bin/env python3
"""
Download classification datasets from HuggingFace Hub or ModelScope.

Supports:
- HCG datasets (A, B) from MarkTom/IP-Network-Flow-HCG, with C auto-synthesized
- TCG dataset (D) from MarkTom/IP-Network-Flow-Graph, with E/F auto-synthesized

Usage:
    # Download HCG datasets (A, B, auto-synthesize C)
    PYTHONPATH=src python3 scripts/download_datasets_from_hub.py --hub modelscope --repo-id MarkTom/IP-Network-Flow-HCG

    # Download TCG dataset (D, auto-synthesize E, F)
    PYTHONPATH=src python3 scripts/download_datasets_from_hub.py --hub modelscope --repo-id MarkTom/IP-Network-Flow-Graph --dataset-dir data/features/tcg/classification/datasets
"""

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# MD5 checksums for dataset files
DATASET_MD5 = {
    "A_raw_flow_features.parquet": "50072934250a8524bf160e0b287712b8",
    "B_hcg_flow_emb_256.parquet": "4b34e01f91ac37f186bb2eaf3e345258",
}

HCG_FILES = ["A_raw_flow_features.parquet", "B_hcg_flow_emb_256.parquet"]
TCG_FILES = ["D_tcg_flow_node2vec_d64_light_crpr.parquet"]


def _md5(filepath: Path) -> str:
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_md5(dataset_dir: Path, filename: str):
    expected = DATASET_MD5.get(filename)
    if not expected:
        return
    filepath = dataset_dir / filename
    actual = _md5(filepath)
    if actual != expected:
        print(f"  WARNING: MD5 mismatch for {filename}")
        print(f"    expected: {expected}")
        print(f"    actual:   {actual}")
    else:
        print(f"  MD5 verified: {filename}")


def _need_download(dataset_dir: Path, filename: str) -> bool:
    filepath = dataset_dir / filename
    if not filepath.exists():
        return True
    print(f"  {filename} already exists, skipping download")
    _verify_md5(dataset_dir, filename)
    return False


def download_from_huggingface(dataset_dir: Path, repo_id: str, files: list[str]):
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    dataset_dir.mkdir(parents=True, exist_ok=True)
    for filename in files:
        if not _need_download(dataset_dir, filename):
            continue
        print(f"  Downloading {filename}...")
        hf_hub_download(repo_id=repo_id, filename=filename, repo_type="dataset", local_dir=str(dataset_dir))
        print(f"  Downloaded {filename}")
        _verify_md5(dataset_dir, filename)


def download_from_modelscope(dataset_dir: Path, repo_id: str, files: list[str]):
    try:
        from modelscope.hub.snapshot_download import snapshot_download
    except ImportError:
        print("ERROR: modelscope not installed. Run: pip install modelscope")
        sys.exit(1)

    dataset_dir.mkdir(parents=True, exist_ok=True)
    need_files = [f for f in files if _need_download(dataset_dir, f)]
    if not need_files:
        return

    print(f"  Downloading from ModelScope: {repo_id}...")
    snapshot_download(repo_id, local_dir=str(dataset_dir), allow_file_pattern=need_files, repo_type="dataset")
    print(f"  Downloaded to {dataset_dir}")
    for filename in files:
        _verify_md5(dataset_dir, filename)


def synthesize_dataset_c(dataset_dir: Path):
    """Synthesize C from A + B (HCG)."""
    import pandas as pd

    a_path = dataset_dir / "A_raw_flow_features.parquet"
    b_path = dataset_dir / "B_hcg_flow_emb_256.parquet"
    c_path = dataset_dir / "C_raw_plus_hcg_flow_emb.parquet"

    if c_path.exists():
        print("  C already exists, skipping")
        return
    if not a_path.exists() or not b_path.exists():
        print("  WARNING: Cannot synthesize C - A or B missing")
        return

    print("  Synthesizing C from A + B...")
    a = pd.read_parquet(a_path)
    b = pd.read_parquet(b_path)
    meta_cols = ['record_id', 'target', 'split', 'src_endpoint', 'dst_endpoint']
    b_feat = b.drop(columns=[c for c in meta_cols if c in b.columns])
    c = pd.concat([a, b_feat], axis=1)
    c.to_parquet(c_path, compression='snappy', index=False)
    print(f"  Synthesized C: {len(c)} rows, {len(c.columns)} columns")


def synthesize_ef(dataset_dir: Path):
    """Synthesize E and F from A/C + D (TCG)."""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    d_path = dataset_dir / "D_tcg_flow_node2vec_d64_light_crpr.parquet"
    a_path = ROOT / "data/features/hcg/classification/datasets" / "A_raw_flow_features.parquet"
    c_path = ROOT / "data/features/hcg/classification/datasets" / "C_raw_plus_hcg_flow_emb.parquet"
    e_path = dataset_dir / "E_raw_plus_tcg_d64_light_crpr.parquet"
    f_path = dataset_dir / "F_raw_plus_hcg_plus_tcg_d64_light_crpr.parquet"

    if not d_path.exists():
        print("  WARNING: D not found, cannot synthesize E/F")
        return

    d_pf = pq.ParquetFile(d_path)
    d_cols = d_pf.schema_arrow.names
    d_tcg_cols = [
        c for c in d_cols
        if c.startswith("emb_") or c.startswith("tcg_emb_")
    ]
    if not d_tcg_cols:
        print("  WARNING: D has no TCG embedding columns, cannot synthesize E/F")
        return
    d = pq.read_table(d_path, columns=["record_id", *d_tcg_cols]).to_pandas()
    d = d.drop_duplicates("record_id", keep="first").set_index("record_id")

    def write_joined(source_path: Path, output_path: Path, label: str):
        source_pf = pq.ParquetFile(source_path)
        writer = None
        rows = 0
        for idx in range(source_pf.metadata.num_row_groups):
            chunk = source_pf.read_row_group(idx).to_pandas()
            joined = chunk.join(d, on="record_id")
            fill_cols = [c for c in d_tcg_cols if c in joined.columns]
            emb_value_cols = [c for c in fill_cols if c != "tcg_emb_missing"]
            unmatched = joined[emb_value_cols[0]].isna() if emb_value_cols else pd.Series(False, index=joined.index)
            if "tcg_emb_missing" in joined.columns:
                joined["tcg_emb_missing"] = joined["tcg_emb_missing"].fillna(1).astype("int8")
            else:
                joined["tcg_emb_missing"] = unmatched.astype("int8")
            joined[fill_cols] = joined[fill_cols].fillna(0)
            table = pa.Table.from_pandas(joined, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(str(output_path), table.schema)
            writer.write_table(table)
            rows += len(joined)
            if (idx + 1) % 10 == 0:
                print(f"    {label} row group {idx + 1}: {rows} rows", flush=True)
        if writer is not None:
            writer.close()
        print(f"  Synthesized {label}: {rows} rows, {output_path.stat().st_size / 1024 / 1024:.1f} MB")

    if not e_path.exists():
        if a_path.exists():
            print("  Synthesizing E from A + D...")
            write_joined(a_path, e_path, "E")
        else:
            print("  WARNING: A not found, cannot synthesize E")

    if not f_path.exists():
        if c_path.exists():
            print("  Synthesizing F from C + D...")
            write_joined(c_path, f_path, "F")
        else:
            print("  WARNING: C not found, cannot synthesize F")


def main():
    parser = argparse.ArgumentParser(description="Download classification datasets from Hub")
    parser.add_argument("--hub", choices=["huggingface", "modelscope"], default="modelscope")
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--dataset-dir", default=None, help="Default: auto-detect based on repo")
    parser.add_argument("--skip-synthesis", action="store_true")
    args = parser.parse_args()

    # Auto-detect dataset type from repo-id
    is_tcg = "Graph" in args.repo_id or "TCG" in args.repo_id or "tcg" in args.repo_id

    if args.dataset_dir:
        dataset_dir = Path(args.dataset_dir)
    elif is_tcg:
        dataset_dir = Path("data/features/tcg/classification/datasets")
    else:
        dataset_dir = Path("data/features/hcg/classification/datasets")

    files = TCG_FILES if is_tcg else HCG_FILES

    print(f"Hub: {args.hub}")
    print(f"Repository: {args.repo_id}")
    print(f"Dataset type: {'TCG' if is_tcg else 'HCG'}")
    print(f"Dataset dir: {dataset_dir}")
    print()

    if args.hub == "huggingface":
        download_from_huggingface(dataset_dir, args.repo_id, files)
    else:
        download_from_modelscope(dataset_dir, args.repo_id, files)

    if not args.skip_synthesis:
        if is_tcg:
            print("\nSynthesizing E and F...")
            synthesize_ef(dataset_dir)
        else:
            print("\nSynthesizing C...")
            synthesize_dataset_c(dataset_dir)

    print("\nDownload complete!")
    print(f"Datasets saved to: {dataset_dir}")
    for f in sorted(dataset_dir.glob("*.parquet")):
        print(f"  - {f.name} ({f.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
