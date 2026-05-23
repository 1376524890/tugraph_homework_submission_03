#!/usr/bin/env python3
"""Check a random-walk text file before word2vec training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_REPORT = Path("data/features/hcg/reports/hcg_walks_smoke_check.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize and validate an HCG walks file.")
    parser.add_argument("--walks", required=True, type=Path, help="Walks file, one walk per line.")
    parser.add_argument("--expected-min-lines", type=int, default=1000)
    parser.add_argument("--min-walk-len", type=int, default=2)
    parser.add_argument("--max-preview", type=int, default=10)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--json-report", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.walks.exists():
        raise FileNotFoundError(f"walks file not found: {args.walks}")

    line_count = 0
    empty_lines = 0
    len_one_count = 0
    total_len = 0
    min_len: int | None = None
    max_len = 0
    tokens: set[str] = set()
    preview: list[str] = []

    with args.walks.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if len(preview) < args.max_preview:
                preview.append(line)
            if not line.strip():
                empty_lines += 1
                length = 0
            else:
                parts = line.split()
                length = len(parts)
                tokens.update(parts)
            line_count += 1
            total_len += length
            min_len = length if min_len is None else min(min_len, length)
            max_len = max(max_len, length)
            if length == 1:
                len_one_count += 1

    avg_len = (total_len / line_count) if line_count else 0.0
    min_len_value = min_len if min_len is not None else 0
    len_one_ratio = (len_one_count / line_count) if line_count else 0.0
    checks = {
        "line_count_at_least_expected": line_count >= args.expected_min_lines,
        "no_empty_lines": empty_lines == 0,
        "min_walk_len_ok": min_len_value >= args.min_walk_len,
    }
    result = {
        "walks": str(args.walks),
        "line_count": line_count,
        "average_walk_length": avg_len,
        "min_walk_length": min_len_value,
        "max_walk_length": max_len,
        "unique_token_count": len(tokens),
        "empty_line_count": empty_lines,
        "length_one_walk_count": len_one_count,
        "length_one_walk_ratio": len_one_ratio,
        "expected_min_lines": args.expected_min_lines,
        "min_walk_len": args.min_walk_len,
        "checks": checks,
        "preview": preview,
    }

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as fh:
        fh.write("# HCG Walks Smoke Check\n\n")
        fh.write(f"- walks: `{args.walks}`\n")
        fh.write(f"- walk lines: {line_count}\n")
        fh.write(f"- average walk length: {avg_len:.4f}\n")
        fh.write(f"- min walk length: {min_len_value}\n")
        fh.write(f"- max walk length: {max_len}\n")
        fh.write(f"- unique token count: {len(tokens)}\n")
        fh.write(f"- empty line count: {empty_lines}\n")
        fh.write(f"- length-1 walk ratio: {len_one_ratio:.6f}\n\n")
        fh.write("## Checks\n\n")
        for name, ok in checks.items():
            fh.write(f"- {name}: {'PASS' if ok else 'FAIL'}\n")
        fh.write("\n## Preview\n\n")
        for line in preview:
            fh.write(f"```text\n{line}\n```\n")

    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
