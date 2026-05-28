#!/usr/bin/env python3
"""Estimate TCG D64-capped size for K=5 and K=10.

Streams through all relation type CSV partitions to compute:
- Total edge count per relation type
- Degree distributions (src out-degree, dst in-degree)
- Estimated capped edge counts for K=5 and K=10
- Disk space estimates

Uses chunked reading to avoid OOM.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from tugraph_homework.common import ROOT


RELATION_TYPES = ["CR", "PR", "DHR", "SHR"]
RELATION_PRIORITY = {"CR": 1, "PR": 2, "DHR": 3, "SHR": 4}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Estimate TCG D64-capped size.")
    parser.add_argument("--tcg-dir", type=Path, default=ROOT / "data/processed/tcg")
    parser.add_argument("--report", type=Path, default=ROOT / "data/features/tcg/reports/tcg_d64_capped_size_estimation_report.md")
    parser.add_argument("--json-report", type=Path, default=ROOT / "data/features/tcg/reports/tcg_d64_capped_size_estimation_report.json")
    parser.add_argument("--sample-rows", type=int, default=0, help="0 = full scan")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def scan_edges(tcg_dir: Path, max_rows: int = 0) -> dict:
    """Scan all relation type partitions and collect edge stats."""
    stats: dict[str, int] = {rt: 0 for rt in RELATION_TYPES}
    total_rows = 0
    src_out_degree: dict[str, int] = defaultdict(int)
    dst_in_degree: dict[str, int] = defaultdict(int)
    all_src: set[str] = set()
    all_dst: set[str] = set()

    for rt in RELATION_TYPES:
        parts_dir = tcg_dir / "causes_full_parts" / f"relation_type={rt}"
        if not parts_dir.exists():
            print(f"  {rt}: partition not found at {parts_dir}", flush=True)
            continue
        csv_files = sorted(parts_dir.glob("*.csv"))
        print(f"  {rt}: {len(csv_files)} files", flush=True)
        for csv_file in csv_files:
            with csv_file.open("r", encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if max_rows and total_rows >= max_rows:
                        break
                    src = row.get("src_record_id", "").strip()
                    dst = row.get("dst_record_id", "").strip()
                    if src and dst:
                        src_out_degree[src] += 1
                        dst_in_degree[dst] += 1
                        all_src.add(src)
                        all_dst.add(dst)
                    stats[rt] += 1
                    total_rows += 1
            if max_rows and total_rows >= max_rows:
                break
        if max_rows and total_rows >= max_rows:
            break

    return {
        "edge_counts": stats,
        "total_edges": total_rows,
        "unique_src": len(all_src),
        "unique_dst": len(all_dst),
        "unique_vertices": len(all_src | all_dst),
        "src_out_degree": src_out_degree,
        "dst_in_degree": dst_in_degree,
    }


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    idx = int(len(values) * p / 100)
    idx = min(idx, len(values) - 1)
    return values[idx]


def estimate_capped(
    src_out_degree: dict[str, int],
    dst_in_degree: dict[str, int],
    k: int,
) -> dict:
    """Estimate capped edge count for given K."""
    # Predecessor cap: each dst keeps at most K incoming edges
    predecessor_capped = sum(min(count, k) for count in dst_in_degree.values())
    # Successor cap: each src keeps at most K outgoing edges
    successor_capped = sum(min(count, k) for count in src_out_degree.values())
    # Union: take max of the two (rough upper bound)
    union_upper = max(predecessor_capped, successor_capped)
    # More realistic: average
    union_estimate = (predecessor_capped + successor_capped) // 2

    return {
        "K": k,
        "predecessor_capped_edges": predecessor_capped,
        "successor_capped_edges": successor_capped,
        "union_upper_bound": union_upper,
        "union_estimate": union_estimate,
    }


def main() -> int:
    args = parse_args()
    args.tcg_dir = resolve_path(args.tcg_dir)
    args.report = resolve_path(args.report)
    args.json_report = resolve_path(args.json_report)

    print("Scanning TCG edges...", flush=True)
    scan_result = scan_edges(args.tcg_dir, args.sample_rows)

    # Degree distributions
    out_degrees = sorted(scan_result["src_out_degree"].values())
    in_degrees = sorted(scan_result["dst_in_degree"].values())

    out_stats = {
        "count": len(out_degrees),
        "min": out_degrees[0] if out_degrees else 0,
        "p50": percentile(out_degrees, 50),
        "p90": percentile(out_degrees, 90),
        "p95": percentile(out_degrees, 95),
        "p99": percentile(out_degrees, 99),
        "max": out_degrees[-1] if out_degrees else 0,
    }
    in_stats = {
        "count": len(in_degrees),
        "min": in_degrees[0] if in_degrees else 0,
        "p50": percentile(in_degrees, 50),
        "p90": percentile(in_degrees, 90),
        "p95": percentile(in_degrees, 95),
        "p99": percentile(in_degrees, 99),
        "max": in_degrees[-1] if in_degrees else 0,
    }

    # Capped estimates
    k5 = estimate_capped(scan_result["src_out_degree"], scan_result["dst_in_degree"], 5)
    k10 = estimate_capped(scan_result["src_out_degree"], scan_result["dst_in_degree"], 10)
    k20 = estimate_capped(scan_result["src_out_degree"], scan_result["dst_in_degree"], 20)

    # Disk estimates (rough: each edge ~150 bytes in CSV, ~300 bytes in TuGraph)
    csv_bytes_per_edge = 150
    tugraph_bytes_per_edge = 300
    walk_bytes_per_edge = 50  # rough estimate

    def disk_estimate(edge_count: int) -> dict:
        csv_gb = edge_count * csv_bytes_per_edge / (1024 ** 3)
        tugraph_gb = edge_count * tugraph_bytes_per_edge / (1024 ** 3)
        # Walks: ~3.5M start nodes * 2 walks * 10 tokens * 15 bytes
        walk_gb = 3_577_296 * 2 * 10 * 15 / (1024 ** 3)
        emb_mb = 3_577_296 * 64 * 4 / (1024 ** 2)  # float32
        return {
            "csv_input_gb": round(csv_gb, 2),
            "tugraph_data_gb": round(tugraph_gb, 2),
            "walk_file_gb": round(walk_gb, 2),
            "embedding_parquet_mb": round(emb_mb, 2),
            "total_peak_gb": round(csv_gb + tugraph_gb + walk_gb + emb_mb / 1024, 2),
        }

    # Feasibility verdicts
    import shutil
    disk_free_gb = shutil.disk_usage(ROOT).free / (1024 ** 3)

    def verdict_k(k_est: dict, k_label: str) -> str:
        edges = k_est["union_estimate"]
        disk_needed = disk_estimate(edges)["total_peak_gb"]
        if edges <= 40_000_000 and disk_free_gb >= 60:
            return "FEASIBLE"
        elif edges <= 40_000_000 and disk_free_gb >= 40:
            return "CAUTIOUS - disk tight but possible"
        elif edges <= 80_000_000 and disk_free_gb >= 100:
            return "FEASIBLE"
        elif edges <= 80_000_000 and disk_free_gb >= 60:
            return "CAUTIOUS - disk tight"
        elif edges > 100_000_000:
            return "NOT_RECOMMENDED - close to full TCG"
        else:
            return f"CAUTION - estimated {disk_needed:.1f}GB needed, {disk_free_gb:.1f}GB free"

    result = {
        "edge_counts": scan_result["edge_counts"],
        "total_edges": scan_result["total_edges"],
        "unique_src": scan_result["unique_src"],
        "unique_dst": scan_result["unique_dst"],
        "unique_vertices": scan_result["unique_vertices"],
        "src_out_degree_stats": out_stats,
        "dst_in_degree_stats": in_stats,
        "k5": {**k5, "disk_estimate": disk_estimate(k5["union_estimate"]), "verdict": verdict_k(k5, "K=5")},
        "k10": {**k10, "disk_estimate": disk_estimate(k10["union_estimate"]), "verdict": verdict_k(k10, "K=10")},
        "k20": {**k20, "disk_estimate": disk_estimate(k20["union_estimate"]), "verdict": verdict_k(k20, "K=20")},
        "disk_free_gb": round(disk_free_gb, 2),
        "sample_rows": args.sample_rows,
        "full_scan": args.sample_rows == 0,
    }

    # Write reports
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as fh:
        fh.write("# TCG D64-Capped Size Estimation Report\n\n")
        fh.write("## Edge Counts by Relation Type\n\n")
        fh.write("| Relation | Count |\n| --- | ---: |\n")
        for rt in RELATION_TYPES:
            fh.write(f"| `{rt}` | `{scan_result['edge_counts'][rt]:,}` |\n")
        fh.write(f"| **Total** | **{scan_result['total_edges']:,}** |\n\n")

        fh.write("## Vertex Statistics\n\n")
        fh.write(f"- Unique source vertices: {scan_result['unique_src']:,}\n")
        fh.write(f"- Unique destination vertices: {scan_result['unique_dst']:,}\n")
        fh.write(f"- Unique vertices (union): {scan_result['unique_vertices']:,}\n\n")

        fh.write("## Degree Distributions\n\n")
        fh.write("### Source Out-Degree\n\n")
        fh.write("| Percentile | Value |\n| --- | ---: |\n")
        for key in ["p50", "p90", "p95", "p99", "max"]:
            fh.write(f"| `{key}` | `{out_stats[key]:,}` |\n")
        fh.write("\n### Destination In-Degree\n\n")
        fh.write("| Percentile | Value |\n| --- | ---: |\n")
        for key in ["p50", "p90", "p95", "p99", "max"]:
            fh.write(f"| `{key}` | `{in_stats[key]:,}` |\n")

        fh.write("\n## Capped Estimates\n\n")
        for label, est in [("K=5", k5), ("K=10", k10), ("K=20", k20)]:
            disk = disk_estimate(est["union_estimate"])
            fh.write(f"### {label}\n\n")
            fh.write(f"- Predecessor-capped edges: {est['predecessor_capped_edges']:,}\n")
            fh.write(f"- Successor-capped edges: {est['successor_capped_edges']:,}\n")
            fh.write(f"- Union upper bound: {est['union_upper_bound']:,}\n")
            fh.write(f"- Union estimate: {est['union_estimate']:,}\n")
            fh.write(f"- Estimated CSV input: {disk['csv_input_gb']:.2f} GB\n")
            fh.write(f"- Estimated TuGraph data: {disk['tugraph_data_gb']:.2f} GB\n")
            fh.write(f"- Estimated walk file: {disk['walk_file_gb']:.2f} GB\n")
            fh.write(f"- Estimated embedding parquet: {disk['embedding_parquet_mb']:.2f} MB\n")
            fh.write(f"- Verdict: **{result[label.replace('=', '').lower()]['verdict']}**\n\n")

        fh.write(f"\n## Disk Space\n\n- Free: {disk_free_gb:.2f} GB\n")

    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    # Remove non-serializable degree dicts
    json_result = {k: v for k, v in result.items() if k not in ("src_out_degree", "dst_in_degree")}
    args.json_report.write_text(json.dumps(json_result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps(json_result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
