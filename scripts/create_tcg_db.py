#!/usr/bin/env python3
"""创建并导入 TCG TuGraph 子图。

本脚本负责创建 Flow/CAUSES schema，并导入已经生成的新版 TCG 中间文件。
旧版 direct-csv 在线构图已禁用，避免继续使用 shared_endpoint_time_window。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import (  # noqa: E402
    DEFAULT_DATASET,
    DEFAULT_PASSWORD,
    DEFAULT_URI,
    DEFAULT_USER,
    TCG_PROCESSED_DIR,
    batched,
    parse_float,
    parse_int,
    read_dict_csv,
    run_schema,
    safe_call,
    upsert_edges,
    upsert_vertices,
)
from tugraph_homework.transform import TCG_EDGE_FIELDS, TCG_FLOW_FIELDS  # noqa: E402


GRAPH = "tcg"
SCHEMAS: list[dict[str, Any]] = [
    {
        "label": "Flow",
        "primary": "record_id",
        "type": "VERTEX",
        "detach_property": True,
        "properties": [
            {"name": "record_id", "type": "STRING", "optional": False},
            {"name": "flow_id", "type": "STRING", "optional": False, "index": True},
            {"name": "src_endpoint", "type": "STRING", "optional": False, "index": True},
            {"name": "dst_endpoint", "type": "STRING", "optional": False, "index": True},
            {"name": "src_ip", "type": "STRING", "optional": False, "index": True},
            {"name": "src_port", "type": "INT64", "optional": False, "index": True},
            {"name": "dst_ip", "type": "STRING", "optional": False, "index": True},
            {"name": "dst_port", "type": "INT64", "optional": False, "index": True},
            {"name": "protocol", "type": "INT64", "optional": False},
            {"name": "timestamp", "type": "STRING", "optional": True},
            {"name": "timestamp_epoch", "type": "INT64", "optional": False, "index": True},
            {"name": "duration", "type": "DOUBLE", "optional": False},
            {"name": "fwd_packets", "type": "INT64", "optional": False},
            {"name": "bwd_packets", "type": "INT64", "optional": False},
            {"name": "fwd_bytes", "type": "INT64", "optional": False},
            {"name": "bwd_bytes", "type": "INT64", "optional": False},
            {"name": "label", "type": "STRING", "optional": True},
            {"name": "l7_protocol", "type": "INT64", "optional": False},
            {"name": "protocol_name", "type": "STRING", "optional": True, "index": True},
        ],
    },
    {
        "label": "CAUSES",
        "type": "EDGE",
        "detach_property": True,
        "constraints": [["Flow", "Flow"]],
        "properties": [
            {"name": "relation_id", "type": "STRING", "optional": False},
            {"name": "src_record_id", "type": "STRING", "optional": False, "index": True},
            {"name": "dst_record_id", "type": "STRING", "optional": False, "index": True},
            {"name": "relation_type", "type": "STRING", "optional": False, "index": True},
            {"name": "relation_priority", "type": "INT64", "optional": False},
            {"name": "delta_seconds", "type": "INT64", "optional": False, "index": True},
            {"name": "same_timestamp", "type": "BOOL", "optional": False},
            {"name": "matched_rule", "type": "STRING", "optional": False},
            {"name": "src_flow_timestamp_epoch", "type": "INT64", "optional": False},
            {"name": "dst_flow_timestamp_epoch", "type": "INT64", "optional": False},
            {"name": "shared_ip", "type": "STRING", "optional": True, "index": True},
            {"name": "shared_endpoint", "type": "STRING", "optional": False, "index": True},
            {"name": "src_ip_pair", "type": "STRING", "optional": False},
            {"name": "src_port_pair", "type": "STRING", "optional": False},
            {"name": "dst_ip_pair", "type": "STRING", "optional": False},
            {"name": "dst_port_pair", "type": "STRING", "optional": False},
            {"name": "protocol_pair", "type": "STRING", "optional": False},
        ],
    },
]


def flow_from_csv(row: dict[str, str]) -> dict[str, Any]:
    return {
        "record_id": row["record_id"],
        "flow_id": row.get("flow_id", ""),
        "src_endpoint": row["src_endpoint"],
        "dst_endpoint": row["dst_endpoint"],
        "src_ip": row.get("src_ip", ""),
        "src_port": parse_int(row.get("src_port", "0")),
        "dst_ip": row.get("dst_ip", ""),
        "dst_port": parse_int(row.get("dst_port", "0")),
        "protocol": parse_int(row.get("protocol", "0")),
        "timestamp": row.get("timestamp", ""),
        "timestamp_epoch": parse_int(row.get("timestamp_epoch", "0")),
        "duration": parse_float(row.get("duration", "0")),
        "fwd_packets": parse_int(row.get("fwd_packets", "0")),
        "bwd_packets": parse_int(row.get("bwd_packets", "0")),
        "fwd_bytes": parse_int(row.get("fwd_bytes", "0")),
        "bwd_bytes": parse_int(row.get("bwd_bytes", "0")),
        "label": row.get("label", ""),
        "l7_protocol": parse_int(row.get("l7_protocol", "0")),
        "protocol_name": row.get("protocol_name", ""),
    }


def edge_from_csv(row: dict[str, str]) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "relation_id": row["relation_id"],
        "src_record_id": row.get("src_record_id", row.get("source_id", "")),
        "dst_record_id": row.get("dst_record_id", row.get("target_id", "")),
        "relation_type": row.get("relation_type", ""),
        "relation_priority": parse_int(row.get("relation_priority", "0")),
        "delta_seconds": parse_int(row.get("delta_seconds", "0")),
        "same_timestamp": row.get("same_timestamp", "").lower() == "true",
        "matched_rule": row.get("matched_rule", ""),
        "src_flow_timestamp_epoch": parse_int(row.get("src_flow_timestamp_epoch", "0")),
        "dst_flow_timestamp_epoch": parse_int(row.get("dst_flow_timestamp_epoch", "0")),
        "shared_ip": row.get("shared_ip", ""),
        "shared_endpoint": row.get("shared_endpoint", ""),
        "src_ip_pair": row.get("src_ip_pair", ""),
        "src_port_pair": row.get("src_port_pair", ""),
        "dst_ip_pair": row.get("dst_ip_pair", ""),
        "dst_port_pair": row.get("dst_port_pair", ""),
        "protocol_pair": row.get("protocol_pair", ""),
    }


def processed_paths(processed_dir: Path) -> tuple[Path, Path]:
    return processed_dir / "flows.csv", processed_dir / "causes.csv"


def import_processed(args: argparse.Namespace) -> None:
    flow_path, edge_path = processed_paths(args.processed_dir)
    if not flow_path.exists() or not edge_path.exists():
        raise FileNotFoundError(f"Processed TCG CSV files not found in {args.processed_dir}. Run scripts/prepare_processed_csv.py --graph tcg first.")

    run_schema(args.uri, args.user, args.password, args.graph, SCHEMAS)
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    flow_count = 0
    edge_count = 0
    try:
        with driver.session(database=args.graph) as session:
            safe_call(session, "CALL db.addEdgeIndex('CAUSES', 'relation_id', false, true)")
            for batch in batched((flow_from_csv(row) for row in read_dict_csv(flow_path)), args.batch_size):
                upsert_vertices(session, "Flow", batch)
                flow_count += len(batch)
                if args.progress_interval > 0 and flow_count % args.progress_interval == 0:
                    print(f"flow_vertices_written={flow_count}", flush=True)
            for batch in batched((edge_from_csv(row) for row in read_dict_csv(edge_path)), args.batch_size):
                upsert_edges(session, "CAUSES", "Flow", "source_id", "Flow", "target_id", batch, "relation_id")
                edge_count += len(batch)
                if args.progress_interval > 0 and edge_count % args.progress_interval == 0:
                    print(f"causal_edges_written={edge_count}", flush=True)
            counts = [dict(row) for row in session.run("CALL dbms.meta.countDetail()")]
            print(counts)
            print(f"flow_vertices_written={flow_count}")
            print(f"causal_edges_written={edge_count}")
    finally:
        driver.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and populate the Traffic Causality Graph (TCG) in TuGraph from processed CSV files.")
    parser.add_argument("--processed-dir", type=Path, default=TCG_PROCESSED_DIR)
    parser.add_argument("--direct-csv", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--graph", default=GRAPH)
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--max-rows", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--window-seconds", type=int, default=60, help=argparse.SUPPRESS)
    parser.add_argument("--max-predecessors", type=int, default=3, help=argparse.SUPPRESS)
    parser.add_argument("--progress-interval", type=int, default=500_000, help="Print import progress after this many processed or written rows.")
    args = parser.parse_args()
    if not args.user or not args.password:
        parser.error("TuGraph credentials are required. Set TUGRAPH_USER/TUGRAPH_PASSWORD in .env or pass --user/--password.")

    if args.direct_csv:
        parser.error("Direct raw CSV TCG import is disabled. Build CR/PR/DHR/SHR files with scripts/build_tcg.py, then import processed files.")
    try:
        import_processed(args)
    except FileNotFoundError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
