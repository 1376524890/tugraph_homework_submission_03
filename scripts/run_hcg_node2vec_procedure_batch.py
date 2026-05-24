#!/usr/bin/env python3
"""Run HCG node2vec Python procedure in batches with ETA estimation."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import subprocess
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests
from requests import exceptions as requests_exceptions

from tugraph_homework.common import DEFAULT_PASSWORD, DEFAULT_USER, progress_bar


DEFAULT_HTTP = "http://127.0.0.1:7070"
DEFAULT_PROCEDURE = Path("procedures/hcg_node2vec_walk_py_batch.py")
DEFAULT_EDGE_CSV = Path("data/processed/hcg/communicates.csv")
DEFAULT_BATCH_SIZE = 1000
DEFAULT_MAX_BATCHES = 0
DEFAULT_TIMEOUT = 900
DEFAULT_PROCEDURE_TIME_BUDGET = 600


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HCG node2vec walks inside TuGraph via batched Python procedure.")
    parser.add_argument("--http", default=DEFAULT_HTTP)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--graph", default="hcg")
    parser.add_argument("--procedure-name", default="hcg_node2vec_walk_py_batch")
    parser.add_argument("--procedure-path", type=Path, default=DEFAULT_PROCEDURE)
    parser.add_argument("--upload", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--delete-first", action="store_true")
    parser.add_argument("--call", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--walk-length", type=int, default=20)
    parser.add_argument("--num-walks", type=int, default=5)
    parser.add_argument("--p", type=float, default=1.0)
    parser.add_argument("--q", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=20260524)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-batches", type=int, default=DEFAULT_MAX_BATCHES, help="Maximum batches to run. 0 means run until completion.")
    parser.add_argument("--start-offset", type=int, default=-1, help="Start offset. -1 means infer from existing output.")
    parser.add_argument("--max-start-nodes", type=int, default=0, help="Override batch size. 0 means use --batch-size.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--procedure-time-budget", type=float, default=DEFAULT_PROCEDURE_TIME_BUDGET, help="Server-side seconds budget per batch. 0 uses --timeout minus 30 seconds.")
    parser.add_argument("--delete-timeout", type=float, default=300)
    parser.add_argument("--health-check", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--kill-stale-runners", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--cleanup-after-batch", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--stale-runner-cpu-threshold", type=float, default=10.0)
    parser.add_argument("--progress", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--edge-csv", type=Path, default=DEFAULT_EDGE_CSV)
    parser.add_argument("--output-path", type=Path, default=Path("docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt"))
    parser.add_argument("--id-map-path", type=Path, default=Path("docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv"))
    return parser.parse_args()


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    lines = 0
    with path.open("rb") as fh:
        for _ in fh:
            lines += 1
    return lines


def infer_start_offset(args: argparse.Namespace) -> int:
    if args.start_offset >= 0:
        return args.start_offset
    walk_lines = count_lines(args.output_path)
    if walk_lines == 0:
        return 0
    if walk_lines % args.num_walks != 0:
        raise RuntimeError(
            f"cannot infer start offset: {args.output_path} has {walk_lines} lines, "
            f"not divisible by num_walks={args.num_walks}"
        )
    return walk_lines // args.num_walks


def append_batch_outputs(batch_walks: Path, batch_id_map: Path, final_walks: Path, final_id_map: Path) -> None:
    final_walks.parent.mkdir(parents=True, exist_ok=True)
    final_id_map.parent.mkdir(parents=True, exist_ok=True)
    if batch_walks.exists():
        with final_walks.open("a", encoding="utf-8") as out:
            out.write(batch_walks.read_text(encoding="utf-8"))

    tokens: set[str] = set()
    if final_id_map.exists():
        with final_id_map.open("r", encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                line = line.strip()
                if line:
                    tokens.add(line.split(",", 1)[0])
    if batch_id_map.exists():
        with batch_id_map.open("r", encoding="utf-8") as fh:
            next(fh, None)
            for line in fh:
                line = line.strip()
                if line:
                    tokens.add(line.split(",", 1)[0])
    with final_id_map.open("w", encoding="utf-8") as out:
        out.write("vid,token\n")
        for token in sorted(tokens, key=lambda s: int(s)):
            out.write(f'{token},"{token}"\n')


def list_task_runners() -> dict[str, dict[str, str | float]]:
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "tugraph-db",
                "sh",
                "-c",
                "ps -eo pid,ppid,stat,etime,pcpu,pmem,args | "
                "grep -E 'lgraph_task_runner|python3' | grep -v grep",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        raise RuntimeError(f"failed to list TuGraph task runners: {exc}") from exc

    runners: dict[str, dict[str, str | float]] = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 6)
        if len(parts) < 7 or "lgraph_task_runner.py" not in parts[6]:
            continue
        pid = parts[0]
        try:
            cpu = float(parts[4])
        except ValueError:
            cpu = 0.0
        runners[pid] = {
            "pid": pid,
            "ppid": parts[1],
            "stat": parts[2],
            "elapsed": parts[3],
            "cpu": cpu,
            "mem": parts[5],
            "cmd": parts[6],
        }
    return runners


def kill_task_runner_pids(pids: set[str]) -> None:
    if not pids:
        return
    pid_text = " ".join(sorted(pids, key=int))
    subprocess.run(
        [
            "docker",
            "exec",
            "tugraph-db",
            "sh",
            "-c",
            f"kill {pid_text} 2>/dev/null || true; sleep 1; kill -9 {pid_text} 2>/dev/null || true",
        ],
        check=False,
        timeout=15,
    )


def cleanup_stale_runners(log, kill: bool, cpu_threshold: float) -> None:
    try:
        runners = list_task_runners()
    except RuntimeError as exc:
        log(f"health_check=skipped reason={exc}")
        return

    stale_pids: set[str] = set()
    for runner in runners.values():
        log(
            "runner "
            f"pid={runner['pid']} ppid={runner['ppid']} stat={runner['stat']} "
            f"elapsed={runner['elapsed']} cpu={runner['cpu']} cmd={runner['cmd']}"
        )
        if float(runner["cpu"]) >= cpu_threshold:
            stale_pids.add(str(runner["pid"]))
            ppid = str(runner["ppid"])
            if ppid != "1":
                stale_pids.add(ppid)

    if kill and stale_pids:
        kill_task_runner_pids(stale_pids)
        log(f"stale_runners_killed={','.join(sorted(stale_pids, key=int))}")


def cleanup_new_runners(log, before_pids: set[str], kill: bool) -> None:
    try:
        after = list_task_runners()
    except RuntimeError as exc:
        log(f"post_batch_cleanup=skipped reason={exc}")
        return

    new_runners = {pid: runner for pid, runner in after.items() if pid not in before_pids}
    if not new_runners:
        log("post_batch_cleanup=no_new_runners")
        return

    kill_pids: set[str] = set()
    for runner in new_runners.values():
        log(
            "post_batch_runner "
            f"pid={runner['pid']} ppid={runner['ppid']} stat={runner['stat']} "
            f"elapsed={runner['elapsed']} cpu={runner['cpu']} cmd={runner['cmd']}"
        )
        kill_pids.add(str(runner["pid"]))
        ppid = str(runner["ppid"])
        if ppid != "1":
            kill_pids.add(ppid)

    if kill:
        kill_task_runner_pids(kill_pids)
        log(f"post_batch_runners_killed={','.join(sorted(kill_pids, key=int))}")


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


def upload(args: argparse.Namespace, jwt: str, log) -> None:
    url = args.http.rstrip("/") + f"/db/{args.graph}/python_plugin"
    if args.delete_first:
        delete_url = url + "/" + args.procedure_name
        try:
            response = requests.delete(delete_url, headers=auth_headers(jwt), timeout=args.delete_timeout)
            if response.status_code not in (200, 400, 404):
                response.raise_for_status()
        except requests_exceptions.Timeout:
            log(f"delete_timeout_after_seconds={args.delete_timeout}; continuing with upload")

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
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=300)
    if response.status_code == 400 and "already exists" in response.text:
        log("upload_skipped=already_exists")
        return
    response.raise_for_status()
    log("upload=ok")


def call_batch(
    args: argparse.Namespace,
    jwt: str,
    start_offset: int,
    batch_size: int,
    batch_index: int,
    host_out_dir: Path,
    container_out_dir: str,
) -> dict:
    url = args.http.rstrip("/") + f"/db/{args.graph}/python_plugin/{args.procedure_name}"
    batch_output = host_out_dir / f"walks_batch_{batch_index:05d}.txt"
    batch_id_map = host_out_dir / f"id_map_batch_{batch_index:05d}.csv"
    params = {
        "output_path": f"{container_out_dir}/walks_batch_{batch_index:05d}.txt",
        "id_map_path": f"{container_out_dir}/id_map_batch_{batch_index:05d}.csv",
        "walk_length": args.walk_length,
        "num_walks": args.num_walks,
        "p": args.p,
        "q": args.q,
        "seed": args.seed + batch_index,
        "max_start_nodes": batch_size,
        "start_offset": start_offset,
        "return_preview_lines": 0,
        "max_elapsed_seconds": max(1, args.procedure_time_budget or (args.timeout - 30)),
    }
    payload = {"data": json.dumps(params), "timeout": args.timeout, "in_process": args.in_process}
    headers = auth_headers(jwt) | {"Content-Type": "application/json"}
    started = time.time()
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=args.timeout + 30)
    except requests_exceptions.Timeout as exc:
        raise TimeoutError(
            f"batch {batch_index} client timeout after {args.timeout + 30}s; "
            "the server-side procedure should stop at max_elapsed_seconds"
        ) from exc
    response.raise_for_status()
    elapsed = time.time() - started
    result = json.loads(response.json()["result"])
    result["client_elapsed_seconds"] = elapsed
    result["host_output_path"] = str(batch_output)
    result["host_id_map_path"] = str(batch_id_map)
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

    # Setup logging
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"node2vec_batch_{timestamp}.log"
    log_fh = log_path.open("a", encoding="utf-8")

    def log(msg: str):
        log_fh.write(msg + "\n")
        log_fh.flush()

    log(f"--- Started at {datetime.now().isoformat()} ---")
    log(
        "recommended_config="
        + json.dumps(
            {
                "upload": args.upload,
                "delete_first": args.delete_first,
                "call": args.call,
                "batch_size": args.batch_size,
                "max_batches": args.max_batches,
                "timeout": args.timeout,
                "procedure_time_budget": args.procedure_time_budget,
                "health_check": args.health_check,
                "kill_stale_runners": args.kill_stale_runners,
                "cleanup_after_batch": args.cleanup_after_batch,
                "stale_runner_cpu_threshold": args.stale_runner_cpu_threshold,
                "progress": args.progress,
            },
            ensure_ascii=False,
        )
    )

    if args.health_check:
        cleanup_stale_runners(log, args.kill_stale_runners, args.stale_runner_cpu_threshold)

    jwt = login(args)
    if args.upload:
        upload(args, jwt, log)
    if not args.call:
        log("Nothing to do. Use --call to run batches.")
        return 0

    batch_size = args.max_start_nodes or args.batch_size
    args.start_offset = infer_start_offset(args)
    total_start_nodes = count_unique_sources(args.edge_csv)
    total_batches = math.ceil(max(0, total_start_nodes - args.start_offset) / batch_size) if batch_size else 0

    log(f"total_start_nodes={total_start_nodes}")
    log(f"batch_size={batch_size}")
    log(f"total_batches={total_batches}")
    log(f"start_offset={args.start_offset}")
    remaining_total = max(0, total_start_nodes - args.start_offset)
    run_total = remaining_total
    if args.max_batches > 0:
        run_total = min(run_total, args.max_batches * batch_size)

    tmp_parent = Path("docker/tugraph-tmp")
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hcg_node2vec_batches_", dir=tmp_parent) as tmp:
        parts_dir = Path(tmp)
        container_parts_dir = "/tmp/" + parts_dir.name
        cumulative_elapsed = 0.0
        completed_start_nodes = 0
        completed_batches = 0
        last_rate = None
        pbar = progress_bar("node2vec batches", unit="start_nodes", total=run_total) if args.progress else None

        try:
            while args.start_offset + completed_start_nodes < total_start_nodes:
                if args.max_batches > 0 and completed_batches >= args.max_batches:
                    log(f"stopped=max_batches_reached max_batches={args.max_batches}")
                    break
                batch_index = completed_batches
                current_start_offset = args.start_offset + completed_start_nodes
                t0 = time.time()
                before_runner_pids = set(list_task_runners()) if args.cleanup_after_batch else set()
                try:
                    result = call_batch(args, jwt, current_start_offset, batch_size, batch_index, parts_dir, container_parts_dir)
                except TimeoutError as exc:
                    log(f"stopped=client_timeout message={exc}")
                    break
                batch_elapsed = time.time() - t0
                cumulative_elapsed += batch_elapsed
                selected_start_count = int(result.get("start_node_count", 0))
                batch_start_count = int(result.get("completed_start_node_count", selected_start_count))
                batch_walk_count = int(result.get("walk_count", 0))
                if batch_start_count == 0:
                    log(f"stopped=no_completed_start_nodes result={json.dumps(result, ensure_ascii=False)}")
                    break
                append_batch_outputs(
                    Path(result["host_output_path"]),
                    Path(result["host_id_map_path"]),
                    args.output_path,
                    args.id_map_path,
                )
                if args.cleanup_after_batch:
                    cleanup_new_runners(log, before_runner_pids, args.kill_stale_runners)
                completed_start_nodes += batch_start_count
                completed_batches += 1
                if pbar is not None:
                    pbar.update(batch_start_count)
                    pbar.set_postfix(
                        batch=completed_batches,
                        offset=args.start_offset + completed_start_nodes,
                        walks=batch_walk_count,
                        refresh=True,
                    )
                batch_rate = (batch_walk_count / batch_elapsed) if batch_elapsed > 0 else 0.0
                if batch_rate > 0:
                    last_rate = batch_rate
                remaining_start_nodes = max(0, total_start_nodes - (args.start_offset + completed_start_nodes))
                eta_seconds = (remaining_start_nodes * args.num_walks / last_rate) if last_rate else None
                
                progress = {
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
                }
                log(json.dumps(progress, ensure_ascii=False, indent=2))
                if result.get("status") != "ok":
                    log(f"stopped=procedure_status status={result.get('status')}")
                    break
                if result.get("stopped_reason"):
                    log(f"stopped=procedure_budget reason={result.get('stopped_reason')}")
                    break
                
                if batch_start_count < batch_size:
                    break
        finally:
            if pbar is not None:
                pbar.close()

    if args.health_check:
        cleanup_stale_runners(log, args.kill_stale_runners, args.stale_runner_cpu_threshold)

    log(f"merged_walks={args.output_path}")
    log(f"merged_id_map={args.id_map_path}")
    log(f"--- Finished at {datetime.now().isoformat()} ---")
    log_fh.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
