#!/usr/bin/env python3
"""Create TuGraph graphs and schemas through Bolt.

Data import is handled only by TuGraph native lgraph_import. This script keeps
Bolt usage limited to graph and schema creation for online validation paths.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import DEFAULT_PASSWORD, DEFAULT_URI, DEFAULT_USER, run_schema  # noqa: E402


HCG_GRAPH = "hcg"
TCG_GRAPH = "tcg"

HCG_SCHEMAS: list[dict[str, Any]] = [
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

TCG_SCHEMAS: list[dict[str, Any]] = [
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

SCHEMAS_BY_GRAPH = {
    "hcg": (HCG_GRAPH, HCG_SCHEMAS),
    "tcg": (TCG_GRAPH, TCG_SCHEMAS),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create TuGraph graph and schema labels through Bolt. Does not import data.")
    parser.add_argument("--graph-type", choices=sorted(SCHEMAS_BY_GRAPH), required=True)
    parser.add_argument("--graph", default=None, help="Override graph name. Defaults to hcg or tcg.")
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args()
    if not args.user or not args.password:
        parser.error("TuGraph credentials are required. Set TUGRAPH_USER/TUGRAPH_PASSWORD in .env or pass --user/--password.")

    default_graph, schemas = SCHEMAS_BY_GRAPH[args.graph_type]
    graph = args.graph or default_graph
    run_schema(args.uri, args.user, args.password, graph, schemas)
    print(f"schema_created graph={graph} graph_type={args.graph_type}")


if __name__ == "__main__":
    main()
