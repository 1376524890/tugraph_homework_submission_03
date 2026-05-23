#!/usr/bin/env python3
"""Create TuGraph graphs through Bolt and import CSV through lgraph_import."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from create_tugraph_import_config import hcg_config, tcg_config  # noqa: E402
from tugraph_homework.common import DEFAULT_PASSWORD, DEFAULT_URI, DEFAULT_USER, ROOT, ensure_graph, schema_exists  # noqa: E402


GRAPH_TYPES = ("hcg", "tcg")
DEFAULT_GRAPHS = {"hcg": "hcg", "tcg": "tcg"}
PRIMARY_LABELS = {"hcg": "Endpoint", "tcg": "Flow"}


def display_command(command: list[str]) -> str:
    clean = list(command)
    for index, value in enumerate(clean[:-1]):
        if value == "--password":
            clean[index + 1] = "***"
    return shlex.join(clean)


def run_command(command: list[str], dry_run: bool) -> None:
    print("$ " + display_command(command), flush=True)
    if dry_run:
        return

    if tqdm is None or command[0] != "docker" or "lgraph_import" not in command:
        subprocess.run(command, check=True)
        return

    # 尝试使用 tqdm 实时显示进度
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )

    pbar = None
    last_phase = ""
    # 匹配模式，例如 "[1/2] Importing vertex... 50%" 或类似的输出
    percent_re = re.compile(r"(\d+)%")
    phase_re = re.compile(r"\[(\d+/\d+)\]\s+(.*?)\.\.\.")

    try:
        for line in process.stdout:
            print(line, end="", flush=True)
            
            # 检测阶段切换
            phase_match = phase_re.search(line)
            if phase_match:
                current_phase = f"{phase_match.group(1)} {phase_match.group(2)}"
                if current_phase != last_phase:
                    if pbar:
                        pbar.n = 100
                        pbar.refresh()
                        pbar.close()
                    pbar = tqdm(total=100, desc=current_phase, unit="%")
                    last_phase = current_phase
            
            # 检测百分比并更新进度条
            if pbar:
                percent_match = percent_re.search(line)
                if percent_match:
                    pbar.n = int(percent_match.group(1))
                    pbar.refresh()
        
        if pbar:
            pbar.n = 100
            pbar.refresh()
            pbar.close()
            
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, command)
    except KeyboardInterrupt:
        process.terminate()
        if pbar:
            pbar.close()
        raise


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def format_gib(size: int) -> str:
    return f"{size / 1024**3:.1f}GiB"


def container_running(name: str) -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def compose_command(args: argparse.Namespace, action: str) -> list[str]:
    command = ["docker", "compose"]
    if args.compose_env_file.exists():
        command.extend(["--env-file", str(args.compose_env_file)])
    command.extend(["-f", str(args.compose_file), action, args.compose_service])
    return command


def service_running(args: argparse.Namespace) -> bool:
    if args.compose_file.exists():
        result = subprocess.run(
            compose_command(args, "ps") + ["--status", "running", "--format", "{{.Name}}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return args.container_name in {line.strip() for line in result.stdout.splitlines()}
    return container_running(args.container_name)


def stop_service(args: argparse.Namespace, dry_run: bool) -> None:
    if args.compose_file.exists():
        run_command(compose_command(args, "stop"), dry_run)
    else:
        run_command(["docker", "stop", args.container_name], dry_run)


def start_service(args: argparse.Namespace, dry_run: bool) -> None:
    if args.compose_file.exists():
        run_command(compose_command(args, "start"), dry_run)
    else:
        run_command(["docker", "start", args.container_name], dry_run)


def generate_config(args: argparse.Namespace, graph_type: str) -> Path:
    processed_dir = args.import_root / graph_type
    output_path = processed_dir / "import.json"
    if graph_type == "hcg":
        config = hcg_config(processed_dir, args.import_root, args.container_import_root, args.keep_indexes)
    else:
        config = tcg_config(processed_dir, args.import_root, args.container_import_root, args.keep_indexes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    import json

    output_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"import_config={output_path} files={len(config['files'])}", flush=True)
    return output_path


def docker_import_command(args: argparse.Namespace, graph_type: str, graph: str, config_path: Path) -> list[str]:
    container_config = str(Path(args.container_import_root) / graph_type / config_path.name)
    command = [
        "docker",
        "run",
        "--rm",
        "--workdir",
        "/tmp",
        "--ulimit",
        f"nofile={args.nofile_limit}",
        "-v",
        f"{args.data_dir.resolve()}:{args.container_data_dir}",
        "-v",
        f"{args.import_root.resolve()}:{args.container_import_root}",
        "-v",
        f"{args.tmp_dir.resolve()}:/tmp",
        args.image,
        "lgraph_import",
        "--dir",
        args.container_data_dir,
        "--config_file",
        container_config,
        "--graph",
        graph,
        "--user",
        args.user,
        "--password",
        args.password,
        "--overwrite",
        "true",
    ]
    command.extend(
        [
            "--parse_file_threads",
            str(args.parse_file_threads),
            "--parse_block_threads",
            str(args.parse_block_threads),
            "--generate_sst_threads",
            str(args.generate_sst_threads),
            "--read_rocksdb_threads",
            str(args.read_rocksdb_threads),
        ]
    )
    return command


def clean_import_tmp(args: argparse.Namespace) -> None:
    import_tmp = args.tmp_dir / ".import_tmp"
    if not import_tmp.exists():
        return
    tmp_root = args.tmp_dir.resolve()
    resolved = import_tmp.resolve()
    if tmp_root not in resolved.parents:
        raise SystemExit(f"Refusing to remove unexpected import temp path: {resolved}")
    size = path_size(import_tmp)
    if args.dry_run:
        print(f"would_remove_import_tmp path={import_tmp} size={format_gib(size)}", flush=True)
        return
    print(f"remove_import_tmp path={import_tmp} size={format_gib(size)}", flush=True)
    shutil.rmtree(import_tmp)


def preflight_graph_import(args: argparse.Namespace, graph_type: str) -> None:
    input_dir = args.import_root / graph_type
    input_size = path_size(input_dir)
    free_bytes = shutil.disk_usage(args.tmp_dir).free
    reclaimable_bytes = 0
    if args.dry_run and args.clean_tmp:
        reclaimable_bytes = path_size(args.tmp_dir / ".import_tmp")
        free_bytes += reclaimable_bytes
    required_bytes = int(input_size * args.min_free_multiplier)
    print(
        "preflight "
        f"graph_type={graph_type} input_size={format_gib(input_size)} "
        f"tmp_free_after_clean={format_gib(free_bytes)} "
        f"reclaimable_tmp={format_gib(reclaimable_bytes)} "
        f"min_required={format_gib(required_bytes)} "
        f"nofile={args.nofile_limit} "
        f"threads=parse_file:{args.parse_file_threads},parse_block:{args.parse_block_threads},"
        f"generate_sst:{args.generate_sst_threads},read_rocksdb:{args.read_rocksdb_threads}",
        flush=True,
    )
    if args.skip_preflight:
        return
    if free_bytes < required_bytes:
        raise SystemExit(
            f"Not enough free space for stable {graph_type} import: tmp/data filesystem has "
            f"{format_gib(free_bytes)} free, require at least {format_gib(required_bytes)} "
            f"({args.min_free_multiplier:g}x input size). Free disk space or pass --skip-preflight."
        )


def import_graphs(args: argparse.Namespace) -> None:
    graph_types = list(GRAPH_TYPES) if args.graph_type == "all" else [args.graph_type]
    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.import_root.mkdir(parents=True, exist_ok=True)
    args.tmp_dir.mkdir(parents=True, exist_ok=True)

    graph_names = {graph_type: args.graph or DEFAULT_GRAPHS[graph_type] for graph_type in graph_types}
    config_paths = {graph_type: generate_config(args, graph_type) for graph_type in graph_types}

    if args.clean_tmp:
        clean_import_tmp(args)
    for graph_type in graph_types:
        preflight_graph_import(args, graph_type)

    for graph_type, graph in graph_names.items():
        if args.dry_run:
            print(f"would_create_graph_with_bolt graph={graph} graph_type={graph_type}", flush=True)
            continue
        ensure_graph(args.uri, args.user, args.password, graph)
        if schema_exists(args.uri, args.user, args.password, graph, PRIMARY_LABELS[graph_type]) and not args.force:
            raise SystemExit(
                f"Graph {graph!r} already has label {PRIMARY_LABELS[graph_type]!r}. "
                "Refusing to import over an existing graph without --force."
            )
        print(f"graph_created_or_exists graph={graph} graph_type={graph_type}", flush=True)

    was_running = service_running(args)
    if was_running:
        stop_service(args, args.dry_run)

    try:
        for graph_type in graph_types:
            command = docker_import_command(args, graph_type, graph_names[graph_type], config_paths[graph_type])
            run_command(command, args.dry_run)
    finally:
        if was_running or args.start_after:
            start_service(args, args.dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create TuGraph graph with Bolt, then import CSV using TuGraph native lgraph_import in Docker."
    )
    parser.add_argument("--graph-type", choices=["hcg", "tcg", "all"], required=True)
    parser.add_argument("--graph", default=None, help="Override graph name. Only valid when importing one graph type.")
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--container-name", default="tugraph-db")
    parser.add_argument("--image", default=os.getenv("TUGRAPH_IMAGE", "custom-tugraph-runtime:latest"))
    parser.add_argument("--data-dir", type=Path, default=ROOT / "docker" / "tugraph-data")
    parser.add_argument("--import-root", type=Path, default=ROOT / "docker" / "tugraph-import")
    parser.add_argument("--tmp-dir", type=Path, default=ROOT / "docker" / "tugraph-tmp")
    parser.add_argument("--container-data-dir", default="/var/lib/lgraph/data")
    parser.add_argument("--container-import-root", default="/import")
    parser.add_argument(
        "--nofile-limit",
        default=os.getenv("TUGRAPH_IMPORT_NOFILE", "1048576:1048576"),
        help="Docker nofile ulimit for the temporary lgraph_import container, formatted as soft:hard.",
    )
    parser.add_argument("--parse-file-threads", type=int, default=1)
    parser.add_argument("--parse-block-threads", type=int, default=1)
    parser.add_argument("--generate-sst_threads", type=int, default=4)
    parser.add_argument("--read-rocksdb-threads", type=int, default=4)
    parser.add_argument(
        "--min-free-multiplier",
        type=float,
        default=float(os.getenv("TUGRAPH_IMPORT_MIN_FREE_MULTIPLIER", "3.0")),
        help="Require this multiple of the graph import input size as free space before import.",
    )
    parser.add_argument("--skip-preflight", action="store_true", help="Skip free-space preflight checks.")
    parser.add_argument(
        "--no-clean-tmp",
        dest="clean_tmp",
        action="store_false",
        help="Do not remove docker/tugraph-tmp/.import_tmp before importing.",
    )
    parser.set_defaults(clean_tmp=True)
    parser.add_argument("--compose-file", type=Path, default=ROOT.parent / "docker-compose.yml")
    parser.add_argument("--compose-env-file", type=Path, default=ROOT.parent / ".env")
    parser.add_argument("--compose-service", default="tugraph-db")
    parser.add_argument("--keep-indexes", action="store_true", help="Keep secondary indexes in the import schema.")
    parser.add_argument("--force", action="store_true", help="Allow importing when the target graph already has data labels.")
    parser.add_argument("--start-after", action="store_true", help="Start the service container after import even if it was not running.")
    parser.add_argument("--dry-run", action="store_true", help="Print docker commands without stopping containers or importing.")
    args = parser.parse_args()

    if args.graph_type == "all" and args.graph:
        parser.error("--graph can only be used with --graph-type hcg or --graph-type tcg")
    if not args.user or not args.password:
        parser.error("TuGraph credentials are required. Set TUGRAPH_USER/TUGRAPH_PASSWORD in .env or pass --user/--password.")

    import_graphs(args)


if __name__ == "__main__":
    main()
