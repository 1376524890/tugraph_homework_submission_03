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

from create_tugraph_schema import HCG_SCHEMAS, TCG_SCHEMAS  # noqa: E402
from tugraph_homework.common import ROOT  # noqa: E402
from tugraph_homework.transform import HCG_EDGE_FIELDS, HCG_ENDPOINT_FIELDS, TCG_EDGE_FIELDS, TCG_FLOW_FIELDS  # noqa: E402


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
    edge_paths = [processed_dir / "causes.csv"] if (processed_dir / "causes.csv").exists() else csv_parts(processed_dir / "causes_full_parts")
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
