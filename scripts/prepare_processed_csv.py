#!/usr/bin/env python3
"""生成传统 processed CSV 的兼容入口。

本脚本保留 HCG processed CSV 生成能力；旧版 TCG shared_endpoint_time_window
生成逻辑已禁用。新版 TCG 请使用 scripts/build_tcg.py。
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import (  # noqa: E402
    DEFAULT_DATASET,
    HCG_PROCESSED_DIR,
    PROCESSED_ROOT,
    TCG_PROCESSED_DIR,
    read_rows,
    write_dict_csv,
)
from tugraph_homework.transform import (  # noqa: E402
    HCG_EDGE_FIELDS,
    HCG_ENDPOINT_FIELDS,
    TCG_EDGE_FIELDS,
    TCG_FLOW_FIELDS,
    build_hcg_rows,
    flow_vertex,
)


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
    endpoint_count = write_dict_csv(endpoint_tmp, HCG_ENDPOINT_FIELDS, endpoints.values())
    edge_count = write_dict_csv(edge_tmp, HCG_EDGE_FIELDS, edges.values())
    replace_tmp(endpoint_tmp, endpoint_path)
    replace_tmp(edge_tmp, edge_path)

    print(f"hcg_endpoints={endpoint_count} file={endpoint_path} size_bytes={file_size(endpoint_path)}")
    print(f"hcg_edges={edge_count} file={edge_path} size_bytes={file_size(edge_path)}")


def prepare_tcg(
    csv_path: Path,
    output_dir: Path,
    max_rows: int | None,
    window_seconds: int,
    max_predecessors: int,
) -> None:
    raise RuntimeError(
        "The old TCG shared_endpoint_time_window builder is disabled. "
        "Use scripts/build_tcg.py --mode estimate or --mode build to construct CR/PR/DHR/SHR TCG files."
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    flow_path = output_dir / "flows.csv"
    edge_path = output_dir / "causes.csv"
    flow_tmp = flow_path.with_suffix(".csv.tmp")
    edge_tmp = edge_path.with_suffix(".csv.tmp")

    flow_count = 0
    edge_count = 0

    with flow_tmp.open("w", newline="", encoding="utf-8") as flow_fh, edge_tmp.open("w", newline="", encoding="utf-8") as edge_fh:
        flow_writer = csv.DictWriter(flow_fh, fieldnames=TCG_FLOW_FIELDS)
        edge_writer = csv.DictWriter(edge_fh, fieldnames=TCG_EDGE_FIELDS)
        flow_writer.writeheader()
        edge_writer.writeheader()

        for row_number, row in read_rows(csv_path, max_rows=max_rows):
            current = flow_vertex(row_number, row)
            flow_writer.writerow({name: current.get(name, "") for name in TCG_FLOW_FIELDS})
            flow_count += 1

            if row_number % 500_000 == 0:
                print(f"tcg_processed_rows={row_number} tcg_edges={edge_count}", flush=True)

    replace_tmp(flow_tmp, flow_path)
    replace_tmp(edge_tmp, edge_path)
    print(f"tcg_flows={flow_count} file={flow_path} size_bytes={file_size(flow_path)}")
    print(f"tcg_edges={edge_count} file={edge_path} size_bytes={file_size(edge_path)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate processed CSV files for HCG and TCG before importing into TuGraph.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--graph", choices=["hcg", "tcg", "all"], default="all")
    parser.add_argument("--output-root", type=Path, default=PROCESSED_ROOT)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--window-seconds", type=int, default=60, help=argparse.SUPPRESS)
    parser.add_argument("--max-predecessors", type=int, default=3, help=argparse.SUPPRESS)
    args = parser.parse_args()

    hcg_dir = HCG_PROCESSED_DIR if args.output_root == PROCESSED_ROOT else args.output_root / "hcg"
    tcg_dir = TCG_PROCESSED_DIR if args.output_root == PROCESSED_ROOT else args.output_root / "tcg"

    if args.graph in ("hcg", "all"):
        prepare_hcg(args.csv, hcg_dir, args.max_rows)
    if args.graph in ("tcg", "all"):
        prepare_tcg(args.csv, tcg_dir, args.max_rows, args.window_seconds, args.max_predecessors)


if __name__ == "__main__":
    main()
