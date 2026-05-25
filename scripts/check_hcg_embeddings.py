#!/usr/bin/env python3
"""Validate exported HCG Endpoint embedding parquet files."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tugraph_homework.common import ROOT, progress_iter


DEFAULT_EMBEDDINGS = ROOT / "data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet"
DEFAULT_ID_MAP = ROOT / "docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv"
DEFAULT_REPORT = ROOT / "data/features/hcg/reports/hcg_endpoint_node2vec_d64_check.md"
DEFAULT_JSON_REPORT = ROOT / "data/features/hcg/reports/hcg_endpoint_node2vec_d64_check.json"
LOGGER = logging.getLogger("hcg_embedding_check")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check HCG Endpoint embedding parquet output.")
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--id-map", type=Path, default=DEFAULT_ID_MAP)
    parser.add_argument("--walks", type=Path, default=None)
    parser.add_argument("--expected-dim", type=int, default=64)
    parser.add_argument("--expected-min-rows", type=int, default=1)
    parser.add_argument("--expected-rows", type=int, default=0, help="0 means do not enforce exact row count.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json-report", type=Path, default=DEFAULT_JSON_REPORT)
    parser.add_argument("--log-file", type=Path, default=None, help="Default: report path with .log suffix.")
    return parser.parse_args()


def resolve_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else ROOT / path


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)


def read_id_map_tokens(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"id map file not found: {path}")
    LOGGER.info("reading id map: %s", path)
    tokens: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != ["vid", "token"]:
            raise ValueError(f"id map header must be vid,token, got: {reader.fieldnames}")
        for row_number, row in enumerate(reader, start=2):
            token = (row.get("token") or "").strip()
            if not token:
                raise ValueError(f"id map has empty token at line {row_number}")
            if token in tokens:
                raise ValueError(f"id map has duplicate token at line {row_number}: {token}")
            tokens.add(token)
    LOGGER.info("id map loaded: %d tokens", len(tokens))
    return tokens


def read_walk_tokens(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"walks file not found: {path}")
    LOGGER.info("scanning walks tokens: %s", path)
    tokens: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for raw_line in progress_iter(fh, "Scan walks", "lines"):
            tokens.update(raw_line.strip().split())
    LOGGER.info("walk scan finished: %d unique tokens", len(tokens))
    return tokens


def write_reports(args: argparse.Namespace, metrics: dict[str, Any], checks: dict[str, bool]) -> None:
    result = {
        "inputs": {
            "embeddings": str(args.embeddings),
            "id_map": str(args.id_map) if args.id_map else None,
            "walks": str(args.walks) if args.walks else None,
        },
        "outputs": {"report": str(args.report), "json_report": str(args.json_report), "log_file": str(args.log_file)},
        "parameters": {
            "expected_dim": args.expected_dim,
            "expected_min_rows": args.expected_min_rows,
            "expected_rows": args.expected_rows,
        },
        "metrics": metrics,
        "checks": checks,
        "overall_status": "PASS" if all(checks.values()) else "FAIL",
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as fh:
        fh.write("# HCG Endpoint Embedding Check\n\n")
        fh.write(f"Overall status: **{result['overall_status']}**\n\n")
        fh.write("## Inputs\n\n")
        fh.write("| Item | Path |\n| --- | --- |\n")
        fh.write(f"| embeddings | `{args.embeddings}` |\n")
        fh.write(f"| id map | `{args.id_map}` |\n")
        fh.write(f"| walks | `{args.walks}` |\n")
        fh.write(f"| log file | `{args.log_file}` |\n\n")

        fh.write("## Metrics\n\n")
        fh.write("| Metric | Value |\n| --- | ---: |\n")
        for key, value in metrics.items():
            if isinstance(value, float):
                fh.write(f"| `{key}` | `{value:.6f}` |\n")
            else:
                fh.write(f"| `{key}` | `{value}` |\n")
        fh.write("\n## Checks\n\n")
        fh.write("| Check | Result |\n| --- | --- |\n")
        for key, ok in checks.items():
            fh.write(f"| `{key}` | {'PASS' if ok else 'FAIL'} |\n")

    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    for name in ("embeddings", "id_map", "walks", "report", "json_report", "log_file"):
        setattr(args, name, resolve_path(getattr(args, name)))
    if args.log_file is None:
        args.log_file = args.report.with_suffix(".log")
    setup_logging(args.log_file)
    start = time.perf_counter()
    LOGGER.info("HCG embedding check started")
    if args.expected_dim <= 0:
        raise ValueError("--expected-dim must be positive")
    if args.expected_min_rows < 0:
        raise ValueError("--expected-min-rows must be >= 0")
    if args.expected_rows < 0:
        raise ValueError("--expected-rows must be >= 0")
    if not args.embeddings.exists():
        raise FileNotFoundError(f"embeddings file not found: {args.embeddings}")

    LOGGER.info("reading parquet: %s size=%d bytes", args.embeddings, args.embeddings.stat().st_size)
    df = pd.read_parquet(args.embeddings)
    LOGGER.info("parquet loaded: rows=%d columns=%d", len(df), len(df.columns))
    expected_emb_cols = [f"emb_{idx:03d}" for idx in range(args.expected_dim)]
    missing_cols = [col for col in ["endpoint_id", "vid", *expected_emb_cols] if col not in df.columns]
    extra_emb_cols = [col for col in df.columns if col.startswith("emb_") and col not in expected_emb_cols]

    endpoint_non_empty = bool(df["endpoint_id"].notna().all()) if "endpoint_id" in df.columns else False
    if endpoint_non_empty:
        endpoint_non_empty = bool((df["endpoint_id"].astype(str).str.len() > 0).all())
    endpoint_unique = bool(df["endpoint_id"].is_unique) if "endpoint_id" in df.columns else False

    if missing_cols:
        vectors = np.empty((len(df), 0), dtype=np.float32)
        nan_count = 0
        inf_count = 0
    else:
        vectors = df[expected_emb_cols].to_numpy(dtype=np.float32, copy=False)
        nan_count = int(np.isnan(vectors).sum())
        inf_count = int(np.isinf(vectors).sum())

    embedding_tokens = set(df["endpoint_id"].astype(str)) if "endpoint_id" in df.columns else set()
    id_map_tokens = read_id_map_tokens(args.id_map)
    walk_tokens = read_walk_tokens(args.walks)

    metrics: dict[str, Any] = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "embedding_dim": int(len([col for col in df.columns if col.startswith("emb_")])),
        "expected_dim": args.expected_dim,
        "missing_required_column_count": len(missing_cols),
        "missing_required_columns": ", ".join(missing_cols),
        "extra_embedding_column_count": len(extra_emb_cols),
        "endpoint_id_unique_count": len(embedding_tokens),
        "nan_count": nan_count,
        "inf_count": inf_count,
    }
    if id_map_tokens is not None:
        intersection = embedding_tokens & id_map_tokens
        not_in_id_map = embedding_tokens - id_map_tokens
        id_map_not_trained = id_map_tokens - embedding_tokens
        metrics.update(
            {
                "id_map_token_count": len(id_map_tokens),
                "embedding_id_map_intersection_count": len(intersection),
                "embedding_not_in_id_map_token_count": len(not_in_id_map),
                "id_map_not_trained_token_count": len(id_map_not_trained),
                "id_map_coverage_percent": (len(intersection) / len(embedding_tokens) * 100.0)
                if embedding_tokens
                else 0.0,
            }
        )
    if walk_tokens is not None:
        walk_missing = walk_tokens - embedding_tokens
        metrics.update(
            {
                "walk_unique_token_count": len(walk_tokens),
                "walk_tokens_covered_count": len(walk_tokens & embedding_tokens),
                "walk_tokens_missing_count": len(walk_missing),
                "walk_token_coverage_percent": ((len(walk_tokens) - len(walk_missing)) / len(walk_tokens) * 100.0)
                if walk_tokens
                else 0.0,
            }
        )
    metrics["check_elapsed_seconds"] = time.perf_counter() - start

    checks = {
        "parquet_readable": True,
        "required_columns_present": not missing_cols,
        "endpoint_id_non_empty": endpoint_non_empty,
        "endpoint_id_unique": endpoint_unique,
        "embedding_dim_matches_expected": metrics["embedding_dim"] == args.expected_dim,
        "no_extra_embedding_columns": len(extra_emb_cols) == 0,
        "no_nan": nan_count == 0,
        "no_inf": inf_count == 0,
        "row_count_at_least_expected_min": len(df) >= args.expected_min_rows,
    }
    if args.expected_rows > 0:
        checks["row_count_equals_expected"] = len(df) == args.expected_rows
    if id_map_tokens is not None:
        checks["all_embeddings_in_id_map"] = metrics["embedding_not_in_id_map_token_count"] == 0
    if walk_tokens is not None:
        checks["all_walk_tokens_covered"] = metrics["walk_tokens_missing_count"] == 0

    write_reports(args, metrics, checks)
    LOGGER.info("reports written: %s %s", args.report, args.json_report)
    LOGGER.info("HCG embedding check finished: status=%s elapsed=%.2fs", "PASS" if all(checks.values()) else "FAIL", metrics["check_elapsed_seconds"])
    print(json.dumps({"metrics": metrics, "checks": checks}, ensure_ascii=False, indent=2, default=str))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
