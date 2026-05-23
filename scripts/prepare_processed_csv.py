#!/usr/bin/env python3
"""生成 HCG/TCG 中间 CSV 文件。

本脚本是统一的 CSV 生成入口：HCG 输出 endpoints.csv 和 communicates.csv；
TCG 输出 flows.csv，并按 relation_type 输出 causes_full_parts CSV 分区。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_tcg import (  # noqa: E402
    DEFAULT_MAX_CANDIDATE_EDGES,
    DEFAULT_MAX_DELTA_SECONDS,
    DEFAULT_RELATION_WINDOW_TEXT,
    build_edges,
    estimate_edges_from_path,
    load_flows,
    normalize_window,
    parse_relation_types,
    parse_relation_windows,
    write_estimation_report,
    write_flows,
)
from tugraph_homework.common import DEFAULT_DATASET, ROOT, write_dict_csv  # noqa: E402
from tugraph_homework.transform import HCG_EDGE_FIELDS, HCG_ENDPOINT_FIELDS, build_hcg_rows  # noqa: E402


def replace_tmp(tmp_path: Path, final_path: Path) -> None:
    os.replace(tmp_path, final_path)


def file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def prepare_hcg(csv_path: Path, output_dir: Path, max_rows: int | None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    endpoint_path = output_dir / "endpoints.csv"
    edge_path = output_dir / "communicates.csv"
    endpoint_tmp = endpoint_path.with_suffix(".csv.tmp")
    edge_tmp = edge_path.with_suffix(".csv.tmp")

    endpoints, edges = build_hcg_rows(csv_path, max_rows)
    endpoint_count = write_dict_csv(endpoint_tmp, HCG_ENDPOINT_FIELDS, endpoints.values(), progress_desc="write HCG endpoints", total=len(endpoints))
    edge_count = write_dict_csv(edge_tmp, HCG_EDGE_FIELDS, edges.values(), progress_desc="write HCG edges", total=len(edges))
    replace_tmp(endpoint_tmp, endpoint_path)
    replace_tmp(edge_tmp, edge_path)

    print(f"hcg_endpoints={endpoint_count} file={endpoint_path} size_bytes={file_size(endpoint_path)}")
    print(f"hcg_edges={edge_count} file={edge_path} size_bytes={file_size(edge_path)}")


def prepare_tcg(
    csv_path: Path,
    output_dir: Path,
    relation_types: list[str],
    chunk_size: int,
    max_rows: int | None,
    estimate_first: bool,
    max_candidate_edges: int,
    force_large_build: bool,
    max_delta_seconds: int | None,
    relation_window_overrides: dict[str, int | None] | None,
    dedupe_store: str,
    dedupe_sqlite_path: Path | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    estimate = estimate_edges_from_path(csv_path, max_rows, max_delta_seconds, relation_window_overrides)
    if estimate_first:
        report_path = write_estimation_report(estimate, output_dir)
        print(f"tcg_estimation_report={report_path}")
        print(f"tcg_estimated_candidate_edges={estimate['total']}")

    selected_candidate_edges = sum(estimate[relation_type] for relation_type in relation_types)
    if selected_candidate_edges > max_candidate_edges and not force_large_build:
        raise SystemExit(
            f"Refusing to build TCG: estimated_candidate_edges={selected_candidate_edges:,} "
            f"exceeds max_candidate_edges={max_candidate_edges:,}. "
            "Reduce --relation-types/--max-rows or pass --force-large-build explicitly."
        )

    flows = load_flows(csv_path, max_rows)
    flow_path = write_flows(flows, output_dir, "csv")
    print(f"tcg_flows={len(flows)} file={flow_path} size_bytes={file_size(flow_path)}")

    counts = build_edges(
        flows,
        output_dir,
        relation_types,
        "csv",
        chunk_size,
        max_delta_seconds,
        relation_window_overrides,
        dedupe_store,
        dedupe_sqlite_path,
    )
    for relation_type in relation_types:
        print(f"tcg_{relation_type}_edges={counts[relation_type]}")
    print(f"tcg_causes_parts_dir={output_dir / 'causes_full_parts'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate latest HCG and TCG intermediate CSV files.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--graph", choices=["hcg", "tcg", "all"], default="all")
    parser.add_argument("--output-root", type=Path, default=ROOT / "data" / "processed")
    parser.add_argument("--relation-types", type=parse_relation_types, default=parse_relation_types("CR,PR,DHR,SHR"))
    parser.add_argument("--chunk-size", type=int, default=1_000_000)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--max-delta-seconds", type=int, default=DEFAULT_MAX_DELTA_SECONDS, help="Fallback TCG flow-pair time window in seconds. Use 0 to disable for relations without an override.")
    parser.add_argument(
        "--relation-max-delta-seconds",
        type=parse_relation_windows,
        default=parse_relation_windows(DEFAULT_RELATION_WINDOW_TEXT),
        help=f"TCG time window per relation. Default: {DEFAULT_RELATION_WINDOW_TEXT}. Use RELATION=0 to disable one relation window.",
    )
    parser.add_argument("--skip-estimate", action="store_true", help="Skip TCG estimate report before writing CSV parts.")
    parser.add_argument("--max-candidate-edges", type=int, default=DEFAULT_MAX_CANDIDATE_EDGES, help="Abort TCG build when estimated selected candidate edges exceed this limit.")
    parser.add_argument("--force-large-build", action="store_true", help="Bypass the TCG candidate-edge safety guard.")
    parser.add_argument("--dedupe-store", choices=["sqlite", "memory"], default="sqlite", help="Store TCG pair de-duplication state on disk or in memory. SQLite is slower but uses much less RAM.")
    parser.add_argument("--dedupe-sqlite-path", type=Path, default=None, help="SQLite file for --dedupe-store sqlite. Default: TCG_OUTPUT/.tcg_seen_pairs.sqlite")
    args = parser.parse_args()
    max_delta_seconds = normalize_window(args.max_delta_seconds)

    hcg_dir = args.output_root / "hcg"
    tcg_dir = args.output_root / "tcg"

    if args.graph in ("hcg", "all"):
        prepare_hcg(args.csv, hcg_dir, args.max_rows)
    if args.graph in ("tcg", "all"):
        prepare_tcg(
            args.csv,
            tcg_dir,
            args.relation_types,
            args.chunk_size,
            args.max_rows,
            not args.skip_estimate,
            args.max_candidate_edges,
            args.force_large_build,
            max_delta_seconds,
            args.relation_max_delta_seconds,
            args.dedupe_store,
            args.dedupe_sqlite_path,
        )


if __name__ == "__main__":
    main()
