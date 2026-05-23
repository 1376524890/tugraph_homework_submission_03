# 数据与中间文件说明

本文档描述 HCG/TCG 构建结果的字段、输出位置和校验重点。

## 原始数据

默认输入：

```text
data/raw/Dataset-Unicauca-Version2-87Atts.csv
```

检查命令：

```bash
PYTHONPATH=src python3 scripts/inspect_dataset.py
```

## CSV 生成功能状态

CSV 生成功能已完成并通过小样本验证。统一入口
`scripts/prepare_processed_csv.py` 会从原始 CSV 直接生成 HCG/TCG 中间 CSV，
不需要连接 TuGraph，也不会写入 TuGraph 数据目录。

已验证的 smoke test：

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

验证结果：

| 输出 | 结果 |
| --- | ---: |
| HCG Endpoint | 1,297 |
| HCG COMMUNICATES | 1,471 |
| TCG Flow | 2,000 |
| TCG CR 边 | 686 |
| TCG PR 边 | 27,132 |
| TCG DHR 边 | 17,516 |
| TCG SHR 边 | 43,352 |

生成的 CSV 表头已与代码字段定义一致；`--chunk-size 5000` 下 TCG 边按
`causes_full_parts/relation_type=*/part-*.csv` 分片输出。

## HCG 中间 CSV

生成命令：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph hcg \
  --output-root data/processed
```

输出文件：

| 文件 | 内容 |
| --- | --- |
| `data/processed/hcg/endpoints.csv` | Endpoint 顶点。 |
| `data/processed/hcg/communicates.csv` | COMMUNICATES 聚合边。 |

Endpoint 字段：

```text
endpoint_id, ip, port, is_private_ip, port_bucket,
is_common_service_port, is_proxy_port
```

COMMUNICATES 字段：

```text
edge_id, src_endpoint, dst_endpoint, source_id, target_id,
flow_count, first_seen_epoch, last_seen_epoch, first_seen, last_seen,
total_fwd_packets, total_bwd_packets, total_packets,
total_fwd_bytes, total_bwd_bytes, total_bytes,
avg_duration, min_duration, max_duration,
protocol_set, protocol_name_set,
major_protocol, major_protocol_name,
protocol_entropy, l7_protocol_entropy
```

## TCG 中间 CSV

TCG 可以单独估算，也可以通过统一入口生成 CSV。全量 CSV 生成前建议先估算：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode estimate \
  --output data/processed/tcg
```

生成命令：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph tcg \
  --output-root data/processed \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

`--relation-max-delta-seconds` 默认值为 `CR=5,PR=1,DHR=1,SHR=5`。如果估算的
候选边数量超过 `--max-candidate-edges`，脚本会停止并保留估算报告；确认资源
足够后再提高阈值或使用 `--force-large-build`。

TCG 默认关系窗口：

| 关系 | 窗口 |
| --- | ---: |
| `CR` | 5 秒 |
| `PR` | 1 秒 |
| `DHR` | 1 秒 |
| `SHR` | 5 秒 |

输出文件：

| 文件或目录 | 内容 |
| --- | --- |
| `data/processed/tcg/flows.csv` | Flow 顶点。 |
| `data/processed/tcg/causes_full_parts/relation_type=CR/*.csv` | CR 因果边分区。 |
| `data/processed/tcg/causes_full_parts/relation_type=PR/*.csv` | PR 因果边分区。 |
| `data/processed/tcg/causes_full_parts/relation_type=DHR/*.csv` | DHR 因果边分区。 |
| `data/processed/tcg/causes_full_parts/relation_type=SHR/*.csv` | SHR 因果边分区。 |
| `data/processed/reports/tcg_edge_estimation_report.md` | TCG 边数量估算报告。 |

Flow 字段：

```text
record_id, flow_id, src_endpoint, dst_endpoint,
src_ip, src_port, dst_ip, dst_port,
protocol, timestamp, timestamp_epoch, duration,
fwd_packets, bwd_packets, fwd_bytes, bwd_bytes,
l7_protocol, protocol_name, label
```

CAUSES 字段：

```text
relation_id, src_record_id, dst_record_id, source_id, target_id,
relation_type, relation_priority, delta_seconds, same_timestamp,
matched_rule, src_flow_timestamp_epoch, dst_flow_timestamp_epoch,
shared_ip, shared_endpoint,
src_ip_pair, src_port_pair, dst_ip_pair, dst_port_pair, protocol_pair
```

## 查询视图

查询视图由 `causes_full_parts` 派生：

```bash
PYTHONPATH=src python3 scripts/query_tcg_by_delta.py \
  --input data/processed/tcg/causes_full_parts \
  --output data/processed/tcg/query_views/causes_delta_5s.parquet \
  --max-delta-seconds 5 \
  --relation-types CR,PR,DHR,SHR
```

输出报告会写在查询视图旁边，例如：

```text
data/processed/tcg/query_views/causes_delta_5s.parquet.report.md
```

## 校验重点

- `flows.csv` 中 `record_id` 必须唯一。
- `flow_id` 只作为普通属性，不作为主键。
- `CAUSES` 不应包含自环。
- `relation_id` 必须唯一。
- `delta_seconds` 是边属性；查询视图可以按它继续过滤。
- TCG 运行前先查看估算报告。

## TuGraph 导入

HCG 和 TCG 数据统一使用 `scripts/import_tugraph_native.py`。该脚本通过 Bolt
确保目标图存在，通过 Docker 调用 TuGraph 原生 `lgraph_import` 导入 CSV，不通过
Bolt 写入数据。

TuGraph 服务由仓库根目录的 Docker Compose 配置启动。Compose 会自动挂载
`docker/tugraph-data`、`docker/tugraph-logs`、`docker/tugraph-import` 和
`docker/tugraph-tmp`，其中 `/tmp` 使用宿主机目录，避免原生导入临时文件写入
Docker overlay。

启动服务：

```bash
cd ..
docker compose up -d
```

预演 HCG 导入命令：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py \
  --graph-type hcg \
  --dry-run
```

执行 HCG 导入：

```bash
set -a
. ./.env
set +a

PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg
```

TCG 全量导入使用同一入口，但执行前需要重新确认磁盘空间：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg
```
