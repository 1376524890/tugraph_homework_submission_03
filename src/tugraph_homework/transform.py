from __future__ import annotations

import collections
from pathlib import Path
from typing import Any

from tugraph_homework.common import endpoint_id, parse_float, parse_int, parse_timestamp, read_rows


HCG_ENDPOINT_FIELDS = ["endpoint_id", "ip", "port"]
HCG_EDGE_FIELDS = [
    "source_id",
    "target_id",
    "flow_count",
    "first_seen",
    "last_seen",
    "protocol_names",
    "total_fwd_packets",
    "total_bwd_packets",
    "total_fwd_bytes",
    "total_bwd_bytes",
    "avg_duration",
]
TCG_FLOW_FIELDS = [
    "record_id",
    "flow_id",
    "src_endpoint",
    "dst_endpoint",
    "protocol",
    "timestamp",
    "timestamp_epoch",
    "duration",
    "fwd_packets",
    "bwd_packets",
    "fwd_bytes",
    "bwd_bytes",
    "label",
    "l7_protocol",
    "protocol_name",
]
TCG_EDGE_FIELDS = ["source_id", "target_id", "relation_id", "shared_endpoint", "delta_seconds", "rule"]


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
