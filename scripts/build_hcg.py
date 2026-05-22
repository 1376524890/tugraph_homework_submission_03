#!/usr/bin/env python3
"""构建 HCG 中间文件。

本脚本从原始或标准化 flow 数据读取记录，生成 Endpoint 顶点 CSV 和
COMMUNICATES 聚合边 CSV。输出默认写入 data/rebuild/hcg，不会连接 TuGraph。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import DEFAULT_DATASET, write_dict_csv  # noqa: E402
from tugraph_homework.transform import HCG_EDGE_FIELDS, HCG_ENDPOINT_FIELDS, build_hcg_rows  # noqa: E402


def replace_tmp(tmp_path: Path, final_path: Path) -> None:
    os.replace(tmp_path, final_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the flow-level Host Communication Graph (HCG) CSV files.")
    parser.add_argument("--input", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=Path("data/rebuild/hcg"))
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    endpoint_path = args.output / "endpoints.csv"
    edge_path = args.output / "communicates.csv"
    endpoint_tmp = endpoint_path.with_suffix(".csv.tmp")
    edge_tmp = edge_path.with_suffix(".csv.tmp")

    endpoints, edges = build_hcg_rows(args.input, args.max_rows)
    endpoint_count = write_dict_csv(endpoint_tmp, HCG_ENDPOINT_FIELDS, endpoints.values(), progress_desc="write HCG endpoints", total=len(endpoints))
    edge_count = write_dict_csv(edge_tmp, HCG_EDGE_FIELDS, edges.values(), progress_desc="write HCG edges", total=len(edges))
    replace_tmp(endpoint_tmp, endpoint_path)
    replace_tmp(edge_tmp, edge_path)

    print(f"hcg_endpoints={endpoint_count} file={endpoint_path}")
    print(f"hcg_edges={edge_count} file={edge_path}")


if __name__ == "__main__":
    main()
