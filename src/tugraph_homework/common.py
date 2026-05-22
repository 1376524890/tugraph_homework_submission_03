from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

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


def batched(items: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


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


def read_rows(path: Path, max_rows: int | None = None) -> Iterator[tuple[int, dict[str, str]]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        for row_number, row in enumerate(reader, start=1):
            yield row_number, row
            if max_rows is not None and row_number >= max_rows:
                break


def read_dict_csv(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        yield from reader


def write_dict_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
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


def upsert_vertices(session, label: str, rows: list[dict[str, Any]]) -> None:
    if rows:
        session.run("CALL db.upsertVertex($label, $rows)", label=label, rows=rows).consume()


def upsert_edges(
    session,
    label: str,
    src_label: str,
    src_key: str,
    dst_label: str,
    dst_key: str,
    rows: list[dict[str, Any]],
    pair_unique: str | None = None,
) -> None:
    if not rows:
        return
    query = (
        "CALL db.upsertEdge($label, "
        "{type:$src_label, key:$src_key}, "
        "{type:$dst_label, key:$dst_key}, "
        "$rows"
    )
    if pair_unique:
        query += ", $pair_unique"
    query += ")"
    params = {
        "label": label,
        "src_label": src_label,
        "src_key": src_key,
        "dst_label": dst_label,
        "dst_key": dst_key,
        "rows": rows,
    }
    if pair_unique:
        params["pair_unique"] = pair_unique
    session.run(query, **params).consume()
