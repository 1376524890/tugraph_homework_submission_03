#!/usr/bin/env python3
"""Upload and call the HCG node2vec Python stored procedure."""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

import requests
from requests import exceptions as requests_exceptions

from tugraph_homework.common import DEFAULT_PASSWORD, DEFAULT_USER


DEFAULT_HTTP = "http://127.0.0.1:7070"
DEFAULT_PROCEDURE = Path("procedures/hcg_node2vec_walk_py.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HCG node2vec walks inside TuGraph via Python procedure.")
    parser.add_argument("--http", default=DEFAULT_HTTP)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--graph", default="hcg")
    parser.add_argument("--procedure-name", default="hcg_node2vec_walk_py")
    parser.add_argument("--procedure-path", type=Path, default=DEFAULT_PROCEDURE)
    parser.add_argument("--upload", action="store_true", help="Upload or replace the Python procedure before running.")
    parser.add_argument("--delete-first", action="store_true", help="Delete the existing procedure before upload.")
    parser.add_argument("--call", action="store_true", help="Call the procedure.")
    parser.add_argument("--output-path", default="/tmp/hcg_walks_node2vec_py_smoke.txt")
    parser.add_argument("--id-map-path", default="/tmp/hcg_node_id_map_node2vec_py_smoke.csv")
    parser.add_argument("--walk-length", type=int, default=10)
    parser.add_argument("--num-walks", type=int, default=2)
    parser.add_argument("--p", type=float, default=1.0)
    parser.add_argument("--q", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260524)
    parser.add_argument("--max-start-nodes", type=int, default=100)
    parser.add_argument("--start-vid", type=int, default=-1)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--delete-timeout", type=float, default=300)
    parser.add_argument("--in-process", action="store_true")
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


def delete_procedure(args: argparse.Namespace, jwt: str) -> bool:
    url = args.http.rstrip("/") + f"/db/{args.graph}/python_plugin/{args.procedure_name}"
    try:
        response = requests.delete(url, headers=auth_headers(jwt), timeout=args.delete_timeout)
        if response.status_code not in (200, 400, 404):
            response.raise_for_status()
        return True
    except requests_exceptions.Timeout:
        print(f"delete_timeout_after_seconds={args.delete_timeout}; continuing with upload")
        return False


def upload(args: argparse.Namespace, jwt: str) -> None:
    url = args.http.rstrip("/") + f"/db/{args.graph}/python_plugin"
    if args.delete_first:
        delete_procedure(args, jwt)

    code = args.procedure_path.read_bytes()
    payload = {
        "name": args.procedure_name,
        "description": "HCG node2vec walk generator, Python active version",
        "code_base64": [base64.b64encode(code).decode("ascii")],
        "read_only": True,
        "code_type": "py",
        "version": "v1",
    }
    headers = auth_headers(jwt) | {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    if response.status_code == 400 and "already exists" in response.text:
        if args.delete_first:
            print("upload_conflict_retry_delete=1")
            delete_procedure(args, jwt)
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
            if response.status_code == 400 and "already exists" in response.text:
                raise RuntimeError("upload_failed_after_delete_retry=already_exists")
        else:
            print("upload_skipped=already_exists")
            return
    response.raise_for_status()
    print("upload=ok")


def call(args: argparse.Namespace, jwt: str) -> dict:
    url = args.http.rstrip("/") + f"/db/{args.graph}/python_plugin/{args.procedure_name}"
    params = {
        "output_path": args.output_path,
        "id_map_path": args.id_map_path,
        "walk_length": args.walk_length,
        "num_walks": args.num_walks,
        "p": args.p,
        "q": args.q,
        "seed": args.seed,
        "max_start_nodes": args.max_start_nodes,
        "start_vid": args.start_vid,
        "return_preview_lines": 5,
    }
    payload = {"data": json.dumps(params), "timeout": args.timeout, "in_process": args.in_process}
    headers = auth_headers(jwt) | {"Content-Type": "application/json"}
    started = time.time()
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=args.timeout + 30)
    response.raise_for_status()
    elapsed = time.time() - started
    result = json.loads(response.json()["result"])
    print(json.dumps({"client_elapsed_seconds": elapsed, "procedure_result": result}, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    args = parse_args()
    jwt = login(args)
    if args.upload:
        upload(args, jwt)
    if args.call:
        call(args, jwt)
    if not args.upload and not args.call:
        print("Nothing to do. Use --upload and/or --call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
