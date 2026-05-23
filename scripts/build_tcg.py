#!/usr/bin/env python3
"""构建或估算 TCG。

本脚本支持 estimate 模式估算 CR/PR/DHR/SHR 边数量，也支持 build 模式按
relation_type 分区写出 causes_full_parts。默认关系窗口为 CR=5,PR=1,DHR=1,SHR=5。
"""

from __future__ import annotations

import argparse
import bisect
import csv
import itertools
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import DEFAULT_DATASET, progress_iter, read_rows, write_dict_csv  # noqa: E402
from tugraph_homework.transform import (  # noqa: E402
    RELATION_PRIORITIES,
    TCG_EDGE_FIELDS,
    TCG_FLOW_FIELDS,
    classify_relation,
    flow_vertex,
    tcg_edge,
)


DEFAULT_MAX_DELTA_SECONDS = 60
DEFAULT_RELATION_WINDOW_TEXT = "CR=5,PR=1,DHR=1,SHR=5"
DEFAULT_MAX_CANDIDATE_EDGES = 5_000_000


def parse_relation_types(value: str) -> list[str]:
    relation_types = [item.strip().upper() for item in value.split(",") if item.strip()]
    invalid = [item for item in relation_types if item not in RELATION_PRIORITIES]
    if invalid:
        raise argparse.ArgumentTypeError(f"Unsupported relation types: {','.join(invalid)}")
    return sorted(set(relation_types), key=lambda item: RELATION_PRIORITIES[item])


def parse_relation_windows(value: str) -> dict[str, int | None]:
    windows: dict[str, int | None] = {}
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "=" not in item:
            raise argparse.ArgumentTypeError("Relation windows must use RELATION=SECONDS, for example PR=1,DHR=1")
        relation_type, seconds_text = item.split("=", 1)
        relation_type = relation_type.strip().upper()
        if relation_type not in RELATION_PRIORITIES:
            raise argparse.ArgumentTypeError(f"Unsupported relation type in relation windows: {relation_type}")
        try:
            seconds = int(seconds_text.strip())
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"Invalid window seconds for {relation_type}: {seconds_text}") from exc
        windows[relation_type] = normalize_window(seconds)
    return windows


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit("Parquet support requires pandas and pyarrow. Install them or use --output-format csv.") from exc
    return pd


def load_flows(input_path: Path, max_rows: int | None = None) -> list[dict[str, Any]]:
    if input_path.suffix.lower() == ".parquet":
        pd = require_pandas()
        frame = pd.read_parquet(input_path)
        if max_rows is not None:
            frame = frame.head(max_rows)
        return frame.to_dict(orient="records")
    return [flow_vertex(row_number, row) for row_number, row in read_rows(input_path, max_rows=max_rows, progress_desc="load flows")]


def write_flows(flows: list[dict[str, Any]], output_dir: Path, output_format: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_format == "parquet":
        pd = require_pandas()
        path = output_dir / "flows.parquet"
        tmp_path = output_dir / "flows.parquet.tmp"
        pd.DataFrame(flows, columns=TCG_FLOW_FIELDS).to_parquet(tmp_path, index=False)
        os.replace(tmp_path, path)
        return path
    path = output_dir / "flows.csv"
    tmp_path = output_dir / "flows.csv.tmp"
    write_dict_csv(tmp_path, TCG_FLOW_FIELDS, flows, progress_desc="write flows", total=len(flows))
    os.replace(tmp_path, path)
    return path


def n_choose_2(n: int) -> int:
    return n * (n - 1) // 2


def normalize_window(value: int) -> int | None:
    if value < 0:
        raise argparse.ArgumentTypeError("--max-delta-seconds must be >= 0")
    return value or None


def relation_windows(default_window: int | None, overrides: dict[str, int | None] | None = None) -> dict[str, int | None]:
    windows = {relation_type: default_window for relation_type in RELATION_PRIORITIES}
    if overrides:
        windows.update(overrides)
    return windows


def format_relation_windows(windows: dict[str, int | None]) -> str:
    return ",".join(f"{relation_type}={windows[relation_type] if windows[relation_type] is not None else 0}" for relation_type in sorted(windows, key=RELATION_PRIORITIES.get))


def count_timestamp_pairs(left_values: list[int], right_values: list[int], max_delta_seconds: int | None, same_group: bool = False) -> int:
    if not left_values or not right_values:
        return 0
    left_sorted = sorted(left_values)
    right_sorted = left_sorted if same_group else sorted(right_values)
    if max_delta_seconds is None:
        return n_choose_2(len(left_sorted)) if same_group else len(left_sorted) * len(right_sorted)

    count = 0
    if same_group:
        right_index = 0
        for left_index, timestamp in enumerate(left_sorted):
            right_index = max(right_index, left_index + 1)
            while right_index < len(left_sorted) and left_sorted[right_index] - timestamp <= max_delta_seconds:
                right_index += 1
            count += right_index - left_index - 1
        return count

    for timestamp in left_sorted:
        lower = bisect.bisect_left(right_sorted, timestamp - max_delta_seconds)
        upper = bisect.bisect_right(right_sorted, timestamp + max_delta_seconds)
        count += upper - lower
    return count


def estimate_edges(
    flows: list[dict[str, Any]],
    max_delta_seconds: int | None = DEFAULT_MAX_DELTA_SECONDS,
    relation_window_overrides: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    # 估算只做分组计数，不枚举实际边；用于全量构图前判断 PR/DHR/SHR 是否会爆炸。
    five_tuple_timestamps: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    src_ip_timestamps: dict[str, list[int]] = defaultdict(list)
    dst_ip_timestamps: dict[str, list[int]] = defaultdict(list)
    src_ip_port_timestamps: dict[tuple[str, int], list[int]] = defaultdict(list)
    src_ip_to_port_timestamps: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))

    for flow in progress_iter(flows, "estimate edge groups", "flows", len(flows)):
        timestamp = int(flow.get("timestamp_epoch", 0))
        five_tuple_timestamps[(flow["protocol"], flow["src_ip"], flow["src_port"], flow["dst_ip"], flow["dst_port"])].append(timestamp)
        src_ip_timestamps[flow["src_ip"]].append(timestamp)
        dst_ip_timestamps[flow["dst_ip"]].append(timestamp)
        src_ip_port_timestamps[(flow["src_ip"], flow["src_port"])].append(timestamp)
        src_ip_to_port_timestamps[flow["src_ip"]][flow["src_port"]].append(timestamp)

    windows = relation_windows(max_delta_seconds, relation_window_overrides)
    cr_pairs = 0
    seen_cr_keys: set[tuple[Any, ...]] = set()
    for key, timestamps in five_tuple_timestamps.items():
        # CR 通过五元组和反向五元组相乘估算，seen_cr_keys 避免正反方向重复计数。
        reverse_key = (key[0], key[3], key[4], key[1], key[2])
        if key in seen_cr_keys:
            continue
        if key == reverse_key:
            cr_pairs += count_timestamp_pairs(timestamps, timestamps, windows["CR"], same_group=True)
        else:
            cr_pairs += count_timestamp_pairs(timestamps, five_tuple_timestamps.get(reverse_key, []), windows["CR"])
        seen_cr_keys.add(key)
        seen_cr_keys.add(reverse_key)

    # PR 估算：同一 IP 作为前序 dst 和后续 src 的笛卡尔积。
    pr_pairs = sum(count_timestamp_pairs(dst_ip_timestamps[ip], src_ip_timestamps[ip], windows["PR"]) for ip in set(dst_ip_timestamps) | set(src_ip_timestamps))
    dhr_pairs = 0
    for ports in src_ip_to_port_timestamps.values():
        all_timestamps = [timestamp for values in ports.values() for timestamp in values]
        same_port_pairs = sum(count_timestamp_pairs(values, values, windows["DHR"], same_group=True) for values in ports.values())
        # DHR 是同一 src_ip 下不同 src_port 的组合，所以要扣掉同端口组合。
        dhr_pairs += count_timestamp_pairs(all_timestamps, all_timestamps, windows["DHR"], same_group=True) - same_port_pairs
    shr_pairs = sum(count_timestamp_pairs(values, values, windows["SHR"], same_group=True) for values in src_ip_port_timestamps.values())
    total_pairs = cr_pairs + pr_pairs + dhr_pairs + shr_pairs
    return {
        "flow_count": len(flows),
        "max_delta_seconds": max_delta_seconds,
        "relation_windows": windows,
        "CR": cr_pairs,
        "PR": pr_pairs,
        "DHR": dhr_pairs,
        "SHR": shr_pairs,
        "total": total_pairs,
        "estimated_parquet_size": int(total_pairs * 180 * 0.35),
        "estimated_csv_size": int(total_pairs * 180),
        "top_groups": top_risk_groups(src_ip_timestamps, dst_ip_timestamps, src_ip_to_port_timestamps, src_ip_port_timestamps, windows),
    }


def estimate_edges_from_path(
    input_path: Path,
    max_rows: int | None = None,
    max_delta_seconds: int | None = DEFAULT_MAX_DELTA_SECONDS,
    relation_window_overrides: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    if input_path.suffix.lower() == ".parquet":
        return estimate_edges(load_flows(input_path, max_rows), max_delta_seconds, relation_window_overrides)

    five_tuple_timestamps: dict[tuple[Any, ...], list[int]] = defaultdict(list)
    src_ip_timestamps: dict[str, list[int]] = defaultdict(list)
    dst_ip_timestamps: dict[str, list[int]] = defaultdict(list)
    src_ip_port_timestamps: dict[tuple[str, int], list[int]] = defaultdict(list)
    src_ip_to_port_timestamps: dict[str, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    flow_count = 0

    for row_number, row in read_rows(input_path, max_rows=max_rows, progress_desc="estimate edge groups"):
        flow = flow_vertex(row_number, row)
        flow_count += 1
        timestamp = int(flow.get("timestamp_epoch", 0))
        five_tuple_timestamps[(flow["protocol"], flow["src_ip"], flow["src_port"], flow["dst_ip"], flow["dst_port"])].append(timestamp)
        src_ip_timestamps[flow["src_ip"]].append(timestamp)
        dst_ip_timestamps[flow["dst_ip"]].append(timestamp)
        src_ip_port_timestamps[(flow["src_ip"], flow["src_port"])].append(timestamp)
        src_ip_to_port_timestamps[flow["src_ip"]][flow["src_port"]].append(timestamp)

    windows = relation_windows(max_delta_seconds, relation_window_overrides)
    cr_pairs = 0
    seen_cr_keys: set[tuple[Any, ...]] = set()
    for key, timestamps in five_tuple_timestamps.items():
        reverse_key = (key[0], key[3], key[4], key[1], key[2])
        if key in seen_cr_keys:
            continue
        if key == reverse_key:
            cr_pairs += count_timestamp_pairs(timestamps, timestamps, windows["CR"], same_group=True)
        else:
            cr_pairs += count_timestamp_pairs(timestamps, five_tuple_timestamps.get(reverse_key, []), windows["CR"])
        seen_cr_keys.add(key)
        seen_cr_keys.add(reverse_key)

    pr_pairs = sum(count_timestamp_pairs(dst_ip_timestamps[ip], src_ip_timestamps[ip], windows["PR"]) for ip in set(dst_ip_timestamps) | set(src_ip_timestamps))
    dhr_pairs = 0
    for ports in src_ip_to_port_timestamps.values():
        all_timestamps = [timestamp for values in ports.values() for timestamp in values]
        same_port_pairs = sum(count_timestamp_pairs(values, values, windows["DHR"], same_group=True) for values in ports.values())
        dhr_pairs += count_timestamp_pairs(all_timestamps, all_timestamps, windows["DHR"], same_group=True) - same_port_pairs
    shr_pairs = sum(count_timestamp_pairs(values, values, windows["SHR"], same_group=True) for values in src_ip_port_timestamps.values())
    total_pairs = cr_pairs + pr_pairs + dhr_pairs + shr_pairs
    return {
        "flow_count": flow_count,
        "max_delta_seconds": max_delta_seconds,
        "relation_windows": windows,
        "CR": cr_pairs,
        "PR": pr_pairs,
        "DHR": dhr_pairs,
        "SHR": shr_pairs,
        "total": total_pairs,
        "estimated_parquet_size": int(total_pairs * 180 * 0.35),
        "estimated_csv_size": int(total_pairs * 180),
        "top_groups": top_risk_groups(src_ip_timestamps, dst_ip_timestamps, src_ip_to_port_timestamps, src_ip_port_timestamps, windows),
    }


def top_risk_groups(
    src_ip_timestamps: dict[str, list[int]],
    dst_ip_timestamps: dict[str, list[int]],
    src_ip_to_port_timestamps: dict[str, dict[int, list[int]]],
    src_ip_port_timestamps: dict[tuple[str, int], list[int]],
    windows: dict[str, int | None],
) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for ip in set(src_ip_timestamps) | set(dst_ip_timestamps):
        rows.append(("PR", ip, count_timestamp_pairs(dst_ip_timestamps[ip], src_ip_timestamps[ip], windows["PR"])))
    for ip, ports in src_ip_to_port_timestamps.items():
        all_timestamps = [timestamp for values in ports.values() for timestamp in values]
        same = sum(count_timestamp_pairs(values, values, windows["DHR"], same_group=True) for values in ports.values())
        rows.append(("DHR", ip, count_timestamp_pairs(all_timestamps, all_timestamps, windows["DHR"], same_group=True) - same))
    for (ip, port), timestamps in src_ip_port_timestamps.items():
        rows.append(("SHR", f"{ip}:{port}", count_timestamp_pairs(timestamps, timestamps, windows["SHR"], same_group=True)))
    return sorted(rows, key=lambda item: item[2], reverse=True)[:20]


def write_estimation_report(estimate: dict[str, Any], output_dir: Path) -> Path:
    report_dir = output_dir.parent / "reports" if output_dir.name == "tcg" else output_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "tcg_edge_estimation_report.md"
    lines = [
        "# TCG Edge Estimation Report",
        "",
        "This report estimates CR/PR/DHR/SHR candidate edges before full TCG construction.",
        "Construction uses CR/PR/DHR/SHR relation rules.",
        "",
        f"- Flow count: {estimate['flow_count']:,}",
        f"- max_delta_seconds: {estimate['max_delta_seconds'] if estimate['max_delta_seconds'] is not None else 'not applied'}",
        f"- relation_windows: {format_relation_windows(estimate['relation_windows'])}",
        f"- CR candidate edges: {estimate['CR']:,}",
        f"- PR candidate edges: {estimate['PR']:,}",
        f"- DHR candidate edges: {estimate['DHR']:,}",
        f"- SHR candidate edges: {estimate['SHR']:,}",
        f"- Total candidate edges: {estimate['total']:,}",
        f"- Estimated Parquet size: {estimate['estimated_parquet_size'] / (1024 ** 3):.2f} GiB",
        f"- Estimated CSV size: {estimate['estimated_csv_size'] / (1024 ** 3):.2f} GiB",
        "",
        "## Top 20 High-Risk Groups",
        "",
        "| relation_type | group | estimated_edges |",
        "| --- | --- | ---: |",
    ]
    for relation_type, group, count in estimate["top_groups"]:
        lines.append(f"| {relation_type} | `{group}` | {count:,} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def pair_flows(items: list[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    yield from itertools.combinations(items, 2)


def timestamp_pair_flows(
    left_items: list[dict[str, Any]],
    right_items: list[dict[str, Any]],
    max_delta_seconds: int | None,
    same_group: bool = False,
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    if max_delta_seconds is None:
        if same_group:
            yield from pair_flows(left_items)
        else:
            yield from itertools.product(left_items, right_items)
        return

    left_sorted = sorted(left_items, key=lambda flow: int(flow.get("timestamp_epoch", 0)))
    if same_group:
        right_index = 0
        for left_index, left in enumerate(left_sorted):
            left_ts = int(left.get("timestamp_epoch", 0))
            right_index = max(right_index, left_index + 1)
            while right_index < len(left_sorted) and int(left_sorted[right_index].get("timestamp_epoch", 0)) - left_ts <= max_delta_seconds:
                right_index += 1
            for candidate_index in range(left_index + 1, right_index):
                yield left, left_sorted[candidate_index]
        return

    right_sorted = sorted(right_items, key=lambda flow: int(flow.get("timestamp_epoch", 0)))
    right_timestamps = [int(flow.get("timestamp_epoch", 0)) for flow in right_sorted]
    for left in left_sorted:
        left_ts = int(left.get("timestamp_epoch", 0))
        lower = bisect.bisect_left(right_timestamps, left_ts - max_delta_seconds)
        upper = bisect.bisect_right(right_timestamps, left_ts + max_delta_seconds)
        for candidate_index in range(lower, upper):
            yield left, right_sorted[candidate_index]


def relation_pairs(flows: list[dict[str, Any]], relation_type: str, max_delta_seconds: int | None) -> Iterator[tuple[dict[str, Any], dict[str, Any], str, str, str]]:
    if relation_type == "CR":
        # CR 用五元组分桶，只在反向五元组桶之间枚举，避免全表两两比较。
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for flow in flows:
            key = (flow["protocol"], flow["src_ip"], flow["src_port"], flow["dst_ip"], flow["dst_port"])
            groups[key].append(flow)
        seen_keys: set[tuple[Any, ...]] = set()
        for key, left_group in groups.items():
            if key in seen_keys:
                continue
            reverse_key = (key[0], key[3], key[4], key[1], key[2])
            right_group = groups.get(reverse_key, [])
            if key == reverse_key:
                iterable = timestamp_pair_flows(left_group, left_group, max_delta_seconds, same_group=True)
            else:
                iterable = timestamp_pair_flows(left_group, right_group, max_delta_seconds)
            for left, right in iterable:
                relation = classify_relation(left, right)
                if relation and relation[0] == "CR":
                    yield left, right, relation[1], relation[2], relation[3]
            seen_keys.add(key)
            seen_keys.add(reverse_key)
        return

    if relation_type == "PR":
        # PR 只在 dst_ip == src_ip 的两个桶之间枚举，并按时间窗口裁剪。
        by_dst_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_src_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for flow in flows:
            by_dst_ip[flow["dst_ip"]].append(flow)
            by_src_ip[flow["src_ip"]].append(flow)
        for ip in set(by_dst_ip) & set(by_src_ip):
            for left, right in timestamp_pair_flows(by_dst_ip[ip], by_src_ip[ip], max_delta_seconds):
                relation = classify_relation(left, right)
                if relation and relation[0] == "PR":
                    yield left, right, relation[1], relation[2], relation[3]
        return

    if relation_type == "DHR":
        # DHR 在同一 src_ip 内跨不同 src_port 枚举，并按时间窗口裁剪。
        by_src_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for flow in flows:
            by_src_ip[flow["src_ip"]].append(flow)
        for group in by_src_ip.values():
            for left, right in timestamp_pair_flows(group, group, max_delta_seconds, same_group=True):
                if left["src_port"] == right["src_port"]:
                    continue
                relation = classify_relation(left, right)
                if relation and relation[0] == "DHR":
                    yield left, right, relation[1], relation[2], relation[3]
        return

    # SHR 在同一 (src_ip, src_port) 桶内两两配对。
    by_src_ip_port: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for flow in flows:
        by_src_ip_port[(flow["src_ip"], flow["src_port"])].append(flow)
    for group in by_src_ip_port.values():
        for left, right in timestamp_pair_flows(group, group, max_delta_seconds, same_group=True):
            relation = classify_relation(left, right)
            if relation and relation[0] == "SHR":
                yield left, right, relation[1], relation[2], relation[3]


class PartitionWriter:
    def __init__(self, output_dir: Path, output_format: str, chunk_size: int) -> None:
        self.output_dir = output_dir
        self.output_format = output_format
        self.chunk_size = chunk_size
        self.buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.part_numbers: Counter[str] = Counter()
        self.counts: Counter[str] = Counter()
        self.pd = require_pandas() if output_format == "parquet" else None

    def write(self, row: dict[str, Any]) -> None:
        relation_type = row["relation_type"]
        buffer = self.buffers[relation_type]
        buffer.append(row)
        if len(buffer) >= self.chunk_size:
            self.flush(relation_type)

    def flush(self, relation_type: str) -> None:
        rows = self.buffers[relation_type]
        if not rows:
            return
        # 分区目录与老师要求一致：causes_full_parts/relation_type=CR/PR/DHR/SHR。
        part_dir = self.output_dir / "causes_full_parts" / f"relation_type={relation_type}"
        part_dir.mkdir(parents=True, exist_ok=True)
        part_no = self.part_numbers[relation_type]
        if self.output_format == "parquet":
            path = part_dir / f"part-{part_no:06d}.parquet"
            self.pd.DataFrame(rows, columns=TCG_EDGE_FIELDS).to_parquet(path, index=False)
        else:
            path = part_dir / f"part-{part_no:06d}.csv"
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=TCG_EDGE_FIELDS)
                writer.writeheader()
                writer.writerows({name: row.get(name, "") for name in TCG_EDGE_FIELDS} for row in rows)
        self.part_numbers[relation_type] += 1
        self.counts[relation_type] += len(rows)
        rows.clear()

    def close(self) -> None:
        for relation_type in list(self.buffers):
            self.flush(relation_type)


class PairDeduper:
    def add(self, src_record_id: str, dst_record_id: str) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        return


class MemoryPairDeduper(PairDeduper):
    def __init__(self) -> None:
        self.seen_pairs: set[tuple[str, str]] = set()

    def add(self, src_record_id: str, dst_record_id: str) -> bool:
        pair_key = (src_record_id, dst_record_id)
        if pair_key in self.seen_pairs:
            return False
        self.seen_pairs.add(pair_key)
        return True


class SQLitePairDeduper(PairDeduper):
    def __init__(self, path: Path, commit_interval: int = 100_000) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        self.path = path
        self.commit_interval = commit_interval
        self.pending = 0
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=OFF")
        self.conn.execute("PRAGMA synchronous=OFF")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA locking_mode=EXCLUSIVE")
        self.conn.execute("CREATE TABLE seen_pairs (src_record_id TEXT NOT NULL, dst_record_id TEXT NOT NULL, PRIMARY KEY (src_record_id, dst_record_id)) WITHOUT ROWID")
        self.conn.execute("BEGIN")

    def add(self, src_record_id: str, dst_record_id: str) -> bool:
        cursor = self.conn.execute("INSERT OR IGNORE INTO seen_pairs VALUES (?, ?)", (src_record_id, dst_record_id))
        self.pending += 1
        if self.pending >= self.commit_interval:
            self.conn.commit()
            self.conn.execute("BEGIN")
            self.pending = 0
        return cursor.rowcount == 1

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()


def build_edges(
    flows: list[dict[str, Any]],
    output_dir: Path,
    relation_types: list[str],
    output_format: str,
    chunk_size: int,
    max_delta_seconds: int | None,
    relation_window_overrides: dict[str, int | None] | None = None,
    dedupe_store: str = "sqlite",
    dedupe_sqlite_path: Path | None = None,
) -> Counter[str]:
    writer = PartitionWriter(output_dir, output_format, chunk_size)
    # relation_types 已按优先级排序；同一有向 flow pair 先命中的就是最高优先级关系。
    if dedupe_store == "memory":
        deduper: PairDeduper = MemoryPairDeduper()
    else:
        dedupe_path = dedupe_sqlite_path or output_dir / ".tcg_seen_pairs.sqlite"
        print(f"dedupe_store=sqlite file={dedupe_path}", flush=True)
        deduper = SQLitePairDeduper(dedupe_path)
    windows = relation_windows(max_delta_seconds, relation_window_overrides)
    try:
        for relation_type in relation_types:
            for left, right, matched_rule, shared_ip, shared_endpoint in progress_iter(
                relation_pairs(flows, relation_type, windows[relation_type]),
                f"build {relation_type} edges",
                "edges",
            ):
                edge = tcg_edge(left, right, relation_type, matched_rule, shared_ip, shared_endpoint)
                if not deduper.add(edge["src_record_id"], edge["dst_record_id"]):
                    continue
                writer.write(edge)
            writer.flush(relation_type)
            print(f"relation_type={relation_type} edges_written={writer.counts[relation_type]}", flush=True)
    finally:
        deduper.close()
        writer.close()
    return writer.counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or estimate the CR/PR/DHR/SHR Traffic Causality Graph (TCG).")
    parser.add_argument("--input", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=["estimate", "build"], required=True)
    parser.add_argument("--output", type=Path, default=Path("data/processed/tcg"))
    parser.add_argument("--relation-types", type=parse_relation_types, default=parse_relation_types("CR,PR,DHR,SHR"))
    parser.add_argument("--output-format", choices=["parquet", "csv"], default="parquet")
    parser.add_argument("--partition-by", choices=["relation_type"], default="relation_type")
    parser.add_argument("--chunk-size", type=int, default=1_000_000)
    parser.add_argument("--max-rows", type=int, default=None, help="Optional smoke-test limit only; do not use for full construction.")
    parser.add_argument("--max-delta-seconds", type=int, default=DEFAULT_MAX_DELTA_SECONDS, help="Fallback flow-pair time window in seconds. Use 0 to disable for relations without an override.")
    parser.add_argument(
        "--relation-max-delta-seconds",
        type=parse_relation_windows,
        default=parse_relation_windows(DEFAULT_RELATION_WINDOW_TEXT),
        help=f"Time window per relation. Default: {DEFAULT_RELATION_WINDOW_TEXT}. Use RELATION=0 to disable one relation window.",
    )
    parser.add_argument("--max-candidate-edges", type=int, default=DEFAULT_MAX_CANDIDATE_EDGES, help="Abort build when estimated selected candidate edges exceed this limit.")
    parser.add_argument("--force-large-build", action="store_true", help="Bypass the candidate-edge safety guard.")
    parser.add_argument("--dedupe-store", choices=["sqlite", "memory"], default="sqlite", help="Store TCG pair de-duplication state on disk or in memory. SQLite is slower but uses much less RAM.")
    parser.add_argument("--dedupe-sqlite-path", type=Path, default=None, help="SQLite file for --dedupe-store sqlite. Default: OUTPUT/.tcg_seen_pairs.sqlite")
    args = parser.parse_args()
    max_delta_seconds = normalize_window(args.max_delta_seconds)

    args.output.mkdir(parents=True, exist_ok=True)
    estimate = estimate_edges_from_path(args.input, args.max_rows, max_delta_seconds, args.relation_max_delta_seconds)
    if args.mode == "estimate":
        report_path = write_estimation_report(estimate, args.output)
        print(f"report={report_path}")
        print(f"total_candidate_edges={estimate['total']}")
        return

    selected_candidate_edges = sum(estimate[relation_type] for relation_type in args.relation_types)
    if selected_candidate_edges > args.max_candidate_edges and not args.force_large_build:
        report_path = write_estimation_report(estimate, args.output)
        selected = ",".join(args.relation_types)
        parser.error(
            f"Refusing to build relation_types={selected}: estimated_candidate_edges={selected_candidate_edges:,} "
            f"exceeds --max-candidate-edges={args.max_candidate_edges:,}. "
            f"Review {report_path}, reduce --relation-types/--max-rows, or pass --force-large-build explicitly."
        )

    flows = load_flows(args.input, args.max_rows)
    flow_path = write_flows(flows, args.output, args.output_format)
    counts = build_edges(
        flows,
        args.output,
        args.relation_types,
        args.output_format,
        args.chunk_size,
        max_delta_seconds,
        args.relation_max_delta_seconds,
        args.dedupe_store,
        args.dedupe_sqlite_path,
    )
    print(f"flows_file={flow_path}")
    print(f"causes_parts_dir={args.output / 'causes_full_parts'}")
    for relation_type in args.relation_types:
        print(f"{relation_type}_edges={counts[relation_type]}")


if __name__ == "__main__":
    main()
