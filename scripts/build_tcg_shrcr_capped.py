#!/usr/bin/env python3
"""从 flows_normalized.parquet 生成 SHR+CR causes CSV，SHR 带度数 cap。

根因背景（必读）
----------------
A parquet 的 raw_timestamp_epoch 在 19 天数据里**只有 363 个唯一值**（精度退化到极粗）。
导致时间窗口配对在热门端点（代理端口 3128 等）爆炸：单端点 10.200.7.9:3128 有 12 万
flow，5 秒窗口内平均 991 个邻居，C(n,2) 候选 >700 亿；全图 SHR 候选 3 亿。
直接用 build_tcg.py（无 cap）会在这些端点生成几亿边，耗时数小时且语义失真。

度数 cap 是此场景下控制度数的唯一手段：每 flow 最多保留 K 个 SHR 邻居（按 timestamp
+record_id 最近的 K 个）。同端点最近 K 个 flow 足以传播标签（SHR 多数类纯度 0.76），
且彻底规避 timestamp 精度退化导致的度数失控。

CR（五元组反转）候选仅 46 万——严格的五元组匹配本身已把配对限制住，不受 timestamp
精度影响，无需 cap。

复用 build_tcg.PartitionWriter / SQLitePairDeduper 与 transform.tcg_edge，
输出格式与 5-29 标准流程完全一致（flows.csv + causes_full_parts/relation_type=*）。
"""
from __future__ import annotations

import bisect
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd

from build_tcg import PartitionWriter, SQLitePairDeduper  # noqa: E402
from tugraph_homework.common import progress_iter, write_dict_csv  # noqa: E402
from tugraph_homework.transform import TCG_FLOW_FIELDS, tcg_edge  # noqa: E402

INPUT = ROOT / "data/processed/tcg_light_shrcr/flows_normalized.parquet"
OUTPUT = ROOT / "data/processed/tcg_light_shrcr"

K_SHR = 15          # 每 flow 最多保留 K 个 SHR 邻居（出度 cap）
SHR_WINDOW = 5      # SHR 时间窗口（秒）；timestamp 精度低时主要由 cap 兜底
CR_WINDOW = 5       # CR 时间窗口（秒）
CHUNK = 1_000_000


def _ts(flow: dict) -> int:
    return int(flow.get("timestamp_epoch") or 0)


def main() -> int:
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    print(f"[load] {INPUT}")
    df = pd.read_parquet(INPUT, columns=TCG_FLOW_FIELDS)
    print(f"  rows={len(df):,}")
    flows = df.to_dict("records")
    del df
    print(f"  flows_loaded={len(flows):,}")

    # flows.csv（Flow 顶点属性，TCG_FLOW_FIELDS 标准格式）
    flows_csv = OUTPUT / "flows.csv"
    write_dict_csv(flows_csv, TCG_FLOW_FIELDS, flows, progress_desc="write flows", total=len(flows))
    print(f"  flows_csv={flows_csv}")

    writer = PartitionWriter(OUTPUT, "csv", CHUNK)
    deduper = SQLitePairDeduper(OUTPUT / ".tcg_shrcr_seen.sqlite")
    counts = {"CR": 0, "SHR": 0}

    # === SHR：同 (src_ip, src_port) 桶，组内按 (timestamp, record_id) 排序，每 flow 向右 cap K ===
    by_ep: dict[tuple, list[dict]] = defaultdict(list)
    for f in flows:
        by_ep[(f["src_ip"], f["src_port"])].append(f)
    print(f"[SHR] endpoints={len(by_ep):,}  cap_K={K_SHR}  window={SHR_WINDOW}s")
    for group in progress_iter(by_ep.values(), "SHR pairs", "endpoints", len(by_ep)):
        group.sort(key=lambda f: (_ts(f), str(f["record_id"])))
        n = len(group)
        for i in range(n):
            left = group[i]
            lts = _ts(left)
            cnt = 0
            for j in range(i + 1, n):
                right = group[j]
                if _ts(right) - lts > SHR_WINDOW:
                    break
                edge = tcg_edge(left, right, "SHR")
                if deduper.add(edge["src_record_id"], edge["dst_record_id"]):
                    writer.write(edge)
                    counts["SHR"] += 1
                cnt += 1
                if cnt >= K_SHR:
                    break
    writer.flush("SHR")
    print(f"  SHR edges_written={counts['SHR']:,}")

    # === CR：五元组反转，时间窗口配对（不 cap；候选 ~46 万可控）===
    by_tuple: dict[tuple, list[dict]] = defaultdict(list)
    for f in flows:
        by_tuple[(f["protocol"], f["src_ip"], f["src_port"], f["dst_ip"], f["dst_port"])].append(f)
    print(f"[CR] five_tuples={len(by_tuple):,}  window={CR_WINDOW}s")
    seen: set[tuple] = set()
    for key, group in progress_iter(by_tuple.items(), "CR pairs", "tuples", len(by_tuple)):
        if key in seen:
            continue
        rev = (key[0], key[3], key[4], key[1], key[2])
        rev_group = by_tuple.get(rev)
        seen.add(key)
        if not rev_group:
            continue
        seen.add(rev)
        g_sorted = sorted(group, key=_ts)
        r_sorted = sorted(rev_group, key=_ts)
        r_ts = [_ts(f) for f in r_sorted]
        for left in g_sorted:
            lts = _ts(left)
            lo = bisect.bisect_left(r_ts, lts - CR_WINDOW)
            hi = bisect.bisect_right(r_ts, lts + CR_WINDOW)
            for k in range(lo, hi):
                right = r_sorted[k]
                if left["record_id"] == right["record_id"]:
                    continue
                edge = tcg_edge(left, right, "CR")
                if deduper.add(edge["src_record_id"], edge["dst_record_id"]):
                    writer.write(edge)
                    counts["CR"] += 1
    writer.flush("CR")
    print(f"  CR edges_written={counts['CR']:,}")

    writer.close()
    deduper.close()
    total = counts["CR"] + counts["SHR"]
    print(f"[done] SHR={counts['SHR']:,}  CR={counts['CR']:,}  total={total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
