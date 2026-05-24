#!/usr/bin/env python3
"""Run HCG node2vec Python procedure in batches with ETA estimation."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import shutil
import tempfile
import time
from pathlib import Path

import requests

from tugraph_homework.common import DEFAULT_PASSWORD, DEFAULT_USER


DEFAULT_HTTP = "http://127.0.0.1:7070"
DEFAULT_PROCEDURE = Path("procedures/hcg_node2vec_walk_py_batch.py")
DEFAULT_EDGE_CSV = Path("data/processed/hcg/communicates.csv")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HCG node2vec walks inside TuGraph via batched Python procedure.")
    parser.add_argument("--http", default=DEFAULT_HTTP)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--graph", default="hcg")
    parser.add_argument("--procedure-name", default="hcg_node2vec_walk_py_batch")
    parser.add_argument("--procedure-path", type=Path, default=DEFAULT_PROCEDURE)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--delete-first", action="store_true")
    parser.add_argument("--call", action="store_true")
    parser.add_argument("--walk-length", type=int, default=20)
    parser.add_argument("--num-walks", type=int, default=5)
    parser.add_argument("--p", type=float, default=1.0)
    parser.add_argument("--q", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260524)
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--max-start-nodes", type=int, default=0, help="Override batch size. 0 means use --batch-size.")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--edge-csv", type=Path, default=DEFAULT_EDGE_CSV)
    parser.add_argument("--output-path", type=Path, default=Path("docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt"))
    parser.add_argument("--id-map-path", type=Path, default=Path("docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv"))
    return parser.parse_args()


def login(args: argparse.Namespace) -> str:
    response = requests.post(
        args.http.rstrip("/") + "/login",
        json={"user": args.user, "password": args.password},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["jwt"]


def auth_headers(jwt: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + jwt}


def upload(args: argparse.Namespace, jwt: str) -> None:
    url = args.http.rstrip("/") + f"/db/{args.graph}/python_plugin"
    if args.delete_first:
        delete_url = url + "/" + args.procedure_name
        response = requests.delete(delete_url, headers=auth_headers(jwt), timeout=30)
        if response.status_code not in (200, 400, 404):
            response.raise_for_status()

    code = args.procedure_path.read_bytes()
    payload = {
        "name": args.procedure_name,
        "description": "HCG node2vec walk generator, Python batched version",
        "code_base64": [base64.b64encode(code).decode("ascii")],
        "read_only": True,
        "code_type": "py",
        "version": "v1",
    }
    headers = auth_headers(jwt) | {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    if response.status_code == 400 and "already exists" in response.text:
        print("upload_skipped=already_exists")
        return
    response.raise_for_status()
    print("upload=ok")


def call_batch(args: argparse.Namespace, jwt: str, start_offset: int, batch_size: int, batch_index: int, out_dir: Path) -> dict:
    url = args.http.rstrip("/") + f"/db/{args.graph}/python_plugin/{args.procedure_name}"
    batch_output = out_dir / f"walks_batch_{batch_index:05d}.txt"
    batch_id_map = out_dir / f"id_map_batch_{batch_index:05d}.csv"
    params = {
        "output_path": str(batch_output),
        "id_map_path": str(batch_id_map),
        "walk_length": args.walk_length,
        "num_walks": args.num_walks,
        "p": args.p,
        "q": args.q,
        "seed": args.seed + batch_index,
        "max_start_nodes": batch_size,
        "start_offset": start_offset,
        "return_preview_lines": 0,
    }
    payload = {"data": json.dumps(params), "timeout": args.timeout, "in_process": args.in_process}
    headers = auth_headers(jwt) | {"Content-Type": "application/json"}
    started = time.time()
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=args.timeout + 30)
    response.raise_for_status()
    elapsed = time.time() - started
    result = json.loads(response.json()["result"])
    result["client_elapsed_seconds"] = elapsed
    return result


def count_unique_sources(edge_csv: Path) -> int:
    sources: set[str] = set()
    with edge_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sources.add(row["src_endpoint"])
    return len(sources)


def merge_walk_parts(parts_dir: Path, final_walks: Path, final_id_map: Path) -> None:
    final_walks.parent.mkdir(parents=True, exist_ok=True)
    final_id_map.parent.mkdir(parents=True, exist_ok=True)
    part_walks = sorted(parts_dir.glob("walks_batch_*.txt"))
    part_id_maps = sorted(parts_dir.glob("id_map_batch_*.csv"))
    with final_walks.open("w", encoding="utf-8") as out:
        for path in part_walks:
            out.write(path.read_text(encoding="utf-8"))
    merged_tokens: set[str] = set()
    for path in part_id_maps:
        with path.open("r", encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                token = line.split(",", 1)[0]
                merged_tokens.add(token)
    with final_id_map.open("w", encoding="utf-8") as out:
        out.write("vid,token\n")
        for token in sorted(merged_tokens, key=lambda s: int(s)):
            out.write(f'{token},"{token}"\n')


def main() -> int:
    args = parse_args()
    jwt = login(args)
    if args.upload:
        upload(args, jwt)
    if not args.call:
        print("Nothing to do. Use --call to run batches.")
        return 0

    batch_size = args.max_start_nodes or args.batch_size
    total_start_nodes = count_unique_sources(args.edge_csv)
    total_batches = math.ceil(max(0, total_start_nodes - args.start_offset) / batch_size) if batch_size else 0

    print(f"total_start_nodes={total_start_nodes}")
    print(f"batch_size={batch_size}")
    print(f"total_batches={total_batches}")
    print(f"start_offset={args.start_offset}")

    with tempfile.TemporaryDirectory(prefix="hcg_node2vec_batches_") as tmp:
        parts_dir = Path(tmp)
        cumulative_elapsed = 0.0
        completed_start_nodes = 0
        completed_batches = 0
        last_rate = None

        while args.start_offset + completed_start_nodes < total_start_nodes:
            batch_index = completed_batches
            current_start_offset = args.start_offset + completed_start_nodes
            t0 = time.time()
            result = call_batch(args, jwt, current_start_offset, batch_size, batch_index, parts_dir)
            batch_elapsed = time.time() - t0
            cumulative_elapsed += batch_elapsed
            batch_start_count = int(result.get("start_node_count", 0))
            batch_walk_count = int(result.get("walk_count", 0))
            if batch_start_count == 0:
                break
            completed_start_nodes += batch_start_count
            completed_batches += 1
            batch_rate = (batch_walk_count / batch_elapsed) if batch_elapsed > 0 else 0.0
            if batch_rate > 0:
                last_rate = batch_rate
            remaining_start_nodes = max(0, total_start_nodes - (args.start_offset + completed_start_nodes))
            eta_seconds = (remaining_start_nodes * args.num_walks / last_rate) if last_rate else None
            print(json.dumps({
                "batch_index": batch_index,
                "batch_start_offset": current_start_offset,
                "batch_start_count": batch_start_count,
                "batch_walk_count": batch_walk_count,
                "batch_elapsed_seconds": batch_elapsed,
                "cumulative_elapsed_seconds": cumulative_elapsed,
                "completed_start_nodes": completed_start_nodes,
                "remaining_start_nodes": remaining_start_nodes,
                "estimated_remaining_seconds": eta_seconds,
                "procedure_result": result,
            }, ensure_ascii=False, indent=2))
            if batch_start_count < batch_size:
                break

        merge_walk_parts(parts_dir, args.output_path, args.id_map_path)

    print(f"merged_walks={args.output_path}")
    print(f"merged_id_map={args.id_map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
