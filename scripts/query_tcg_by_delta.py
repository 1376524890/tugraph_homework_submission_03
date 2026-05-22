#!/usr/bin/env python3
"""生成 TCG 查询视图。

本脚本读取无时间窗口约束的 causes_full 分区或文件，在查询阶段按
delta_seconds、relation_type 和可选前驱/后继数量生成派生子图。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_relation_types(value: str) -> list[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit("This query script requires pandas and pyarrow for Parquet input/output.") from exc
    return pd


def read_edges(path: Path):
    pd = require_pandas()
    if path.is_dir():
        # 支持读取 causes_full_parts/relation_type=... 这种分区目录。
        parquet_parts = sorted(path.glob("**/*.parquet"))
        if parquet_parts:
            return pd.concat((pd.read_parquet(part) for part in parquet_parts), ignore_index=True)
        csv_parts = sorted(path.glob("**/*.csv"))
        if csv_parts:
            return pd.concat((pd.read_csv(part) for part in csv_parts), ignore_index=True)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    raise FileNotFoundError(f"No readable TCG edge files found at {path}")


def write_output(frame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".parquet":
        frame.to_parquet(path, index=False)
        return
    frame.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)


def write_report(output_path: Path, input_path: Path, row_count: int, args: argparse.Namespace) -> Path:
    report_path = output_path.with_suffix(output_path.suffix + ".report.md")
    lines = [
        "# TCG Delta Query View Report",
        "",
        "This file describes a query-stage derived TCG subgraph.",
        "It is not the original full TCG construction result.",
        "",
        f"- Input: `{input_path}`",
        f"- Output: `{output_path}`",
        f"- Rows: {row_count:,}",
        f"- max_delta_seconds: {args.max_delta_seconds}",
        f"- relation_types: {','.join(args.relation_types)}",
        f"- max_predecessors_per_flow: {args.max_predecessors_per_flow or 'not applied'}",
        f"- max_successors_per_flow: {args.max_successors_per_flow or 'not applied'}",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a query-stage TCG view filtered by delta_seconds.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-delta-seconds", type=int, required=True)
    parser.add_argument("--relation-types", type=parse_relation_types, default=parse_relation_types("CR,PR,DHR,SHR"))
    parser.add_argument("--max-predecessors-per-flow", type=int, default=None)
    parser.add_argument("--max-successors-per-flow", type=int, default=None)
    args = parser.parse_args()

    frame = read_edges(args.input)
    # 时间窗口只在查询视图阶段应用；原始 causes_full 构图结果不被改写。
    frame = frame[frame["delta_seconds"] <= args.max_delta_seconds]
    frame = frame[frame["relation_type"].isin(args.relation_types)]
    sort_cols = ["relation_priority", "delta_seconds", "src_record_id", "dst_record_id"]
    if args.max_predecessors_per_flow:
        # 可选前驱裁剪：对每个目标 flow 保留优先级更高、时间差更小的前 k 条。
        frame = (
            frame.sort_values(sort_cols)
            .groupby("dst_record_id", group_keys=False)
            .head(args.max_predecessors_per_flow)
        )
    if args.max_successors_per_flow:
        # 可选后继裁剪：对每个源 flow 保留优先级更高、时间差更小的后 k 条。
        frame = (
            frame.sort_values(sort_cols)
            .groupby("src_record_id", group_keys=False)
            .head(args.max_successors_per_flow)
        )
    write_output(frame, args.output)
    report_path = write_report(args.output, args.input, len(frame), args)
    print(f"query_view={args.output}")
    print(f"report={report_path}")
    print(f"rows={len(frame)}")


if __name__ == "__main__":
    main()
