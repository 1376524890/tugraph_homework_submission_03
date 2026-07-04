#!/usr/bin/env python3
"""从 A_raw_flow_features.parquet 流式生成规范化 flow parquet（TCG_FLOW_FIELDS 列），
供 build_tcg.py --relation-types CR,SHR 重建 TCG light_shrcr 变体。

背景
----
原始 Kaggle CSV（Dataset-Unicauca-Version2-87Atts.csv）已不在本地（data/raw 已清），
但 A parquet 含全部所需字段：src_endpoint/dst_endpoint 可拆出 ip:port，raw_protocol、
raw_timestamp_epoch、record_id 等齐备。

build_tcg.load_flows (scripts/build_tcg.py:75-82) 对 .parquet 输入直接
`pd.read_parquet → to_dict('records')`，**不做字段名映射**；只有 CSV 路径才经
flow_vertex() 把 Source.IP 等映射成 src_ip。因此直接喂 A parquet 会因列名不匹配
（A 是 src_endpoint/raw_protocol，classify_relation 期望 src_ip/protocol）而 KeyError。

本脚本把 A 的字段映射成 TCG_FLOW_FIELDS（src_ip/src_port/protocol/timestamp_epoch/...），
输出规范化 parquet，再由 build_tcg.py 正常消费。

流式 row-group 处理，峰值 ≈ 单 row group（~10万行），内存安全。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
A_PATH = ROOT / "data/features/hcg/classification/datasets/A_raw_flow_features.parquet"
OUT_DIR = ROOT / "data/processed/tcg_light_shrcr"
OUT_PATH = OUT_DIR / "flows_normalized.parquet"

# 须与 src/tugraph_homework/transform.py:60-80 TCG_FLOW_FIELDS 完全一致
TCG_FLOW_FIELDS = [
    "record_id", "flow_id", "src_endpoint", "dst_endpoint",
    "src_ip", "src_port", "dst_ip", "dst_port",
    "protocol", "timestamp", "timestamp_epoch",
    "duration", "fwd_packets", "bwd_packets", "fwd_bytes", "bwd_bytes",
    "l7_protocol", "protocol_name", "label",
]

# A parquet 中需要的列
A_COLS = [
    "record_id", "target", "src_endpoint", "dst_endpoint", "raw_protocol",
    "raw_flow_duration", "raw_total_fwd_packets", "raw_total_backward_packets",
    "raw_total_length_of_fwd_packets", "raw_total_length_of_bwd_packets",
    "raw_timestamp_epoch",
]


def _split_endpoint(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """ip:port 字符串拆成 (ip, port)。无冒号或端口非数字时 port=0。"""
    parts = series.astype(str).str.rsplit(":", n=1, expand=True)
    if parts.shape[1] == 1:
        ip, port = parts[0], pd.Series(["0"] * len(parts), index=parts.index)
    else:
        ip, port = parts[0], parts[1]
    port = pd.to_numeric(port, errors="coerce").fillna(0).astype(np.int64)
    return ip, port


def convert(df: pd.DataFrame) -> pd.DataFrame:
    src_ip, src_port = _split_endpoint(df["src_endpoint"])
    dst_ip, dst_port = _split_endpoint(df["dst_endpoint"])
    out = pd.DataFrame({
        "record_id": df["record_id"].astype(str),
        "flow_id": df["record_id"].astype(str),  # 非空占位（TuGraph 不接受空 STRING；Flow.ID 重复，用 record_id）
        "src_endpoint": df["src_endpoint"].astype(str),
        "dst_endpoint": df["dst_endpoint"].astype(str),
        "src_ip": src_ip,
        "src_port": src_port,
        "dst_ip": dst_ip,
        "dst_port": dst_port,
        "protocol": pd.to_numeric(df["raw_protocol"], errors="coerce").fillna(0).astype(np.int64),
        "timestamp": pd.to_datetime(df["raw_timestamp_epoch"].astype("int64"), unit="s").dt.strftime("%Y-%m-%d %H:%M:%S"),  # 非空，TuGraph 不接受空 STRING
        "timestamp_epoch": pd.to_numeric(df["raw_timestamp_epoch"], errors="coerce").fillna(0).astype(np.int64),
        "duration": pd.to_numeric(df["raw_flow_duration"], errors="coerce").fillna(0),
        "fwd_packets": pd.to_numeric(df["raw_total_fwd_packets"], errors="coerce").fillna(0).astype(np.int64),
        "bwd_packets": pd.to_numeric(df["raw_total_backward_packets"], errors="coerce").fillna(0).astype(np.int64),
        "fwd_bytes": pd.to_numeric(df["raw_total_length_of_fwd_packets"], errors="coerce").fillna(0).astype(np.int64),
        "bwd_bytes": pd.to_numeric(df["raw_total_length_of_bwd_packets"], errors="coerce").fillna(0).astype(np.int64),
        "l7_protocol": 0,      # A 无 L7 数值编码，不影响关系判定
        "protocol_name": df["target"].astype(str),  # 非空占位（用应用名）
        "label": df["target"].astype(str),
    })
    return out[TCG_FLOW_FIELDS]  # 强制列顺序


def main() -> int:
    if not A_PATH.exists():
        raise FileNotFoundError(A_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pf = pq.ParquetFile(A_PATH)
    num_rg = pf.metadata.num_row_groups
    print(f"[src] {A_PATH}")
    print(f"      row_groups={num_rg} reading_cols={len(A_COLS)}")

    writer = None
    total = 0
    for i in range(num_rg):
        tbl = pf.read_row_group(i, columns=A_COLS)
        out_df = convert(tbl.to_pandas())
        out_tbl = pa.Table.from_pandas(out_df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(OUT_PATH, out_tbl.schema)
        writer.write_table(out_tbl)
        total += len(out_df)
        if (i + 1) % 6 == 0 or (i + 1) == num_rg:
            print(f"  rg {i + 1}/{num_rg}: {total:,} rows", flush=True)
        del tbl, out_df, out_tbl

    writer.close()
    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    print(f"[done] {OUT_PATH}: {total:,} rows, {size_mb:.1f}MB")

    # 自检：列顺序、行数、src_port 分布
    chk = pq.ParquetFile(OUT_PATH)
    chk_cols = [chk.schema_arrow.field(j).name for j in range(len(chk.schema_arrow))]
    print(f"[check] cols_match={chk_cols == TCG_FLOW_FIELDS} rows={chk.metadata.num_rows}")
    sample = pq.read_table(OUT_PATH, columns=["src_ip", "src_port", "protocol"]).slice(0, 5).to_pandas()
    print(sample.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
