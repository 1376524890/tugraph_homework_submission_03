#!/usr/bin/env python3
"""Build A/B/C HCG classification feature datasets."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from tugraph_homework.common import ROOT
from tugraph_homework.transform import (
    COMMON_SERVICE_PORTS,
    PROXY_PORTS,
    normalized_endpoints,
    parse_timestamp,
    port_bucket,
    stable_record_id,
)


TARGET_COLUMNS = {
    "label": "Label",
    "protocol_name": "ProtocolName",
    "l7_protocol": "L7Protocol",
}
LEAKAGE_COLUMNS = {
    "Flow.ID",
    "record_id",
    "src_endpoint",
    "dst_endpoint",
    "Source.IP",
    "Destination.IP",
    "Timestamp",
    "Label",
    "L7Protocol",
    "ProtocolName",
}
PORT_BUCKET_CODES = {"invalid": 0, "well_known": 1, "registered": 2, "dynamic": 3}
COMMON_META_COLUMNS = ["record_id", "target", "split", "src_endpoint", "dst_endpoint"]
DEFAULT_CHUNK_SIZE = 100_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build reproducible HCG classification feature datasets.")
    parser.add_argument("--raw-csv", type=Path, default=ROOT / "data/raw/Dataset-Unicauca-Version2-87Atts.csv")
    parser.add_argument("--embedding", type=Path, default=ROOT / "data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/features/hcg/classification/datasets")
    parser.add_argument("--report", type=Path, default=ROOT / "data/features/hcg/classification/reports/hcg_classification_feature_build_report.md")
    parser.add_argument("--json-report", type=Path, default=ROOT / "data/features/hcg/classification/reports/hcg_classification_feature_build_report.json")
    parser.add_argument("--target", choices=sorted(TARGET_COLUMNS), default="protocol_name")
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260525)
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--valid-size", type=float, default=0.1)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def raw_feature_name(column: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in column).strip("_")
    while "__" in safe:
        safe = safe.replace("__", "_")
    return f"raw_{safe}"


def split_for(record_id: str, target: str, seed: int, valid_size: float, test_size: float) -> str:
    payload = f"{seed}|{target}|{record_id}".encode("utf-8")
    value = int.from_bytes(hashlib.sha1(payload).digest()[:8], "big") / float(2**64)
    if value < test_size:
        return "test"
    if value < test_size + valid_size:
        return "valid"
    return "train"


def numeric_quality(df: pd.DataFrame, feature_cols: list[str]) -> dict[str, int]:
    if not feature_cols:
        return {"nan_count": 0, "inf_count": 0}
    values = df[feature_cols].to_numpy(dtype=np.float32, copy=False)
    return {"nan_count": int(np.isnan(values).sum()), "inf_count": int(np.isinf(values).sum())}


def make_record_ids(start_row_number: int, chunk: pd.DataFrame) -> list[str]:
    if "record_id" in chunk.columns:
        values = chunk["record_id"].fillna("").astype(str)
        return [value if value else f"rec_{idx:010d}" for idx, value in enumerate(values, start=start_row_number)]
    records = chunk.to_dict("records")
    return [stable_record_id(idx, row) for idx, row in enumerate(records, start=start_row_number)]


def make_endpoints(chunk: pd.DataFrame) -> tuple[list[str], list[str], np.ndarray, np.ndarray]:
    src_endpoints: list[str] = []
    dst_endpoints: list[str] = []
    src_ports = np.zeros(len(chunk), dtype=np.int32)
    dst_ports = np.zeros(len(chunk), dtype=np.int32)
    for idx, row in enumerate(chunk.to_dict("records")):
        _, src_port, _, dst_port, src_endpoint, dst_endpoint = normalized_endpoints(row)
        src_endpoints.append(src_endpoint)
        dst_endpoints.append(dst_endpoint)
        src_ports[idx] = src_port
        dst_ports[idx] = dst_port
    return src_endpoints, dst_endpoints, src_ports, dst_ports


def parse_timestamps(values: pd.Series) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    epochs = np.zeros(len(values), dtype=np.float32)
    hours = np.zeros(len(values), dtype=np.float32)
    dayofweeks = np.zeros(len(values), dtype=np.float32)
    failed = 0
    for idx, value in enumerate(values.fillna("").astype(str)):
        _, epoch = parse_timestamp(value)
        if epoch:
            dt = pd.to_datetime(epoch, unit="s", errors="coerce")
            if pd.notna(dt):
                epochs[idx] = float(epoch)
                hours[idx] = float(dt.hour)
                dayofweeks[idx] = float(dt.dayofweek)
            else:
                failed += 1
        else:
            failed += 1
    return epochs, hours, dayofweeks, failed


def build_raw_features(chunk: pd.DataFrame, raw_source_cols: list[str], src_ports: np.ndarray, dst_ports: np.ndarray) -> tuple[pd.DataFrame, dict[str, Any]]:
    features: dict[str, np.ndarray] = {}
    removed: list[str] = []
    for col in raw_source_cols:
        numeric = pd.to_numeric(chunk[col], errors="coerce")
        if numeric.notna().sum() == 0:
            removed.append(col)
            continue
        values = numeric.replace([np.inf, -np.inf], np.nan).fillna(0).astype(np.float32)
        # Chunks keep the source CSV row index; store plain arrays so DataFrame
        # construction cannot align Series by global row labels and introduce NaN.
        features[raw_feature_name(col)] = values.to_numpy(dtype=np.float32, copy=True)

    if "Timestamp" in chunk.columns:
        epoch, hour, dayofweek, timestamp_failed = parse_timestamps(chunk["Timestamp"])
    else:
        epoch = np.zeros(len(chunk), dtype=np.float32)
        hour = np.zeros(len(chunk), dtype=np.float32)
        dayofweek = np.zeros(len(chunk), dtype=np.float32)
        timestamp_failed = len(chunk)

    features["raw_timestamp_epoch"] = epoch
    features["raw_hour"] = hour
    features["raw_dayofweek"] = dayofweek
    features["raw_src_port"] = src_ports.astype(np.float32)
    features["raw_dst_port"] = dst_ports.astype(np.float32)
    features["raw_src_is_common_service_port"] = np.isin(src_ports, list(COMMON_SERVICE_PORTS)).astype(np.float32)
    features["raw_dst_is_common_service_port"] = np.isin(dst_ports, list(COMMON_SERVICE_PORTS)).astype(np.float32)
    features["raw_src_is_proxy_port"] = np.isin(src_ports, list(PROXY_PORTS)).astype(np.float32)
    features["raw_dst_is_proxy_port"] = np.isin(dst_ports, list(PROXY_PORTS)).astype(np.float32)
    features["raw_src_port_bucket_code"] = np.array([PORT_BUCKET_CODES[port_bucket(int(port))] for port in src_ports], dtype=np.float32)
    features["raw_dst_port_bucket_code"] = np.array([PORT_BUCKET_CODES[port_bucket(int(port))] for port in dst_ports], dtype=np.float32)
    return pd.DataFrame(features), {"removed_non_numeric": removed, "timestamp_parse_failed_count": timestamp_failed}


def build_hcg_features(
    src_endpoints: list[str],
    dst_endpoints: list[str],
    embedding_index: pd.Index,
    embedding_values: np.ndarray,
) -> tuple[pd.DataFrame, dict[str, int]]:
    dim = embedding_values.shape[1]
    src_idx = embedding_index.get_indexer(src_endpoints)
    dst_idx = embedding_index.get_indexer(dst_endpoints)
    src_missing = src_idx < 0
    dst_missing = dst_idx < 0
    src = np.zeros((len(src_endpoints), dim), dtype=np.float32)
    dst = np.zeros((len(dst_endpoints), dim), dtype=np.float32)
    if (~src_missing).any():
        src[~src_missing] = embedding_values[src_idx[~src_missing]]
    if (~dst_missing).any():
        dst[~dst_missing] = embedding_values[dst_idx[~dst_missing]]
    diff = np.abs(src - dst)
    prod = src * dst

    data: dict[str, np.ndarray] = {}
    for idx in range(dim):
        data[f"hcg_src_emb_{idx:03d}"] = src[:, idx]
    for idx in range(dim):
        data[f"hcg_dst_emb_{idx:03d}"] = dst[:, idx]
    for idx in range(dim):
        data[f"hcg_absdiff_emb_{idx:03d}"] = diff[:, idx]
    for idx in range(dim):
        data[f"hcg_prod_emb_{idx:03d}"] = prod[:, idx]
    data["hcg_src_emb_missing"] = src_missing.astype(np.float32)
    data["hcg_dst_emb_missing"] = dst_missing.astype(np.float32)
    return pd.DataFrame(data), {
        "src_missing_count": int(src_missing.sum()),
        "dst_missing_count": int(dst_missing.sum()),
        "any_missing_count": int((src_missing | dst_missing).sum()),
    }


def write_table(writer: pq.ParquetWriter | None, path: Path, df: pd.DataFrame) -> pq.ParquetWriter:
    table = pa.Table.from_pandas(df, preserve_index=False)
    if writer is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = pq.ParquetWriter(path, table.schema, compression="snappy")
    writer.write_table(table)
    return writer


def close_writer(writer: pq.ParquetWriter | None) -> None:
    if writer is not None:
        writer.close()


def counts_top(counter: Counter[str], n: int = 20) -> list[dict[str, Any]]:
    return [{"value": key, "count": int(value)} for key, value in counter.most_common(n)]


def write_reports(args: argparse.Namespace, result: dict[str, Any]) -> None:
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with args.report.open("w", encoding="utf-8") as fh:
        fh.write("# HCG Classification Feature Build Report\n\n")
        fh.write(f"Overall status: **{result['overall_status']}**\n\n")
        fh.write("## Inputs\n\n| Item | Path |\n| --- | --- |\n")
        for key, value in result["inputs"].items():
            fh.write(f"| {key} | `{value}` |\n")
        fh.write("\n## Outputs\n\n| Dataset | Path |\n| --- | --- |\n")
        for key, value in result["outputs"].items():
            fh.write(f"| {key} | `{value}` |\n")
        fh.write("\n## Metrics\n\n| Metric | Value |\n| --- | ---: |\n")
        for key, value in result["metrics"].items():
            if isinstance(value, (list, dict)):
                continue
            if isinstance(value, float):
                fh.write(f"| `{key}` | `{value:.6f}` |\n")
            else:
                fh.write(f"| `{key}` | `{value}` |\n")
        fh.write("\n## Target Top 20\n\n| Target | Count |\n| --- | ---: |\n")
        for row in result["target_top20"]:
            fh.write(f"| `{row['value']}` | `{row['count']}` |\n")
        fh.write("\n## Split Distribution\n\n| Split | Count |\n| --- | ---: |\n")
        for split, count in result["split_counts"].items():
            fh.write(f"| `{split}` | `{count}` |\n")
        fh.write("\n## Checks\n\n| Check | Result |\n| --- | --- |\n")
        for key, ok in result["checks"].items():
            fh.write(f"| `{key}` | {'PASS' if ok else 'FAIL'} |\n")
        fh.write("\n## Raw Features\n\n")
        fh.write(", ".join(f"`{col}`" for col in result["raw_features"]) + "\n\n")
        fh.write("## HCG Features\n\n")
        fh.write(f"{len(result['hcg_features'])} columns: `hcg_src_emb_*`, `hcg_dst_emb_*`, `hcg_absdiff_emb_*`, `hcg_prod_emb_*`, and missing flags.\n")
        fh.write("\n## Removed Columns\n\n")
        fh.write(", ".join(f"`{col}`" for col in result["removed_columns"]) or "None")
        fh.write("\n")


def main() -> int:
    args = parse_args()
    for name in ("raw_csv", "embedding", "output_dir", "report", "json_report"):
        setattr(args, name, resolve_path(getattr(args, name)))
    if args.max_rows < 0:
        raise ValueError("--max-rows must be >= 0")
    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be positive")
    if not (0 < args.test_size < 1) or not (0 <= args.valid_size < 1) or args.test_size + args.valid_size >= 1:
        raise ValueError("--test-size and --valid-size must define a positive train split")

    output_paths = {
        "A": args.output_dir / "A_raw_flow_features.parquet",
        "B": args.output_dir / "B_hcg_flow_emb_256.parquet",
        "C": args.output_dir / "C_raw_plus_hcg_flow_emb.parquet",
    }
    existing = [path for path in output_paths.values() if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError("output exists and --overwrite was not set: " + ", ".join(str(path) for path in existing))
    for path in existing:
        path.unlink()

    started = time.perf_counter()
    target_column = TARGET_COLUMNS[args.target]
    raw_header = pd.read_csv(args.raw_csv, nrows=0).columns.tolist()
    if target_column not in raw_header:
        raise ValueError(f"target column not found: {target_column}")
    raw_source_cols = [col for col in raw_header if col not in LEAKAGE_COLUMNS]

    emb = pd.read_parquet(args.embedding)
    emb_cols = [col for col in emb.columns if col.startswith("emb_")]
    emb_cols = sorted(emb_cols)
    if len(emb_cols) != 64:
        raise ValueError(f"expected 64 endpoint embedding columns, got {len(emb_cols)}")
    embedding_index = pd.Index(emb["endpoint_id"].astype(str))
    embedding_values = emb[emb_cols].to_numpy(dtype=np.float32, copy=False)
    del emb

    writer_a = writer_b = writer_c = None
    row_count = 0
    target_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    split_target_counts: dict[str, Counter[str]] = defaultdict(Counter)
    removed_columns: set[str] = set()
    raw_features: list[str] = []
    hcg_features: list[str] = []
    timestamp_failed_total = 0
    src_missing_total = 0
    dst_missing_total = 0
    any_missing_total = 0
    nan_total = 0
    inf_total = 0

    read_kwargs: dict[str, Any] = {"chunksize": args.chunk_size, "low_memory": False}
    if args.max_rows > 0:
        read_kwargs["nrows"] = args.max_rows

    for chunk_idx, chunk in enumerate(pd.read_csv(args.raw_csv, **read_kwargs), start=1):
        chunk = chunk.reset_index(drop=True)
        start_row_number = row_count + 1
        record_ids = make_record_ids(start_row_number, chunk)
        src_endpoints, dst_endpoints, src_ports, dst_ports = make_endpoints(chunk)
        targets = chunk[target_column].fillna("").astype(str)
        splits = [split_for(rid, target, args.seed, args.valid_size, args.test_size) for rid, target in zip(record_ids, targets)]
        meta = pd.DataFrame(
            {
                "record_id": record_ids,
                "target": targets,
                "split": splits,
                "src_endpoint": src_endpoints,
                "dst_endpoint": dst_endpoints,
            }
        )

        raw_df, raw_info = build_raw_features(chunk, raw_source_cols, src_ports, dst_ports)
        hcg_df, hcg_info = build_hcg_features(src_endpoints, dst_endpoints, embedding_index, embedding_values)
        if not raw_features:
            raw_features = raw_df.columns.tolist()
        if not hcg_features:
            hcg_features = hcg_df.columns.tolist()
        removed_columns.update(raw_info["removed_non_numeric"])
        timestamp_failed_total += int(raw_info["timestamp_parse_failed_count"])
        src_missing_total += hcg_info["src_missing_count"]
        dst_missing_total += hcg_info["dst_missing_count"]
        any_missing_total += hcg_info["any_missing_count"]

        a_df = pd.concat([meta, raw_df], axis=1)
        b_df = pd.concat([meta, hcg_df], axis=1)
        c_df = pd.concat([meta, raw_df, hcg_df], axis=1)
        for frame, cols in ((a_df, raw_features), (b_df, hcg_features), (c_df, raw_features + hcg_features)):
            quality = numeric_quality(frame, cols)
            nan_total += quality["nan_count"]
            inf_total += quality["inf_count"]

        writer_a = write_table(writer_a, output_paths["A"], a_df)
        writer_b = write_table(writer_b, output_paths["B"], b_df)
        writer_c = write_table(writer_c, output_paths["C"], c_df)

        row_count += len(chunk)
        target_counts.update(targets)
        split_counts.update(splits)
        for split, target in zip(splits, targets):
            split_target_counts[split][target] += 1
        print(f"processed_chunk={chunk_idx} rows={row_count}", flush=True)

    close_writer(writer_a)
    close_writer(writer_b)
    close_writer(writer_c)

    metrics = {
        "raw_read_rows": row_count,
        "output_rows": row_count,
        "max_rows": args.max_rows,
        "target": args.target,
        "target_class_count": len(target_counts),
        "embedding_endpoint_count": len(embedding_index),
        "src_embedding_missing_count": src_missing_total,
        "src_embedding_missing_ratio": src_missing_total / row_count if row_count else 0.0,
        "dst_embedding_missing_count": dst_missing_total,
        "dst_embedding_missing_ratio": dst_missing_total / row_count if row_count else 0.0,
        "any_embedding_missing_count": any_missing_total,
        "any_embedding_missing_ratio": any_missing_total / row_count if row_count else 0.0,
        "A_raw_feature_count": len(raw_features),
        "B_hcg_feature_count": len(hcg_features),
        "C_feature_count": len(raw_features) + len(hcg_features),
        "timestamp_parse_failed_count": timestamp_failed_total,
        "nan_count": nan_total,
        "inf_count": inf_total,
        "build_elapsed_seconds": time.perf_counter() - started,
        "split_method": "deterministic_target_record_hash",
    }
    checks = {
        "A_file_exists": output_paths["A"].exists(),
        "B_file_exists": output_paths["B"].exists(),
        "C_file_exists": output_paths["C"].exists(),
        "rows_non_empty": row_count > 0,
        "raw_features_non_empty": len(raw_features) > 0,
        "hcg_feature_count_is_258": len(hcg_features) == 258,
        "hcg_embedding_feature_count_is_256": len([c for c in hcg_features if c.startswith("hcg_") and c.endswith(tuple(f"{i:03d}" for i in range(64)))]) >= 256,
        "C_feature_count_matches": metrics["C_feature_count"] == metrics["A_raw_feature_count"] + metrics["B_hcg_feature_count"],
        "no_nan": nan_total == 0,
        "no_inf": inf_total == 0,
        "target_non_empty": "" not in target_counts,
        "split_non_empty": all(split_counts.get(split, 0) > 0 for split in ("train", "valid", "test")),
    }
    result = {
        "inputs": {"raw_csv": str(args.raw_csv), "embedding": str(args.embedding)},
        "outputs": {key: str(value) for key, value in output_paths.items()},
        "parameters": {
            "target": args.target,
            "max_rows": args.max_rows,
            "seed": args.seed,
            "test_size": args.test_size,
            "valid_size": args.valid_size,
            "chunk_size": args.chunk_size,
        },
        "metrics": metrics,
        "target_top20": counts_top(target_counts),
        "split_counts": dict(split_counts),
        "split_target_top20": {split: counts_top(counter) for split, counter in split_target_counts.items()},
        "raw_features": raw_features,
        "hcg_features": hcg_features,
        "removed_columns": sorted(removed_columns),
        "checks": checks,
        "overall_status": "PASS" if all(checks.values()) else "FAIL",
    }
    write_reports(args, result)
    print(json.dumps({"metrics": metrics, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
