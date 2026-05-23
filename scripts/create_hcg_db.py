#!/usr/bin/env python3
"""创建并导入 HCG TuGraph 子图。

本脚本通过 Bolt 创建 Endpoint/COMMUNICATES schema，并把 HCG 中间 CSV
endpoints.csv 和 communicates.csv 导入 TuGraph。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import (  # noqa: E402
    DEFAULT_PASSWORD,
    ROOT,
    DEFAULT_URI,
    DEFAULT_USER,
    batched,
    parse_float,
    parse_int,
    progress_bar,
    read_dict_csv,
    run_schema,
    upsert_edges,
    upsert_vertices,
)


GRAPH = "hcg"


SCHEMAS: list[dict[str, Any]] = [
    {
        "label": "Endpoint",
        "primary": "endpoint_id",
        "type": "VERTEX",
        "detach_property": True,
        "properties": [
            {"name": "endpoint_id", "type": "STRING", "optional": False},
            {"name": "ip", "type": "STRING", "optional": False, "index": True},
            {"name": "port", "type": "INT64", "optional": False, "index": True},
            {"name": "is_private_ip", "type": "BOOL", "optional": False, "index": True},
            {"name": "port_bucket", "type": "STRING", "optional": False, "index": True},
            {"name": "is_common_service_port", "type": "BOOL", "optional": False, "index": True},
            {"name": "is_proxy_port", "type": "BOOL", "optional": False, "index": True},
        ],
    },
    {
        "label": "COMMUNICATES",
        "type": "EDGE",
        "detach_property": True,
        "constraints": [["Endpoint", "Endpoint"]],
        "properties": [
            {"name": "edge_id", "type": "STRING", "optional": False},
            {"name": "src_endpoint", "type": "STRING", "optional": False, "index": True},
            {"name": "dst_endpoint", "type": "STRING", "optional": False, "index": True},
            {"name": "flow_count", "type": "INT64", "optional": False},
            {"name": "first_seen_epoch", "type": "INT64", "optional": False, "index": True},
            {"name": "last_seen_epoch", "type": "INT64", "optional": False, "index": True},
            {"name": "first_seen", "type": "STRING", "optional": True},
            {"name": "last_seen", "type": "STRING", "optional": True},
            {"name": "total_fwd_packets", "type": "INT64", "optional": False},
            {"name": "total_bwd_packets", "type": "INT64", "optional": False},
            {"name": "total_packets", "type": "INT64", "optional": False},
            {"name": "total_fwd_bytes", "type": "INT64", "optional": False},
            {"name": "total_bwd_bytes", "type": "INT64", "optional": False},
            {"name": "total_bytes", "type": "INT64", "optional": False},
            {"name": "avg_duration", "type": "DOUBLE", "optional": False},
            {"name": "min_duration", "type": "DOUBLE", "optional": False},
            {"name": "max_duration", "type": "DOUBLE", "optional": False},
            {"name": "protocol_set", "type": "STRING", "optional": True},
            {"name": "protocol_name_set", "type": "STRING", "optional": True},
            {"name": "major_protocol", "type": "INT64", "optional": False, "index": True},
            {"name": "major_protocol_name", "type": "STRING", "optional": True, "index": True},
            {"name": "protocol_entropy", "type": "DOUBLE", "optional": False},
            {"name": "l7_protocol_entropy", "type": "DOUBLE", "optional": False},
        ],
    },
]


def hcg_endpoint_from_csv(row: dict[str, str]) -> dict[str, Any]:
    return {
        "endpoint_id": row["endpoint_id"],
        "ip": row["ip"],
        "port": parse_int(row.get("port", "0")),
        "is_private_ip": row.get("is_private_ip", "").lower() == "true",
        "port_bucket": row.get("port_bucket", "invalid"),
        "is_common_service_port": row.get("is_common_service_port", "").lower() == "true",
        "is_proxy_port": row.get("is_proxy_port", "").lower() == "true",
    }


def hcg_edge_from_csv(row: dict[str, str]) -> dict[str, Any]:
    return {
        "edge_id": row.get("edge_id", ""),
        "src_endpoint": row.get("src_endpoint", row.get("source_id", "")),
        "dst_endpoint": row.get("dst_endpoint", row.get("target_id", "")),
        "source_id": row.get("source_id", row.get("src_endpoint", "")),
        "target_id": row.get("target_id", row.get("dst_endpoint", "")),
        "flow_count": parse_int(row.get("flow_count", "0")),
        "first_seen_epoch": parse_int(row.get("first_seen_epoch", "0")),
        "last_seen_epoch": parse_int(row.get("last_seen_epoch", "0")),
        "first_seen": row.get("first_seen", ""),
        "last_seen": row.get("last_seen", ""),
        "total_fwd_packets": parse_int(row.get("total_fwd_packets", "0")),
        "total_bwd_packets": parse_int(row.get("total_bwd_packets", "0")),
        "total_packets": parse_int(row.get("total_packets", "0")),
        "total_fwd_bytes": parse_int(row.get("total_fwd_bytes", "0")),
        "total_bwd_bytes": parse_int(row.get("total_bwd_bytes", "0")),
        "total_bytes": parse_int(row.get("total_bytes", "0")),
        "avg_duration": parse_float(row.get("avg_duration", "0")),
        "min_duration": parse_float(row.get("min_duration", "0")),
        "max_duration": parse_float(row.get("max_duration", "0")),
        "protocol_set": row.get("protocol_set", ""),
        "protocol_name_set": row.get("protocol_name_set", ""),
        "major_protocol": parse_int(row.get("major_protocol", "0")),
        "major_protocol_name": row.get("major_protocol_name", ""),
        "protocol_entropy": parse_float(row.get("protocol_entropy", "0")),
        "l7_protocol_entropy": parse_float(row.get("l7_protocol_entropy", "0")),
    }


def processed_paths(processed_dir: Path) -> tuple[Path, Path]:
    return processed_dir / "endpoints.csv", processed_dir / "communicates.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and populate the Host Communication Graph (HCG) in TuGraph from processed CSV files.")
    parser.add_argument("--processed-dir", type=Path, default=ROOT / "data" / "processed" / "hcg")
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--graph", default=GRAPH)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--progress-interval", type=int, default=500_000, help="Print import progress after this many written rows.")
    args = parser.parse_args()
    if not args.user or not args.password:
        parser.error("TuGraph credentials are required. Set TUGRAPH_USER/TUGRAPH_PASSWORD in .env or pass --user/--password.")

    run_schema(args.uri, args.user, args.password, args.graph, SCHEMAS)
    endpoint_path, edge_path = processed_paths(args.processed_dir)
    if not endpoint_path.exists() or not edge_path.exists():
        parser.error(f"HCG CSV files not found in {args.processed_dir}. Run scripts/prepare_processed_csv.py --graph hcg --output-root data/processed first.")
    endpoint_rows = (hcg_endpoint_from_csv(row) for row in read_dict_csv(endpoint_path))
    edge_rows = (hcg_edge_from_csv(row) for row in read_dict_csv(edge_path))

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    endpoint_count = 0
    edge_count = 0
    try:
        with driver.session(database=args.graph) as session:
            endpoint_bar = progress_bar("import HCG endpoints", "rows")
            try:
                for batch in batched(endpoint_rows, args.batch_size):
                    upsert_vertices(session, "Endpoint", batch)
                    endpoint_count += len(batch)
                    if endpoint_bar is not None:
                        endpoint_bar.update(len(batch))
                    if args.progress_interval > 0 and endpoint_count % args.progress_interval == 0:
                        print(f"endpoint_vertices_written={endpoint_count}", flush=True)
            finally:
                if endpoint_bar is not None:
                    endpoint_bar.close()
            edge_bar = progress_bar("import HCG edges", "rows")
            try:
                for batch in batched(edge_rows, args.batch_size):
                    upsert_edges(session, "COMMUNICATES", "Endpoint", "source_id", "Endpoint", "target_id", batch)
                    edge_count += len(batch)
                    if edge_bar is not None:
                        edge_bar.update(len(batch))
                    if args.progress_interval > 0 and edge_count % args.progress_interval == 0:
                        print(f"communicates_edges_written={edge_count}", flush=True)
            finally:
                if edge_bar is not None:
                    edge_bar.close()
            counts = [dict(row) for row in session.run("CALL dbms.meta.countDetail()")]
            print(counts)
            print(f"endpoint_vertices_written={endpoint_count}")
            print(f"communicates_edges_written={edge_count}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
