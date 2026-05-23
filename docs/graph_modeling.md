# 图建模方案

本项目构建 HCG 和 TCG 两类图，并生成可导入 TuGraph 的中间 CSV 文件。

## HCG

HCG 表示为 `G(V, E)`。`V` 中每个顶点是 `{IP, port}` Endpoint；若两个端点之间存在 flow 通信，则在源端点到目的端点之间建立一条有向 `COMMUNICATES` 边。

Endpoint 字段：

| 字段 | 说明 |
| --- | --- |
| `endpoint_id` | `ip:port` 主键。 |
| `ip` | IP 地址。 |
| `port` | 端口号。 |
| `is_private_ip` | 是否私有地址。 |
| `port_bucket` | `well_known`、`registered`、`dynamic` 或 `invalid`。 |
| `is_common_service_port` | 是否常见服务端口。 |
| `is_proxy_port` | 是否常见代理端口。 |

COMMUNICATES 边按 `(src_endpoint, dst_endpoint)` 聚合，每个有向端点对只保留一条边。

边字段包括：

```text
edge_id, src_endpoint, dst_endpoint, source_id, target_id, flow_count,
first_seen_epoch, last_seen_epoch, first_seen, last_seen,
total_fwd_packets, total_bwd_packets, total_packets,
total_fwd_bytes, total_bwd_bytes, total_bytes,
avg_duration, min_duration, max_duration,
protocol_set, protocol_name_set,
major_protocol, major_protocol_name,
protocol_entropy, l7_protocol_entropy
```

HCG 是 flow-level approximation。原始数据是流级统计数据；如果缺少 TCP flags 或 SYN 字段，则不能严格按 TCP SYN 触发建边。

## TCG

TCG 中每条 flow 记录是一个 `Flow` 顶点，主键为 `record_id`。如果输入没有 `record_id`，脚本按原始行号生成稳定 ID，例如 `rec_0000000001`。`flow_id` 只作为普通属性保存。

Flow 字段：

```text
record_id, flow_id, src_endpoint, dst_endpoint,
src_ip, src_port, dst_ip, dst_port,
protocol, timestamp, timestamp_epoch, duration,
fwd_packets, bwd_packets, fwd_bytes, bwd_bytes,
l7_protocol, protocol_name, label
```

TCG 边为 `CAUSES`，只使用四类关系：

| 关系 | 优先级 | 规则 |
| --- | ---: | --- |
| `CR` | 1 | 协议相同，五元组方向相反。 |
| `PR` | 2 | `dstIp(f1) == srcIp(f2)`。 |
| `DHR` | 3 | `srcIp(f1) == srcIp(f2)` 且 `srcPort(f1) != srcPort(f2)`。 |
| `SHR` | 4 | `srcIp(f1) == srcIp(f2)` 且 `srcPort(f1) == srcPort(f2)`。 |

同一对 flow 同时满足多个关系时，只保留优先级最高的关系。边方向由时间决定：较早 flow 指向较晚 flow；时间相同时按 `record_id` 字典序确定方向。

构建窗口：

| 关系 | 窗口 |
| --- | ---: |
| `CR` | 5 秒 |
| `PR` | 1 秒 |
| `DHR` | 1 秒 |
| `SHR` | 5 秒 |

CAUSES 字段：

```text
relation_id, src_record_id, dst_record_id, source_id, target_id,
relation_type, relation_priority, delta_seconds, same_timestamp,
matched_rule, src_flow_timestamp_epoch, dst_flow_timestamp_epoch,
shared_ip, shared_endpoint,
src_ip_pair, src_port_pair, dst_ip_pair, dst_port_pair, protocol_pair
```

`delta_seconds` 是边属性，并可用于查询阶段继续过滤。

## 中间 CSV

CSV 生成功能已实现并可独立运行，不需要连接 TuGraph。统一入口是
`scripts/prepare_processed_csv.py`：

- `--graph hcg` 只生成 HCG CSV。
- `--graph tcg` 只生成 TCG CSV。
- `--graph all` 同时生成 HCG 和 TCG CSV。

小样本验证命令：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph all \
  --output-root /tmp/tugraph_csv_smoke \
  --max-rows 2000 \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 5000 \
  --max-candidate-edges 10000000
```

全量 CSV 生成命令：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph all \
  --output-root data/processed \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

HCG 输出：

```text
data/processed/hcg/endpoints.csv
data/processed/hcg/communicates.csv
```

TCG 输出：

```text
data/processed/tcg/flows.csv
data/processed/tcg/causes_full_parts/relation_type=CR/*.csv
data/processed/tcg/causes_full_parts/relation_type=PR/*.csv
data/processed/tcg/causes_full_parts/relation_type=DHR/*.csv
data/processed/tcg/causes_full_parts/relation_type=SHR/*.csv
```

TCG CSV 生成前会先估算候选边数量并写出
`data/processed/reports/tcg_edge_estimation_report.md`。如果估算数量超过
`--max-candidate-edges`，脚本会拒绝继续构建；确认磁盘和时间预算后再提高阈值
或显式使用 `--force-large-build`。

TCG 建议先估算：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode estimate \
  --output data/processed/tcg
```

## 查询视图

查询视图可按 `delta_seconds` 继续过滤：

```bash
PYTHONPATH=src python3 scripts/query_tcg_by_delta.py \
  --input data/processed/tcg/causes_full_parts \
  --output data/processed/tcg/query_views/causes_delta_5s.parquet \
  --max-delta-seconds 5 \
  --relation-types CR,PR,DHR,SHR
```

查询视图是从 `causes_full_parts` 派生出来的子图，用于后续实验或嵌入训练。
