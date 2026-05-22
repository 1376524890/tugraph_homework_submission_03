#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tugraph_homework.common import DEFAULT_DATASET, endpoint_id, read_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect the Unicauca flow CSV structure.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--sample-rows", type=int, default=200_000)
    args = parser.parse_args()

    counters = {
        name: collections.Counter()
        for name in ("Protocol", "Label", "L7Protocol", "ProtocolName", "Source.Port", "Destination.Port")
    }
    endpoints: set[str] = set()
    flow_ids: set[str] = set()
    row_count = 0

    with args.csv.open(newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh)
        columns = reader.fieldnames or []
    for row_count, row in read_rows(args.csv):
        endpoints.add(endpoint_id(row["Source.IP"], row["Source.Port"]))
        endpoints.add(endpoint_id(row["Destination.IP"], row["Destination.Port"]))
        flow_ids.add(row["Flow.ID"])
        if row_count <= args.sample_rows:
            for name, counter in counters.items():
                counter[row.get(name, "")] += 1

    print(f"file={args.csv}")
    print(f"size_bytes={os.path.getsize(args.csv)}")
    print(f"columns={len(columns)}")
    print(f"rows={row_count}")
    print(f"unique_endpoints={len(endpoints)}")
    print(f"unique_flow_ids={len(flow_ids)}")
    print("column_names=" + ",".join(columns))
    for name, counter in counters.items():
        print(f"\n{name}")
        for value, count in counter.most_common(10):
            print(f"  {value!r}: {count}")


if __name__ == "__main__":
    main()
