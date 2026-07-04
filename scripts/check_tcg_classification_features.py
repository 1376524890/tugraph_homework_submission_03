#!/usr/bin/env python3
"""Check TCG classification datasets D, E, F for correctness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from tugraph_homework.common import ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check TCG classification datasets.")
    parser.add_argument("--a-path", type=Path, default=ROOT / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet")
    parser.add_argument("--c-path", type=Path, default=ROOT / "data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json-report", type=Path, required=True)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def check_dataset(name: str, path: Path, a_meta: dict, c_meta: dict, a_feature_cols: list[str], c_feature_cols: list[str]) -> dict:
    if not path.exists():
        return {"exists": False, "status": "FAIL", "error": f"{path} does not exist"}

    pf = pq.ParquetFile(path)
    schema = pf.schema_arrow
    cols = [schema.field(i).name for i in range(len(schema))]
    rows = pf.metadata.num_rows

    # Read meta columns
    table = pq.read_table(path, columns=["record_id", "target", "split"])
    rids = table.column("record_id").to_pylist()
    targets = table.column("target").to_pylist()
    splits = table.column("split").to_pylist()

    # Identify feature columns
    meta_cols = {"record_id", "target", "split", "src_endpoint", "dst_endpoint"}
    feature_cols = [c for c in cols if c not in meta_cols]
    tcg_emb_cols = [
        c for c in cols
        if (c.startswith("tcg_emb_") and c != "tcg_emb_missing") or c.startswith("emb_")
    ]
    has_missing_flag = "tcg_emb_missing" in cols

    checks = {
        "exists": True,
        "rows_equal_A": rows == a_meta["rows"],
        "record_id_unique": len(set(rids)) == len(rids),
        "record_id_order_matches_A": rids == a_meta["record_ids"],
        "target_matches_A": targets == a_meta["targets"],
        "split_matches_A": splits == a_meta["splits"],
        "tcg_emb_col_count_64": len(tcg_emb_cols) == 64,
        "has_tcg_emb_missing_flag": has_missing_flag,
    }
    if name == "E":
        checks["contains_all_A_feature_columns"] = set(a_feature_cols).issubset(cols)
    if name == "F":
        checks.update(
            {
                "rows_equal_C": rows == c_meta["rows"],
                "record_id_order_matches_C": rids == c_meta["record_ids"],
                "target_matches_C": targets == c_meta["targets"],
                "split_matches_C": splits == c_meta["splits"],
                "contains_all_C_feature_columns": set(c_feature_cols).issubset(cols),
            }
        )

    # Check NaN/Inf on numeric columns (sample first row group for efficiency)
    batch = pf.read_row_group(0)
    numeric_arrays = [
        batch.column(i)
        for i in range(batch.num_columns)
        if pa.types.is_floating(schema.field(i).type)
    ]
    has_nan = any(any(np.isnan(arr.to_pylist()[:10000])) for arr in numeric_arrays if len(arr) > 0)
    has_inf = any(any(np.isinf(arr.to_pylist()[:10000])) for arr in numeric_arrays if len(arr) > 0)
    checks["no_nan"] = not has_nan
    checks["no_inf"] = not has_inf

    status = "PASS" if all(v for k, v in checks.items() if k != "exists") else "FAIL"

    return {
        "path": str(path),
        "rows": rows,
        "columns": len(cols),
        "feature_columns": len(feature_cols),
        "tcg_emb_columns": len(tcg_emb_cols),
        "has_tcg_emb_missing_flag": has_missing_flag,
        "checks": checks,
        "status": status,
    }


def main() -> int:
    args = parse_args()
    args.a_path = resolve_path(args.a_path)
    args.c_path = resolve_path(args.c_path)
    args.dataset_dir = resolve_path(args.dataset_dir)
    args.report = resolve_path(args.report)
    args.json_report = resolve_path(args.json_report)

    # Load A meta for comparison
    a_table = pq.read_table(args.a_path, columns=["record_id", "target", "split"])
    a_meta = {
        "rows": a_table.num_rows,
        "record_ids": a_table.column("record_id").to_pylist(),
        "targets": a_table.column("target").to_pylist(),
        "splits": a_table.column("split").to_pylist(),
    }
    c_table = pq.read_table(args.c_path, columns=["record_id", "target", "split"])
    c_meta = {
        "rows": c_table.num_rows,
        "record_ids": c_table.column("record_id").to_pylist(),
        "targets": c_table.column("target").to_pylist(),
        "splits": c_table.column("split").to_pylist(),
    }
    meta_cols = {"record_id", "target", "split", "src_endpoint", "dst_endpoint"}
    a_cols = pq.ParquetFile(args.a_path).schema_arrow.names
    c_cols = pq.ParquetFile(args.c_path).schema_arrow.names
    a_feature_cols = [col for col in a_cols if col not in meta_cols]
    c_feature_cols = [col for col in c_cols if col not in meta_cols]

    datasets = {
        "D": args.dataset_dir / "D_tcg_flow_node2vec_d128_light_shrcr.parquet",
        "E": args.dataset_dir / "E_raw_plus_tcg_d128_light_shrcr.parquet",
        "F": args.dataset_dir / "F_raw_plus_hcg_plus_tcg_d128_light_shrcr.parquet",
    }

    results = {}
    for name, path in datasets.items():
        print(f"Checking {name}: {path}", flush=True)
        results[name] = check_dataset(name, path, a_meta, c_meta, a_feature_cols, c_feature_cols)

    all_pass = all(r.get("status") == "PASS" for r in results.values())
    overall_status = "PASS" if all_pass else "FAIL"

    report = {
        "overall_status": overall_status,
        "datasets": results,
    }

    # Write reports
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as fh:
        fh.write("# TCG Classification Dataset Check Report\n\n")
        fh.write(f"Overall status: **{overall_status}**\n\n")
        for name, r in results.items():
            fh.write(f"## {name}\n\n")
            fh.write(f"- Path: `{r.get('path', 'N/A')}`\n")
            fh.write(f"- Status: **{r.get('status', 'N/A')}**\n")
            if "rows" in r:
                fh.write(f"- Rows: {r['rows']}\n")
                fh.write(f"- Columns: {r['columns']}\n")
                fh.write(f"- Feature columns: {r['feature_columns']}\n")
                fh.write(f"- TCG emb columns: {r['tcg_emb_columns']}\n")
            if "checks" in r:
                fh.write("\n| Check | Result |\n| --- | --- |\n")
                for k, v in r["checks"].items():
                    fh.write(f"| `{k}` | {'PASS' if v else 'FAIL'} |\n")
            fh.write("\n")

    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps({"status": overall_status, "results": {k: v.get("status") for k, v in results.items()}}, indent=2))
    return 0 if overall_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
