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
    endpoint_id,
    parse_float,
    parse_int,
    parse_timestamp,
    read_rows,
    run_schema,
    safe_call,
    upsert_edges,
    upsert_vertices,
)


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
            {"name": "shared_endpoint", "type": "STRING", "optional": False, "index": True},
            {"name": "delta_seconds", "type": "INT64", "optional": False},
            {"name": "rule", "type": "STRING", "optional": False},
        ],
    },
]


def flow_vertex(row_number: int, row: dict[str, str]) -> dict[str, Any]:
    src = endpoint_id(row["Source.IP"], row["Source.Port"])
    dst = endpoint_id(row["Destination.IP"], row["Destination.Port"])
    timestamp_text, timestamp_epoch = parse_timestamp(row.get("Timestamp", ""))
    return {
        "record_id": str(row_number),
        "flow_id": row.get("Flow.ID", ""),
        "src_endpoint": src,
        "dst_endpoint": dst,
        "protocol": parse_int(row.get("Protocol", "0")),
        "timestamp": timestamp_text,
        "timestamp_epoch": timestamp_epoch,
        "duration": parse_float(row.get("Flow.Duration", "0")),
        "fwd_packets": parse_int(row.get("Total.Fwd.Packets", "0")),
        "bwd_packets": parse_int(row.get("Total.Backward.Packets", "0")),
        "fwd_bytes": parse_int(row.get("Total.Length.of.Fwd.Packets", "0")),
        "bwd_bytes": parse_int(row.get("Total.Length.of.Bwd.Packets", "0")),
        "label": row.get("Label", ""),
        "l7_protocol": parse_int(row.get("L7Protocol", "0")),
        "protocol_name": row.get("ProtocolName", ""),
    }


def causal_edges(
    current: dict[str, Any],
    histories: dict[str, collections.deque[dict[str, Any]]],
    window_seconds: int,
    max_predecessors: int,
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    current_ts = current["timestamp_epoch"]
    if current_ts <= 0:
        return edges

    for shared_endpoint in (current["src_endpoint"], current["dst_endpoint"]):
        history = histories[shared_endpoint]
        while history and current_ts - history[0]["timestamp_epoch"] > window_seconds:
            history.popleft()
        for previous in list(history)[-max_predecessors:]:
            delta = current_ts - previous["timestamp_epoch"]
            if delta < 0:
                continue
            key = (previous["record_id"], current["record_id"], shared_endpoint)
            if key in seen:
                continue
            seen.add(key)
            relation_id = f"{previous['record_id']}->{current['record_id']}@{shared_endpoint}"
            edges.append(
                {
                    "source_id": previous["record_id"],
                    "target_id": current["record_id"],
                    "relation_id": relation_id,
                    "shared_endpoint": shared_endpoint,
                    "delta_seconds": delta,
                    "rule": "shared_endpoint_time_window",
                }
            )
    return edges


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and populate the Traffic Causality Graph (TCG) in TuGraph.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--graph", default=GRAPH)
    parser.add_argument("--batch-size", type=int, default=2000)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--window-seconds", type=int, default=60)
    parser.add_argument("--max-predecessors", type=int, default=3)
    args = parser.parse_args()
    if not args.user or not args.password:
        parser.error("TuGraph credentials are required. Set TUGRAPH_USER/TUGRAPH_PASSWORD in .env or pass --user/--password.")

    run_schema(args.uri, args.user, args.password, args.graph, SCHEMAS)
    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    histories: dict[str, collections.deque[dict[str, Any]]] = collections.defaultdict(collections.deque)
    flow_batch: list[dict[str, Any]] = []
    edge_batch: list[dict[str, Any]] = []
    edge_count = 0

    try:
        with driver.session(database=args.graph) as session:
            safe_call(session, "CALL db.addEdgeIndex('CAUSES', 'relation_id', false, true)")
            for row_number, row in read_rows(args.csv, max_rows=args.max_rows):
                current = flow_vertex(row_number, row)
                flow_batch.append(current)
                edge_batch.extend(causal_edges(current, histories, args.window_seconds, args.max_predecessors))
                for shared_endpoint in (current["src_endpoint"], current["dst_endpoint"]):
                    histories[shared_endpoint].append(current)

                if len(flow_batch) >= args.batch_size:
                    upsert_vertices(session, "Flow", flow_batch)
                    flow_batch = []
                if len(edge_batch) >= args.batch_size:
                    if flow_batch:
                        upsert_vertices(session, "Flow", flow_batch)
                        flow_batch = []
                    upsert_edges(session, "CAUSES", "Flow", "source_id", "Flow", "target_id", edge_batch, "relation_id")
                    edge_count += len(edge_batch)
                    edge_batch = []

                if row_number % 500_000 == 0:
                    print(f"processed_rows={row_number} pending_histories={len(histories)} edges={edge_count}", flush=True)

            upsert_vertices(session, "Flow", flow_batch)
            if edge_batch:
                upsert_edges(session, "CAUSES", "Flow", "source_id", "Flow", "target_id", edge_batch, "relation_id")
                edge_count += len(edge_batch)
            counts = [dict(row) for row in session.run("CALL dbms.meta.countDetail()")]
            print(counts)
            print(f"causal_edges_written={edge_count}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
