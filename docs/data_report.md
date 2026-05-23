# 数据与中间文件说明

本文档描述 HCG/TCG 构建结果的字段、输出位置、优化策略和最终导入验证。

## 原始数据

默认输入：

```text
data/raw/Dataset-Unicauca-Version2-87Atts.csv
```

检查命令：

```bash
PYTHONPATH=src python3 scripts/inspect_dataset.py
```

## 存储优化策略：精简属性 (2026-05-23)

为了应对服务器磁盘空间不足（仅剩 76GB）并支持 1.34 亿条 TCG 边的导入，本项目实施了**精简属性 (Streamlined Attributes)** 策略：

1. **源头剔除**：在 `transform.py` 中修改边生成逻辑，仅提取图拓扑和权重必须的核心字段。
2. **字段压缩**：TCG 边属性从 19 个缩减至 **9 个**，中间 CSV 大小从 33GB 降至 **14.6GB**。
3. **兼容性**：保留了 `relation_type`（支持路径过滤）和 `delta_seconds`（支持 node2vec 权重计算），完全满足后续向量化分析需求。

## CSV 生成功能状态

CSV 生成功能已全量完成。统一入口 `scripts/prepare_processed_csv.py` 从原始 CSV 生成中间文件.

全量 TCG 生成结果：

| 指标 | 结果 | 说明 |
| --- | ---: | --- |
| TCG Flow 顶点 | 3,577,296 | 匹配原始数据行数 |
| TCG CAUSES 边 | 134,240,414 | 含 CR, PR, DHR, SHR |
| TCG 边 CSV 总大小 | **14.6 GiB** | 已实施精简优化 |
| 总中间数据量 | 20.2 GiB | 位于 `data/processed` |

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
`endpoint_id, ip, port, is_private_ip, port_bucket, is_common_service_port, is_proxy_port`

COMMUNICATES 字段：
`edge_id, src_endpoint, dst_endpoint, source_id, target_id, flow_count, first_seen_epoch, last_seen_epoch, first_seen, last_seen, total_fwd_packets, total_bwd_packets, total_packets, total_fwd_bytes, total_bwd_bytes, total_bytes, avg_duration, min_duration, max_duration, protocol_set, protocol_name_set, major_protocol, major_protocol_name, protocol_entropy, l7_protocol_entropy`

## TCG 中间 CSV

生成命令：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph tcg \
  --output-root data/processed \
  --force-large-build
```

TCG 默认关系窗口：
`CR=5s, PR=1s, DHR=1s, SHR=5s`

输出文件：

| 文件或目录 | 内容 |
| --- | --- |
| `data/processed/tcg/flows.csv` | Flow 顶点。 |
| `data/processed/tcg/causes_full_parts/relation_type=*/` | 精简版因果边分区 CSV。 |
| `data/processed/reports/tcg_edge_estimation_report.md` | 边数量估算报告。 |

Flow 字段：
`record_id, flow_id, src_endpoint, dst_endpoint, src_ip, src_port, dst_ip, dst_port, protocol, timestamp, timestamp_epoch, duration, fwd_packets, bwd_packets, fwd_bytes, bwd_bytes, l7_protocol, protocol_name, label`

**精简版 CAUSES 字段 (9个)**：
`relation_id, src_record_id, dst_record_id, source_id, target_id, relation_type, relation_priority, delta_seconds, same_timestamp`

## TuGraph 导入与验证

HCG 和 TCG 数据已成功通过 `scripts/import_tugraph_native.py` 导入。

### 导入状态总结

| 项目 | 状态 | 详情 |
| --- | --- | --- |
| HCG 导入 | **成功** | 93.5k 顶点 / 1.7M 边 |
| TCG 导入 | **成功** | 3.57M 顶点 / 1.34亿 边 |
| 实时进度 | 已实现 | 支持 tqdm 进度条展示 |
| 磁盘可用余量 | 50 GiB+ | 导入后状态稳定 |
| 数据库目录大小 | **37 GiB** | 位于 `docker/tugraph-data` |

### 验证查询

TCG 最终验证结果：

```bash
PYTHONPATH=src python3 - <<'PY'
from neo4j import GraphDatabase
from tugraph_homework.common import DEFAULT_URI, DEFAULT_USER, DEFAULT_PASSWORD

driver = GraphDatabase.driver(DEFAULT_URI, auth=(DEFAULT_USER, DEFAULT_PASSWORD))
try:
    with driver.session(database="tcg") as session:
        print("Flow count =", session.run("MATCH (n:Flow) RETURN count(n) AS c").single()["c"])
finally:
    driver.close()
PY
```
输出：`Flow count = 3577296` (完全匹配 CSV)。

## 校验重点

- `flows.csv` 中 `record_id` 必须 unique。
- `CAUSES` 不包含自环。
- `relation_id` 必须唯一。
- 边属性仅保留 node2vec 核心字段以优化空间。
- **硬链接视图**：`docker/tugraph-import` 现为 `data/processed` 的硬链接视图，不再占用双倍空间。

更多图建模说明见 [docs/graph_modeling.md](docs/graph_modeling.md)。
