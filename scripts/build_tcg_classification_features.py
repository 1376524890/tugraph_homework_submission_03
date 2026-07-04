#!/usr/bin/env python3
"""Build TCG classification feature datasets D, E, F.

Memory-optimized: writes one row group at a time using pyarrow ParquetWriter.
"""

from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from tugraph_homework.common import ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build TCG classification datasets D, E, F.")
    parser.add_argument("--a-path", type=Path, default=ROOT / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet")
    parser.add_argument("--c-path", type=Path, default=ROOT / "data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet")
    parser.add_argument("--tcg-emb-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json-report", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def load_tcg_emb(tcg_emb_path: Path):
    pf = pq.ParquetFile(tcg_emb_path)
    schema = pf.schema_arrow
    all_cols = [schema.field(i).name for i in range(len(schema))]
    emb_cols = sorted([c for c in all_cols if c.startswith("emb_")])
    table = pq.read_table(tcg_emb_path, columns=["record_id"] + emb_cols)
    rids = table.column("record_id").to_pylist()
    rid_to_idx = {r: i for i, r in enumerate(rids)}
    mat = np.zeros((len(rids), len(emb_cols)), dtype=np.float32)
    for j, col in enumerate(emb_cols):
        mat[:, j] = table.column(col).to_numpy()
    del table; gc.collect()
    return rid_to_idx, mat, emb_cols


def add_tcg_emb(df: pd.DataFrame, rid_to_idx: dict, mat: np.ndarray, emb_cols: list[str]) -> int:
    n, nd = len(df), len(emb_cols)
    result = np.zeros((n, nd), dtype=np.float32)
    missing = np.ones(n, dtype=np.int8)
    rids = df["record_id"].values
    for i in range(n):
        idx = rid_to_idx.get(rids[i])
        if idx is not None:
            result[i] = mat[idx]
            missing[i] = 0
    for j in range(nd):
        df[emb_cols[j]] = result[:, j]
    df["tcg_emb_missing"] = missing
    return int(missing.sum())


def write_dataset_incremental(
    source_pf: pq.ParquetFile,
    columns: list[str] | None,
    rid_to_idx: dict,
    mat: np.ndarray,
    emb_cols: list[str],
    output_path: Path,
) -> tuple[int, int]:
    """Write a dataset row-group by row-group to avoid OOM."""
    total_rows = 0
    total_missing = 0
    writer = None

    for i in range(source_pf.metadata.num_row_groups):
        df = source_pf.read_row_group(i, columns=columns).to_pandas()
        miss = add_tcg_emb(df, rid_to_idx, mat, emb_cols)
        total_missing += miss
        total_rows += len(df)

        table = pa.Table.from_pandas(df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(str(output_path), table.schema)
        writer.write_table(table)
        del df, table
        gc.collect()

        if (i + 1) % 10 == 0:
            print(f"    rg {i}: {total_rows} rows, missing={total_missing}", flush=True)

    if writer:
        writer.close()
    return total_rows, total_missing


def main() -> int:
    args = parse_args()
    for name in ("a_path", "c_path", "tcg_emb_path", "output_dir", "report", "json_report"):
        v = getattr(args, name)
        if v is not None:
            setattr(args, name, resolve_path(v))

    start = time.perf_counter()

    rid_to_idx, emb_mat, emb_cols = load_tcg_emb(args.tcg_emb_path)
    if not emb_cols:
        print("ERROR: No emb_* columns", flush=True)
        return 1
    print(f"TCG emb: {len(rid_to_idx)} records, {len(emb_cols)} dims", flush=True)

    a_pf = pq.ParquetFile(args.a_path)
    n_a = a_pf.metadata.num_rows
    a_schema = [a_pf.schema_arrow.field(i).name for i in range(len(a_pf.schema_arrow))]
    a_meta = ["record_id", "target", "split", "src_endpoint", "dst_endpoint"]
    a_feats = [c for c in a_schema if c not in a_meta]

    c_pf = pq.ParquetFile(args.c_path)
    c_schema = [c_pf.schema_arrow.field(i).name for i in range(len(c_pf.schema_arrow))]
    c_feats = [c for c in c_schema if c not in a_meta]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    d_path = args.output_dir / "D_tcg_flow_node2vec_d128_light_shrcr.parquet"
    e_path = args.output_dir / "E_raw_plus_tcg_d128_light_shrcr.parquet"
    f_path = args.output_dir / "F_raw_plus_hcg_plus_tcg_d128_light_shrcr.parquet"

    if args.dry_run:
        print(f"DRY RUN: D(meta+emb), E(A+emb), F(C+emb)", flush=True)
        return 0

    # D
    print("Building D...", flush=True)
    d_rows, d_miss = write_dataset_incremental(a_pf, a_meta, rid_to_idx, emb_mat, emb_cols, d_path)
    gc.collect()
    print(f"D: {d_rows} rows, missing={d_miss}", flush=True)

    # E
    print("Building E...", flush=True)
    e_rows, e_miss = write_dataset_incremental(a_pf, None, rid_to_idx, emb_mat, emb_cols, e_path)
    gc.collect()
    print(f"E: {e_rows} rows, missing={e_miss}", flush=True)

    # F
    print("Building F...", flush=True)
    f_rows, f_miss = write_dataset_incremental(c_pf, None, rid_to_idx, emb_mat, emb_cols, f_path)
    del rid_to_idx, emb_mat; gc.collect()
    print(f"F: {f_rows} rows, missing={f_miss}", flush=True)

    checks = {
        "D_rows_equal_A": d_rows == n_a,
        "E_rows_equal_A": e_rows == n_a,
        "F_rows_equal_A": f_rows == n_a,
        "tcg_emb_col_count_64": len(emb_cols) == 64,
    }
    status = "PASS" if all(checks.values()) else "FAIL"
    elapsed = time.perf_counter() - start

    result = {
        "stats": {
            "A_rows": n_a, "tcg_emb_dims": len(emb_cols),
            "D_rows": d_rows, "E_rows": e_rows, "F_rows": f_rows,
            "D_missing": d_miss, "E_missing": e_miss, "F_missing": f_miss,
            "D_missing_pct": round(d_miss / n_a * 100, 2),
            "elapsed_seconds": round(elapsed, 2),
        },
        "checks": checks, "overall_status": status,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w") as fh:
        fh.write("# TCG Classification Feature Build Report\n\n")
        fh.write(f"Status: **{status}**\n\n| Metric | Value |\n|---|---:|\n")
        for k, v in result["stats"].items():
            fh.write(f"| `{k}` | `{v}` |\n")
        fh.write("\n| Check | Result |\n|---|---|\n")
        for k, ok in checks.items():
            fh.write(f"| `{k}` | {'PASS' if ok else 'FAIL'} |\n")

    args.json_report.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
