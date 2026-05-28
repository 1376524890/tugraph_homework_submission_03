#!/usr/bin/env python3
"""Check TCG Node2Vec walk file and id_map for correctness."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from tugraph_homework.common import ROOT, progress_iter


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check TCG walk file and id_map.")
    parser.add_argument("--walks", type=Path, required=True)
    parser.add_argument("--id-map", type=Path, required=True)
    parser.add_argument("--min-walk-len", type=int, default=2)
    parser.add_argument("--max-lines", type=int, default=0, help="0 = all")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json-report", type=Path, required=True)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    args = parse_args()
    args.walks = resolve_path(args.walks)
    args.id_map = resolve_path(args.id_map)
    args.report = resolve_path(args.report)
    args.json_report = resolve_path(args.json_report)

    # Read id_map
    id_map: dict[str, str] = {}
    id_map_empty_tokens = 0
    with args.id_map.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            vid = (row.get("vid") or "").strip()
            token = (row.get("token") or "").strip()
            if not token:
                id_map_empty_tokens += 1
            if vid:
                id_map[vid] = token

    # Walk file stats
    line_count = 0
    empty_lines = 0
    walk_lengths: list[int] = []
    all_tokens: set[str] = set()
    dead_end_walks = 0

    max_lines = args.max_lines or 0
    with args.walks.open("r", encoding="utf-8") as fh:
        iterable = progress_iter(fh, "Check walks", "lines", max_lines or None) if max_lines else progress_iter(fh, "Check walks", "lines")
        for raw_line in iterable:
            if max_lines and line_count >= max_lines:
                break
            parts = raw_line.strip().split()
            line_count += 1
            if not parts:
                empty_lines += 1
                walk_lengths.append(0)
            else:
                walk_lengths.append(len(parts))
                all_tokens.update(parts)
                if len(parts) == 1:
                    dead_end_walks += 1

    walk_lengths_sorted = sorted(walk_lengths)
    total_walk_len = sum(walk_lengths)
    min_len = walk_lengths_sorted[0] if walk_lengths_sorted else 0
    max_len = walk_lengths_sorted[-1] if walk_lengths_sorted else 0
    avg_len = total_walk_len / line_count if line_count else 0.0
    p50_idx = len(walk_lengths_sorted) // 2
    p50 = walk_lengths_sorted[p50_idx] if walk_lengths_sorted else 0

    short_walks = sum(1 for l in walk_lengths if 0 < l < args.min_walk_len)
    tokens_not_in_id_map = all_tokens - set(id_map.values())
    id_map_tokens_not_in_walks = set(id_map.values()) - all_tokens - {""}

    checks = {
        "walk_file_exists": args.walks.exists(),
        "id_map_exists": args.id_map.exists(),
        "walk_line_count_positive": line_count > 0,
        "no_empty_lines": empty_lines == 0,
        "min_walk_length_ok": min_len >= args.min_walk_len,
        "id_map_no_empty_tokens": id_map_empty_tokens == 0,
        "all_walk_tokens_in_id_map": len(tokens_not_in_id_map) == 0,
    }
    status = "PASS" if all(checks.values()) else "FAIL"

    result = {
        "walk_file": str(args.walks),
        "id_map_file": str(args.id_map),
        "walk_line_count": line_count,
        "empty_line_count": empty_lines,
        "dead_end_walks": dead_end_walks,
        "short_walks_lt_min": short_walks,
        "min_walk_length": min_len,
        "max_walk_length": max_len,
        "avg_walk_length": avg_len,
        "p50_walk_length": p50,
        "unique_token_count": len(all_tokens),
        "id_map_token_count": len(id_map),
        "id_map_empty_tokens": id_map_empty_tokens,
        "tokens_not_in_id_map_count": len(tokens_not_in_id_map),
        "id_map_tokens_not_in_walks_count": len(id_map_tokens_not_in_walks),
        "checks": checks,
        "overall_status": status,
    }

    # Write reports
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as fh:
        fh.write("# TCG Walk File Check Report\n\n")
        fh.write(f"Overall status: **{status}**\n\n")
        fh.write("## Walk File Stats\n\n")
        fh.write("| Metric | Value |\n| --- | ---: |\n")
        fh.write(f"| `walk_line_count` | `{line_count}` |\n")
        fh.write(f"| `empty_line_count` | `{empty_lines}` |\n")
        fh.write(f"| `dead_end_walks` | `{dead_end_walks}` |\n")
        fh.write(f"| `short_walks_lt_{args.min_walk_len}` | `{short_walks}` |\n")
        fh.write(f"| `min_walk_length` | `{min_len}` |\n")
        fh.write(f"| `max_walk_length` | `{max_len}` |\n")
        fh.write(f"| `avg_walk_length` | `{avg_len:.4f}` |\n")
        fh.write(f"| `p50_walk_length` | `{p50}` |\n")
        fh.write(f"| `unique_token_count` | `{len(all_tokens)}` |\n")
        fh.write("\n## ID Map Stats\n\n")
        fh.write("| Metric | Value |\n| --- | ---: |\n")
        fh.write(f"| `id_map_token_count` | `{len(id_map)}` |\n")
        fh.write(f"| `id_map_empty_tokens` | `{id_map_empty_tokens}` |\n")
        fh.write(f"| `tokens_not_in_id_map` | `{len(tokens_not_in_id_map)}` |\n")
        fh.write(f"| `id_map_tokens_not_in_walks` | `{len(id_map_tokens_not_in_walks)}` |\n")
        fh.write("\n## Checks\n\n")
        fh.write("| Check | Result |\n| --- | --- |\n")
        for key, ok in checks.items():
            fh.write(f"| `{key}` | {'PASS' if ok else 'FAIL'} |\n")

    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"status": status, "checks": checks, "walk_line_count": line_count, "unique_tokens": len(all_tokens)}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
