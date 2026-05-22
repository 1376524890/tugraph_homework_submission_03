#!/usr/bin/env python3
"""构建或估算新版 TCG。

本脚本支持 estimate 模式估算 CR/PR/DHR/SHR 边数量，也支持 build 模式按
relation_type 分区写出无时间窗口约束的 causes_full_parts。构图阶段不使用
window_seconds 或 max_predecessors。
"""

from __future__ import annotations

import argparse
import csv
import itertools
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import DEFAULT_DATASET, read_rows, write_dict_csv  # noqa: E402
from tugraph_homework.transform import (  # noqa: E402
    RELATION_PRIORITIES,
    TCG_EDGE_FIELDS,
    TCG_FLOW_FIELDS,
    classify_relation,
    flow_vertex,
    tcg_edge,
)


def parse_relation_types(value: str) -> list[str]:
    relation_types = [item.strip().upper() for item in value.split(",") if item.strip()]
    invalid = [item for item in relation_types if item not in RELATION_PRIORITIES]
    if invalid:
        raise argparse.ArgumentTypeError(f"Unsupported relation types: {','.join(invalid)}")
    return sorted(set(relation_types), key=lambda item: RELATION_PRIORITIES[item])


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
    return [flow_vertex(row_number, row) for row_number, row in read_rows(input_path, max_rows=max_rows)]


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
    write_dict_csv(tmp_path, TCG_FLOW_FIELDS, flows)
    os.replace(tmp_path, path)
    return path


def n_choose_2(n: int) -> int:
    return n * (n - 1) // 2


def estimate_edges(flows: list[dict[str, Any]]) -> dict[str, Any]:
    # 估算只做分组计数，不枚举实际边；用于全量构图前判断 PR/DHR/SHR 是否会爆炸。
    five_tuple_counts: Counter[tuple[Any, ...]] = Counter()
    src_ip_counts: Counter[str] = Counter()
    dst_ip_counts: Counter[str] = Counter()
    src_ip_port_counts: Counter[tuple[str, int]] = Counter()
    src_ip_to_ports: dict[str, Counter[int]] = defaultdict(Counter)

    for flow in flows:
        five_tuple_counts[(flow["protocol"], flow["src_ip"], flow["src_port"], flow["dst_ip"], flow["dst_port"])] += 1
        src_ip_counts[flow["src_ip"]] += 1
        dst_ip_counts[flow["dst_ip"]] += 1
        src_ip_port_counts[(flow["src_ip"], flow["src_port"])] += 1
        src_ip_to_ports[flow["src_ip"]][flow["src_port"]] += 1

    cr_pairs = 0
    seen_cr_keys: set[tuple[Any, ...]] = set()
    for key, count in five_tuple_counts.items():
        # CR 通过五元组和反向五元组相乘估算，seen_cr_keys 避免正反方向重复计数。
        reverse_key = (key[0], key[3], key[4], key[1], key[2])
        if key in seen_cr_keys:
            continue
        if key == reverse_key:
            cr_pairs += n_choose_2(count)
        else:
            cr_pairs += count * five_tuple_counts.get(reverse_key, 0)
        seen_cr_keys.add(key)
        seen_cr_keys.add(reverse_key)

    # PR 估算：同一 IP 作为前序 dst 和后续 src 的笛卡尔积。
    pr_pairs = sum(dst_ip_counts[ip] * src_ip_counts[ip] for ip in set(dst_ip_counts) | set(src_ip_counts))
    dhr_pairs = 0
    for ports in src_ip_to_ports.values():
        total = sum(ports.values())
        same_port_pairs = sum(n_choose_2(count) for count in ports.values())
        # DHR 是同一 src_ip 下不同 src_port 的组合，所以要扣掉同端口组合。
        dhr_pairs += n_choose_2(total) - same_port_pairs
    shr_pairs = sum(n_choose_2(count) for count in src_ip_port_counts.values())
    total_pairs = cr_pairs + pr_pairs + dhr_pairs + shr_pairs
    return {
        "flow_count": len(flows),
        "CR": cr_pairs,
        "PR": pr_pairs,
        "DHR": dhr_pairs,
        "SHR": shr_pairs,
        "total": total_pairs,
        "estimated_parquet_size": int(total_pairs * 180 * 0.35),
        "estimated_csv_size": int(total_pairs * 180),
        "top_groups": top_risk_groups(src_ip_counts, dst_ip_counts, src_ip_to_ports, src_ip_port_counts),
    }


def top_risk_groups(
    src_ip_counts: Counter[str],
    dst_ip_counts: Counter[str],
    src_ip_to_ports: dict[str, Counter[int]],
    src_ip_port_counts: Counter[tuple[str, int]],
) -> list[tuple[str, str, int]]:
    rows: list[tuple[str, str, int]] = []
    for ip in set(src_ip_counts) | set(dst_ip_counts):
        rows.append(("PR", ip, src_ip_counts[ip] * dst_ip_counts[ip]))
    for ip, ports in src_ip_to_ports.items():
        total = sum(ports.values())
        same = sum(n_choose_2(count) for count in ports.values())
        rows.append(("DHR", ip, n_choose_2(total) - same))
    for (ip, port), count in src_ip_port_counts.items():
        rows.append(("SHR", f"{ip}:{port}", n_choose_2(count)))
    return sorted(rows, key=lambda item: item[2], reverse=True)[:20]


def write_estimation_report(estimate: dict[str, Any], output_dir: Path) -> Path:
    report_dir = output_dir.parent / "reports" if output_dir.name == "tcg" else output_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "tcg_edge_estimation_report.md"
    lines = [
        "# TCG Edge Estimation Report",
        "",
        "This report estimates CR/PR/DHR/SHR candidate edges before full TCG construction.",
        "No time window or max_predecessors truncation is applied.",
        "",
        f"- Flow count: {estimate['flow_count']:,}",
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


def relation_pairs(flows: list[dict[str, Any]], relation_type: str) -> Iterator[tuple[dict[str, Any], dict[str, Any], str, str, str]]:
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
                iterable = pair_flows(left_group)
            else:
                iterable = itertools.product(left_group, right_group)
            for left, right in iterable:
                relation = classify_relation(left, right)
                if relation and relation[0] == "CR":
                    yield left, right, relation[1], relation[2], relation[3]
            seen_keys.add(key)
            seen_keys.add(reverse_key)
        return

    if relation_type == "PR":
        # PR 只在 dst_ip == src_ip 的两个桶之间枚举；这里不加时间窗口。
        by_dst_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_src_ip: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for flow in flows:
            by_dst_ip[flow["dst_ip"]].append(flow)
            by_src_ip[flow["src_ip"]].append(flow)
        for ip in set(by_dst_ip) & set(by_src_ip):
            for left, right in itertools.product(by_dst_ip[ip], by_src_ip[ip]):
                relation = classify_relation(left, right)
                if relation and relation[0] == "PR":
                    yield left, right, relation[1], relation[2], relation[3]
        return

    if relation_type == "DHR":
        # DHR 在同一 src_ip 内跨不同 src_port 枚举。
        by_src_ip: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for flow in flows:
            by_src_ip[flow["src_ip"]][flow["src_port"]].append(flow)
        for port_groups in by_src_ip.values():
            for left_port, right_port in itertools.combinations(sorted(port_groups), 2):
                for left, right in itertools.product(port_groups[left_port], port_groups[right_port]):
                    relation = classify_relation(left, right)
                    if relation and relation[0] == "DHR":
                        yield left, right, relation[1], relation[2], relation[3]
        return

    # SHR 在同一 (src_ip, src_port) 桶内两两配对。
    by_src_ip_port: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for flow in flows:
        by_src_ip_port[(flow["src_ip"], flow["src_port"])].append(flow)
    for group in by_src_ip_port.values():
        for left, right in pair_flows(group):
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


def build_edges(flows: list[dict[str, Any]], output_dir: Path, relation_types: list[str], output_format: str, chunk_size: int) -> Counter[str]:
    writer = PartitionWriter(output_dir, output_format, chunk_size)
    # relation_types 已按优先级排序；同一有向 flow pair 先命中的就是最高优先级关系。
    seen_pairs: set[tuple[str, str]] = set()
    try:
        for relation_type in relation_types:
            for left, right, matched_rule, shared_ip, shared_endpoint in relation_pairs(flows, relation_type):
                edge = tcg_edge(left, right, relation_type, matched_rule, shared_ip, shared_endpoint)
                pair_key = (edge["src_record_id"], edge["dst_record_id"])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                writer.write(edge)
            writer.flush(relation_type)
            print(f"relation_type={relation_type} edges_written={writer.counts[relation_type]}", flush=True)
    finally:
        writer.close()
    return writer.counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or estimate the CR/PR/DHR/SHR Traffic Causality Graph (TCG).")
    parser.add_argument("--input", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=["estimate", "build"], required=True)
    parser.add_argument("--output", type=Path, default=Path("data/rebuild/tcg"))
    parser.add_argument("--relation-types", type=parse_relation_types, default=parse_relation_types("CR,PR,DHR,SHR"))
    parser.add_argument("--output-format", choices=["parquet", "csv"], default="parquet")
    parser.add_argument("--partition-by", choices=["relation_type"], default="relation_type")
    parser.add_argument("--chunk-size", type=int, default=1_000_000)
    parser.add_argument("--max-rows", type=int, default=None, help="Optional smoke-test limit only; do not use for full construction.")
    args = parser.parse_args()

    flows = load_flows(args.input, args.max_rows)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "estimate":
        estimate = estimate_edges(flows)
        report_path = write_estimation_report(estimate, args.output)
        print(f"report={report_path}")
        print(f"total_candidate_edges={estimate['total']}")
        return

    flow_path = write_flows(flows, args.output, args.output_format)
    counts = build_edges(flows, args.output, args.relation_types, args.output_format, args.chunk_size)
    print(f"flows_file={flow_path}")
    print(f"causes_parts_dir={args.output / 'causes_full_parts'}")
    for relation_type in args.relation_types:
        print(f"{relation_type}_edges={counts[relation_type]}")


if __name__ == "__main__":
    main()
