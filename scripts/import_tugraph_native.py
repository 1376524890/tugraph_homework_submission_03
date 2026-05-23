#!/usr/bin/env python3
"""Create TuGraph graphs through Bolt and import CSV through lgraph_import."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

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
    if not dry_run:
        subprocess.run(command, check=True)


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
    return [
        "docker",
        "run",
        "--rm",
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


def import_graphs(args: argparse.Namespace) -> None:
    graph_types = list(GRAPH_TYPES) if args.graph_type == "all" else [args.graph_type]
    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.import_root.mkdir(parents=True, exist_ok=True)
    args.tmp_dir.mkdir(parents=True, exist_ok=True)

    graph_names = {graph_type: args.graph or DEFAULT_GRAPHS[graph_type] for graph_type in graph_types}
    config_paths = {graph_type: generate_config(args, graph_type) for graph_type in graph_types}

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
