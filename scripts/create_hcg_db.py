#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import (  # noqa: E402
    DEFAULT_DATASET,
    DEFAULT_PASSWORD,
    DEFAULT_URI,
    DEFAULT_USER,
    batched,
    endpoint_id,
    parse_float,
    parse_int,
    parse_timestamp,
    read_rows,
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
        ],
    },
    {
        "label": "COMMUNICATES",
        "type": "EDGE",
        "detach_property": True,
        "constraints": [["Endpoint", "Endpoint"]],
        "properties": [
            {"name": "flow_count", "type": "INT64", "optional": False},
            {"name": "first_seen", "type": "STRING", "optional": True},
            {"name": "last_seen", "type": "STRING", "optional": True},
            {"name": "protocol_names", "type": "STRING", "optional": True},
            {"name": "total_fwd_packets", "type": "INT64", "optional": False},
            {"name": "total_bwd_packets", "type": "INT64", "optional": False},
            {"name": "total_fwd_bytes", "type": "INT64", "optional": False},
            {"name": "total_bwd_bytes", "type": "INT64", "optional": False},
            {"name": "avg_duration", "type": "DOUBLE", "optional": False},
        ],
    },
]


def build_hcg_rows(csv_path: Path, max_rows: int | None) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    endpoints: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    protocol_sets: dict[tuple[str, str], set[str]] = collections.defaultdict(set)

    for row_number, row in read_rows(csv_path, max_rows=max_rows):
        src = endpoint_id(row["Source.IP"], row["Source.Port"])
        dst = endpoint_id(row["Destination.IP"], row["Destination.Port"])
        endpoints.setdefault(src, {"endpoint_id": src, "ip": row["Source.IP"], "port": parse_int(row["Source.Port"])})
        endpoints.setdefault(dst, {"endpoint_id": dst, "ip": row["Destination.IP"], "port": parse_int(row["Destination.Port"])})

        timestamp_text, timestamp_epoch = parse_timestamp(row.get("Timestamp", ""))
        key = (src, dst)
        edge = edges.setdefault(
            key,
            {
                "source_id": src,
                "target_id": dst,
                "flow_count": 0,
                "first_seen": timestamp_text,
                "last_seen": timestamp_text,
                "_first_epoch": timestamp_epoch,
                "_last_epoch": timestamp_epoch,
                "total_fwd_packets": 0,
                "total_bwd_packets": 0,
                "total_fwd_bytes": 0,
                "total_bwd_bytes": 0,
                "_duration_sum": 0.0,
            },
        )
        edge["flow_count"] += 1
        edge["total_fwd_packets"] += parse_int(row.get("Total.Fwd.Packets", "0"))
        edge["total_bwd_packets"] += parse_int(row.get("Total.Backward.Packets", "0"))
        edge["total_fwd_bytes"] += parse_int(row.get("Total.Length.of.Fwd.Packets", "0"))
        edge["total_bwd_bytes"] += parse_int(row.get("Total.Length.of.Bwd.Packets", "0"))
        edge["_duration_sum"] += parse_float(row.get("Flow.Duration", "0"))
        if timestamp_epoch and (not edge["_first_epoch"] or timestamp_epoch < edge["_first_epoch"]):
            edge["_first_epoch"] = timestamp_epoch
            edge["first_seen"] = timestamp_text
        if timestamp_epoch and timestamp_epoch > edge["_last_epoch"]:
            edge["_last_epoch"] = timestamp_epoch
            edge["last_seen"] = timestamp_text
        protocol_name = row.get("ProtocolName", "")
        if protocol_name and len(protocol_sets[key]) < 12:
            protocol_sets[key].add(protocol_name)

        if row_number % 500_000 == 0:
            print(f"aggregated_rows={row_number} endpoints={len(endpoints)} edges={len(edges)}", flush=True)

    for key, edge in edges.items():
        edge["protocol_names"] = ",".join(sorted(protocol_sets.get(key, set())))
        edge["avg_duration"] = edge["_duration_sum"] / edge["flow_count"] if edge["flow_count"] else 0.0
        edge.pop("_duration_sum", None)
        edge.pop("_first_epoch", None)
        edge.pop("_last_epoch", None)
    return endpoints, edges


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and populate the Host Communication Graph (HCG) in TuGraph.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--graph", default=GRAPH)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()
    if not args.user or not args.password:
        parser.error("TuGraph credentials are required. Set TUGRAPH_USER/TUGRAPH_PASSWORD in .env or pass --user/--password.")

    run_schema(args.uri, args.user, args.password, args.graph, SCHEMAS)
    endpoints, edges = build_hcg_rows(args.csv, args.max_rows)

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        with driver.session(database=args.graph) as session:
            for batch in batched(endpoints.values(), args.batch_size):
                upsert_vertices(session, "Endpoint", batch)
            for batch in batched(edges.values(), args.batch_size):
                upsert_edges(session, "COMMUNICATES", "Endpoint", "source_id", "Endpoint", "target_id", batch)
            counts = [dict(row) for row in session.run("CALL dbms.meta.countDetail()")]
            print(counts)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
