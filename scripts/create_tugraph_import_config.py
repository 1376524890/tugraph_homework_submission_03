#!/usr/bin/env python3
"""Generate lgraph_import config files for TuGraph native bulk import."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tugraph_homework.common import ROOT  # noqa: E402
from tugraph_homework.transform import HCG_EDGE_FIELDS, HCG_ENDPOINT_FIELDS, TCG_EDGE_FIELDS, TCG_FLOW_FIELDS  # noqa: E402


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
        ],
    },
]


def strip_indexes(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = copy.deepcopy(schemas)
    for schema in clean:
        for prop in schema.get("properties", []):
            prop.pop("index", None)
    return clean


def container_path(local_path: Path, local_root: Path, container_root: str) -> str:
    path = local_path.resolve()
    root = local_root.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"{path} is not under local import root {root}") from exc
    return str(Path(container_root) / relative)


def csv_parts(parts_dir: Path) -> list[Path]:
    return sorted(parts_dir.glob("relation_type=*/*.csv"))


def csv_part_dirs(parts_dir: Path) -> list[Path]:
    return sorted(path for path in parts_dir.glob("relation_type=*") if path.is_dir() and any(path.glob("*.csv")))


def hcg_config(processed_dir: Path, local_root: Path, container_root: str, keep_indexes: bool) -> dict[str, Any]:
    endpoint_path = processed_dir / "endpoints.csv"
    edge_path = processed_dir / "communicates.csv"
    if not endpoint_path.exists() or not edge_path.exists():
        raise SystemExit(f"HCG CSV files not found in {processed_dir}")
    schemas = copy.deepcopy(HCG_SCHEMAS) if keep_indexes else strip_indexes(HCG_SCHEMAS)
    return {
        "schema": schemas,
        "files": [
            {
                "path": container_path(endpoint_path, local_root, container_root),
                "format": "CSV",
                "label": "Endpoint",
                "header": 1,
                "columns": HCG_ENDPOINT_FIELDS,
            },
            {
                "path": container_path(edge_path, local_root, container_root),
                "format": "CSV",
                "label": "COMMUNICATES",
                "header": 1,
                "SRC_ID": "Endpoint",
                "DST_ID": "Endpoint",
                "columns": ["edge_id", "src_endpoint", "dst_endpoint", "SRC_ID", "DST_ID", *HCG_EDGE_FIELDS[5:]],
            },
        ],
    }


def tcg_config(processed_dir: Path, local_root: Path, container_root: str, keep_indexes: bool) -> dict[str, Any]:
    flow_path = processed_dir / "flows.csv"
    edge_paths = [processed_dir / "causes.csv"] if (processed_dir / "causes.csv").exists() else csv_part_dirs(processed_dir / "causes_full_parts")
    if not edge_paths:
        edge_paths = csv_parts(processed_dir / "causes_full_parts")
    if not flow_path.exists() or not edge_paths:
        raise SystemExit(f"TCG CSV files not found in {processed_dir}")
    schemas = copy.deepcopy(TCG_SCHEMAS) if keep_indexes else strip_indexes(TCG_SCHEMAS)
    files: list[dict[str, Any]] = [
        {
            "path": container_path(flow_path, local_root, container_root),
            "format": "CSV",
            "label": "Flow",
            "header": 1,
            "columns": TCG_FLOW_FIELDS,
        }
    ]
    edge_columns = [
        "relation_id",
        "src_record_id",
        "dst_record_id",
        "SRC_ID",
        "DST_ID",
        *TCG_EDGE_FIELDS[5:],
    ]
    for edge_path in edge_paths:
        files.append(
            {
                "path": container_path(edge_path, local_root, container_root),
                "format": "CSV",
                "label": "CAUSES",
                "header": 1,
                "SRC_ID": "Flow",
                "DST_ID": "Flow",
                "columns": edge_columns,
            }
        )
    return {"schema": schemas, "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a TuGraph lgraph_import JSON config for HCG or TCG CSV files.")
    parser.add_argument("--graph-type", choices=["hcg", "tcg"], required=True)
    parser.add_argument("--processed-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-import-root", type=Path, default=ROOT)
    parser.add_argument("--container-import-root", default="/workspace")
    parser.add_argument("--keep-indexes", action="store_true", help="Keep secondary indexes in the import schema. Default strips them for bulk import.")
    args = parser.parse_args()

    if args.graph_type == "hcg":
        config = hcg_config(args.processed_dir, args.local_import_root, args.container_import_root, args.keep_indexes)
    else:
        config = tcg_config(args.processed_dir, args.local_import_root, args.container_import_root, args.keep_indexes)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"import_config={args.output}")


if __name__ == "__main__":
    main()
