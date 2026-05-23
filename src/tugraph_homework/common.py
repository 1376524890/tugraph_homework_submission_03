from __future__ import annotations

import csv
import itertools
import json
import os
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from tqdm.auto import tqdm
except ImportError:  # pragma: no cover - fallback for minimal environments.
    tqdm = None

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "data" / "raw" / "Dataset-Unicauca-Version2-87Atts.csv"
PROCESSED_ROOT = ROOT / "data" / "processed"
HCG_PROCESSED_DIR = PROCESSED_ROOT / "hcg"
TCG_PROCESSED_DIR = PROCESSED_ROOT / "tcg"


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()

DEFAULT_URI = os.getenv("TUGRAPH_URI", "bolt://localhost:7687")
DEFAULT_USER = os.getenv("TUGRAPH_USER", "")
DEFAULT_PASSWORD = os.getenv("TUGRAPH_PASSWORD", "")


def progress_iter(items: Iterable[Any], desc: str, unit: str = "it", total: int | None = None) -> Iterable[Any]:
    if tqdm is None:
        return items
    return tqdm(items, desc=desc, unit=unit, total=total, dynamic_ncols=True)


def progress_bar(desc: str, unit: str = "it", total: int | None = None):
    if tqdm is None:
        return None
    return tqdm(desc=desc, unit=unit, total=total, dynamic_ncols=True)


def parse_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value)) if value not in ("", None) else default
    except (TypeError, ValueError):
        return default


def parse_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value) if value not in ("", None) else default
    except (TypeError, ValueError):
        return default


def parse_timestamp(value: str) -> tuple[str, int]:
    if not value:
        return "", 0
    for fmt in ("%d/%m/%Y%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.isoformat(sep=" "), int(dt.timestamp())
        except ValueError:
            continue
    return value, 0


def endpoint_id(ip: str, port: str) -> str:
    return f"{ip}:{port}"


def read_rows(path: Path, max_rows: int | None = None, progress_desc: str | None = None) -> Iterator[tuple[int, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        input_rows = itertools.islice(reader, max_rows) if max_rows is not None else reader
        rows = progress_iter(input_rows, progress_desc, "rows", max_rows) if progress_desc else input_rows
        for row_number, row in enumerate(rows, start=1):
            yield row_number, row


def write_dict_csv(
    path: Path,
    fieldnames: list[str],
    rows: Iterable[dict[str, Any]],
    progress_desc: str | None = None,
    total: int | None = None,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        output_rows = progress_iter(rows, progress_desc, "rows", total) if progress_desc else rows
        for row in output_rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
            count += 1
    return count


def safe_call(session, query: str, **params: Any) -> None:
    try:
        list(session.run(query, **params))
    except Exception as exc:
        if not exc.__class__.__module__.startswith("neo4j"):
            raise
        message = str(exc).lower()
        if "already" in message or "exist" in message or "same name" in message:
            return
        raise


def ensure_graph(uri: str, user: str, password: str, graph: str) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database="default") as session:
            rows = [dict(row) for row in session.run("CALL dbms.graph.listGraphs()")]
            if graph not in {row.get("graph_name") for row in rows}:
                session.run("CALL dbms.graph.createGraph($graph)", graph=graph).consume()
    finally:
        driver.close()


def run_schema(uri: str, user: str, password: str, graph: str, schemas: list[dict[str, Any]]) -> None:
    ensure_graph(uri, user, password, graph)
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=graph) as session:
            for schema in schemas:
                payload = json.dumps(schema, ensure_ascii=False)
                if schema["type"] == "VERTEX":
                    safe_call(session, "CALL db.createVertexLabelByJson($json_data)", json_data=payload)
                else:
                    safe_call(session, "CALL db.createEdgeLabelByJson($json_data)", json_data=payload)
    finally:
        driver.close()
