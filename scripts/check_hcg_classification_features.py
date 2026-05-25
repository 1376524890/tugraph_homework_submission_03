#!/usr/bin/env python3
"""Check A/B/C HCG classification feature datasets."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from tugraph_homework.common import ROOT


DATASET_FILES = {
    "A": "A_raw_flow_features.parquet",
    "B": "B_hcg_flow_emb_256.parquet",
    "C": "C_raw_plus_hcg_flow_emb.parquet",
}
META_COLUMNS = {"record_id", "target", "split", "src_endpoint", "dst_endpoint"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check HCG classification feature datasets.")
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "data/features/hcg/classification/datasets")
    parser.add_argument("--report", type=Path, default=ROOT / "data/features/hcg/classification/reports/hcg_classification_feature_check_report.md")
    parser.add_argument("--json-report", type=Path, default=ROOT / "data/features/hcg/classification/reports/hcg_classification_feature_check_report.json")
    parser.add_argument("--expected-hcg-dim", type=int, default=256)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def feature_columns(df: pd.DataFrame, prefix: str) -> list[str]:
    return [col for col in df.columns if col.startswith(prefix)]


def hcg_embedding_columns(df: pd.DataFrame) -> list[str]:
    pattern = re.compile(r"^hcg_(src|dst|absdiff|prod)_emb_\d{3}$")
    return [col for col in df.columns if pattern.match(col)]


def numeric_quality(df: pd.DataFrame, columns: list[str]) -> dict[str, int]:
    if not columns:
        return {"nan_count": 0, "inf_count": 0}
    values = df[columns].to_numpy(dtype=np.float32, copy=False)
    return {"nan_count": int(np.isnan(values).sum()), "inf_count": int(np.isinf(values).sum())}


def top_counts(values: pd.Series, n: int = 20) -> list[dict[str, Any]]:
    counter = Counter(values.fillna("").astype(str))
    return [{"value": key, "count": int(value)} for key, value in counter.most_common(n)]


def top_counts_counter(counter: Counter[str], n: int = 20) -> list[dict[str, Any]]:
    return [{"value": key, "count": int(value)} for key, value in counter.most_common(n)]


def parquet_columns(path: Path) -> list[str]:
    return pq.ParquetFile(path).schema_arrow.names


def column_batches(path: Path, columns: list[str], batch_size: int = 100_000):
    yield from pq.ParquetFile(path).iter_batches(batch_size=batch_size, columns=columns)


def count_numeric_quality(path: Path, columns: list[str]) -> dict[str, int]:
    nan_count = 0
    inf_count = 0
    if not columns:
        return {"nan_count": 0, "inf_count": 0}
    for batch in column_batches(path, columns):
        df = batch.to_pandas()
        values = df[columns].to_numpy(dtype=np.float32, copy=False)
        nan_count += int(np.isnan(values).sum())
        inf_count += int(np.isinf(values).sum())
    return {"nan_count": nan_count, "inf_count": inf_count}


def scan_meta(path: Path) -> dict[str, Any]:
    record_ids: set[str] = set()
    duplicate_count = 0
    target_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    target_empty_count = 0
    split_empty_count = 0
    row_count = 0
    for batch in column_batches(path, ["record_id", "target", "split"]):
        df = batch.to_pandas()
        records = df["record_id"].fillna("").astype(str)
        targets = df["target"].fillna("").astype(str)
        splits = df["split"].fillna("").astype(str)
        row_count += len(df)
        target_counts.update(targets)
        split_counts.update(splits)
        target_empty_count += int((targets.str.len() == 0).sum())
        split_empty_count += int((splits.str.len() == 0).sum())
        for record_id in records:
            if record_id in record_ids:
                duplicate_count += 1
            else:
                record_ids.add(record_id)
    return {
        "row_count": row_count,
        "record_id_unique": duplicate_count == 0 and len(record_ids) == row_count,
        "target_counts": target_counts,
        "split_counts": split_counts,
        "target_empty_count": target_empty_count,
        "split_empty_count": split_empty_count,
    }


def compare_columns(path_left: Path, path_right: Path, columns: list[str]) -> bool:
    left_iter = column_batches(path_left, columns)
    right_iter = column_batches(path_right, columns)
    for left_batch, right_batch in zip(left_iter, right_iter, strict=True):
        left = left_batch.to_pandas()
        right = right_batch.to_pandas()
        for col in columns:
            if not left[col].equals(right[col]):
                return False
    return True


def write_reports(args: argparse.Namespace, result: dict[str, Any]) -> None:
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with args.report.open("w", encoding="utf-8") as fh:
        fh.write("# HCG Classification Feature Check Report\n\n")
        fh.write(f"Overall status: **{result['overall_status']}**\n\n")
        fh.write("## Inputs\n\n| Dataset | Path |\n| --- | --- |\n")
        for key, value in result["inputs"].items():
            fh.write(f"| {key} | `{value}` |\n")
        fh.write("\n## Metrics\n\n| Metric | Value |\n| --- | ---: |\n")
        for key, value in result["metrics"].items():
            if isinstance(value, (list, dict)):
                continue
            if isinstance(value, float):
                fh.write(f"| `{key}` | `{value:.6f}` |\n")
            else:
                fh.write(f"| `{key}` | `{value}` |\n")
        fh.write("\n## Split Counts\n\n| Split | Count | Ratio |\n| --- | ---: | ---: |\n")
        total = result["metrics"].get("row_count_A", 0) or 1
        for split, count in result["split_counts"].items():
            fh.write(f"| `{split}` | `{count}` | `{count / total:.6f}` |\n")
        fh.write("\n## Target Top 20\n\n| Target | Count |\n| --- | ---: |\n")
        for row in result["target_top20"]:
            fh.write(f"| `{row['value']}` | `{row['count']}` |\n")
        fh.write("\n## Checks\n\n| Check | Result |\n| --- | --- |\n")
        for key, ok in result["checks"].items():
            fh.write(f"| `{key}` | {'PASS' if ok else 'FAIL'} |\n")


def main() -> int:
    args = parse_args()
    for name in ("dataset_dir", "report", "json_report"):
        setattr(args, name, resolve_path(getattr(args, name)))
    if args.expected_hcg_dim <= 0:
        raise ValueError("--expected-hcg-dim must be positive")

    started = time.perf_counter()
    paths = {key: args.dataset_dir / filename for key, filename in DATASET_FILES.items()}
    exists = {key: path.exists() for key, path in paths.items()}
    checks: dict[str, bool] = {f"{key}_file_exists": ok for key, ok in exists.items()}
    if not all(exists.values()):
        result = {
            "inputs": {key: str(value) for key, value in paths.items()},
            "metrics": {"check_elapsed_seconds": time.perf_counter() - started},
            "split_counts": {},
            "target_top20": [],
            "checks": checks,
            "overall_status": "FAIL",
        }
        write_reports(args, result)
        return 1

    cols_a = parquet_columns(paths["A"])
    cols_b = parquet_columns(paths["B"])
    cols_c = parquet_columns(paths["C"])
    raw_a = [col for col in cols_a if col.startswith("raw_")]
    raw_c = [col for col in cols_c if col.startswith("raw_")]
    hcg_b = [col for col in cols_b if col.startswith("hcg_")]
    hcg_c = [col for col in cols_c if col.startswith("hcg_")]
    hcg_emb_b = [col for col in cols_b if re.match(r"^hcg_(src|dst|absdiff|prod)_emb_\d{3}$", col)]
    hcg_emb_c = [col for col in cols_c if re.match(r"^hcg_(src|dst|absdiff|prod)_emb_\d{3}$", col)]
    quality_a = count_numeric_quality(paths["A"], raw_a)
    quality_b = count_numeric_quality(paths["B"], hcg_b)
    quality_c = count_numeric_quality(paths["C"], raw_c + hcg_c)
    nan_count = quality_a["nan_count"] + quality_b["nan_count"] + quality_c["nan_count"]
    inf_count = quality_a["inf_count"] + quality_b["inf_count"] + quality_c["inf_count"]

    meta_a = scan_meta(paths["A"])
    meta_b = scan_meta(paths["B"])
    meta_c = scan_meta(paths["C"])
    row_count_a = meta_a["row_count"]
    row_count_b = meta_b["row_count"]
    row_count_c = meta_c["row_count"]
    record_id_match_ab = compare_columns(paths["A"], paths["B"], ["record_id"])
    record_id_match_ac = compare_columns(paths["A"], paths["C"], ["record_id"])
    target_match_ab = compare_columns(paths["A"], paths["B"], ["target"])
    target_match_ac = compare_columns(paths["A"], paths["C"], ["target"])
    split_match_ab = compare_columns(paths["A"], paths["B"], ["split"])
    split_match_ac = compare_columns(paths["A"], paths["C"], ["split"])
    split_counts = meta_a["split_counts"]

    metrics: dict[str, Any] = {
        "row_count_A": int(row_count_a),
        "row_count_B": int(row_count_b),
        "row_count_C": int(row_count_c),
        "raw_feature_count_A": len(raw_a),
        "raw_feature_count_C": len(raw_c),
        "hcg_feature_count_B": len(hcg_b),
        "hcg_feature_count_C": len(hcg_c),
        "hcg_embedding_feature_count_B": len(hcg_emb_b),
        "hcg_embedding_feature_count_C": len(hcg_emb_c),
        "nan_count": nan_count,
        "inf_count": inf_count,
        "target_class_count": len(meta_a["target_counts"]),
        "train_ratio": split_counts.get("train", 0) / row_count_a if row_count_a else 0.0,
        "valid_ratio": split_counts.get("valid", 0) / row_count_a if row_count_a else 0.0,
        "test_ratio": split_counts.get("test", 0) / row_count_a if row_count_a else 0.0,
        "check_elapsed_seconds": time.perf_counter() - started,
    }

    checks.update(
        {
            "row_counts_match": row_count_a == row_count_b == row_count_c and row_count_a > 0,
            "record_id_unique_A": bool(meta_a["record_id_unique"]),
            "record_id_unique_B": bool(meta_b["record_id_unique"]),
            "record_id_unique_C": bool(meta_c["record_id_unique"]),
            "record_id_order_match": record_id_match_ab and record_id_match_ac,
            "target_match": target_match_ab and target_match_ac,
            "split_match": split_match_ab and split_match_ac,
            "A_has_raw_features": len(raw_a) >= 1,
            "B_has_expected_hcg_embedding_dim": len(hcg_emb_b) == args.expected_hcg_dim,
            "B_has_missing_flags": {"hcg_src_emb_missing", "hcg_dst_emb_missing"}.issubset(cols_b),
            "C_has_raw_and_hcg": len(raw_c) >= 1 and len(hcg_c) >= args.expected_hcg_dim,
            "C_raw_feature_count_matches_A": len(raw_c) == len(raw_a),
            "C_hcg_feature_count_matches_B": len(hcg_c) == len(hcg_b),
            "no_nan": nan_count == 0,
            "no_inf": inf_count == 0,
            "target_non_empty": meta_a["target_empty_count"] == 0,
            "split_non_empty": meta_a["split_empty_count"] == 0,
            "split_contains_train_valid_test": all(split_counts.get(split, 0) > 0 for split in ("train", "valid", "test")),
            "split_ratio_close_to_expected": (
                abs(metrics["train_ratio"] - 0.7) <= 0.05
                and abs(metrics["valid_ratio"] - 0.1) <= 0.05
                and abs(metrics["test_ratio"] - 0.2) <= 0.05
            ),
        }
    )
    result = {
        "inputs": {key: str(value) for key, value in paths.items()},
        "parameters": {"expected_hcg_dim": args.expected_hcg_dim},
        "metrics": metrics,
        "split_counts": dict(split_counts),
        "target_top20": top_counts_counter(meta_a["target_counts"]),
        "checks": checks,
        "overall_status": "PASS" if all(checks.values()) else "FAIL",
    }
    write_reports(args, result)
    print(json.dumps({"metrics": metrics, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
