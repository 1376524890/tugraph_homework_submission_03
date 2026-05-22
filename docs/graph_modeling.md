# 图建模方案

实现基于 TuGraph Bolt 协议。TuGraph 兼容 Neo4j Bolt 驱动，脚本使用 `neo4j` Python 包连接环境变量 `TUGRAPH_URI` 指定的地址。本项目默认子图为 `hcg` 和 `tcg`。

## HCG：`{IP, port}` 作为顶点

HCG 表示为 `G(V, E)`。将 `{IP, port}` 抽象为 `Endpoint` 顶点；若两个端点之间存在 flow 通信，则建立一条有向 `COMMUNICATES` 边。

点类型：`Endpoint`

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `endpoint_id` | STRING | 主键，格式为 `IP:port`。 |
| `ip` | STRING | IP 地址。 |
| `port` | INT64 | 端口号。 |
| `is_private_ip` | BOOL | 是否私有地址。 |
| `port_bucket` | STRING | `well_known`、`registered`、`dynamic` 或 `invalid`。 |
| `is_common_service_port` | BOOL | 是否常见服务端口。 |
| `is_proxy_port` | BOOL | 是否常见代理端口。 |

边类型：`COMMUNICATES`

方向从源端点指向目的端点。Python 侧按 `(src_endpoint, dst_endpoint)` 聚合，每个端点对只保留一条有向边。

| 属性 | 说明 |
| --- | --- |
| `edge_id` | `src_endpoint`、`dst_endpoint`、`COMMUNICATES` 的稳定 hash。 |
| `src_endpoint`, `dst_endpoint` | 边两端端点。 |
| `flow_count` | 该通信方向上的流记录数。 |
| `first_seen_epoch`, `last_seen_epoch` | 首末出现时间戳。 |
| `first_seen`, `last_seen` | 首末出现时间文本。 |
| `total_fwd_packets`, `total_bwd_packets`, `total_packets` | 聚合包数。 |
| `total_fwd_bytes`, `total_bwd_bytes`, `total_bytes` | 聚合字节数。 |
| `avg_duration`, `min_duration`, `max_duration` | 流持续时间统计。 |
| `protocol_set`, `protocol_name_set` | 去重协议集合。 |
| `major_protocol`, `major_protocol_name` | 出现次数最多的协议。 |
| `protocol_entropy`, `l7_protocol_entropy` | 协议分布 Shannon entropy。 |

实现限制：当前数据是 flow 级统计数据，不是报文级数据。若原始数据缺少 TCP flags 或 SYN 字段，HCG 采用 flow-level HCG approximation，不伪造 SYN 判断，也不能严格按 TCP SYN 触发建边。

运行：

```bash
PYTHONPATH=src python3 scripts/build_hcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --output data/rebuild/hcg
```

## TCG：flow 作为顶点

TCG 中的顶点表示网络流 flow，边表示 flow 间的因果关系。新版 TCG 仅按 CR、PR、DHR、SHR 四类关系建边。

点类型：`Flow`

`Flow.ID` 在数据集中重复，所以不能作为主键。脚本使用 `record_id` 作为主键；如果输入没有 `record_id`，则按原始行号生成 `rec_0000000001` 形式的稳定 ID，并将原始 `flow_id` 作为普通属性保留。

Flow 至少包含：

| 属性 |
| --- |
| `record_id`, `flow_id`, `src_endpoint`, `dst_endpoint` |
| `src_ip`, `src_port`, `dst_ip`, `dst_port` |
| `protocol`, `timestamp`, `timestamp_epoch`, `duration` |
| `fwd_packets`, `bwd_packets`, `fwd_bytes`, `bwd_bytes` |
| `l7_protocol`, `protocol_name`, `label` |

边类型：`CAUSES`

关系优先级：`CR = 1`、`PR = 2`、`DHR = 3`、`SHR = 4`。如果同一对 flow 同时满足多个关系，只保留优先级最高的 `relation_type`。

| 关系 | 规则 | 含义 |
| --- | --- | --- |
| `CR` | 协议相同，五元组方向相反 | 请求/响应或一对一直接通信。 |
| `PR` | `dstIp(f1) == srcIp(f2)` | 传播、代理、转发或链式访问。 |
| `DHR` | `srcIp(f1) == srcIp(f2)` 且 `srcPort(f1) != srcPort(f2)` | 同源主机动态端口关系。 |
| `SHR` | `srcIp(f1) == srcIp(f2)` 且 `srcPort(f1) == srcPort(f2)` | 同源主机静态端口关系。 |

边方向由时间确定。较早 flow 指向较晚 flow；时间相同则按 `record_id` 字典序确定方向。`delta_seconds` 只保存为边属性，不作为构图过滤条件。

CAUSES 至少包含：

| 属性 |
| --- |
| `relation_id`, `src_record_id`, `dst_record_id` |
| `relation_type`, `relation_priority`, `delta_seconds`, `same_timestamp` |
| `matched_rule`, `src_flow_timestamp_epoch`, `dst_flow_timestamp_epoch` |
| `shared_ip`, `shared_endpoint` |
| `src_ip_pair`, `src_port_pair`, `dst_ip_pair`, `dst_port_pair`, `protocol_pair` |

`relation_id` 使用 `hash(src_record_id, dst_record_id, relation_type)` 生成，避免重复。

## TCG 边数量估算

新版 TCG 全量构图阶段不使用 `window_seconds`，不做 `delta_seconds <= 60` 或 `delta_seconds <= 300` 过滤，也不使用 `max_predecessors` 截断。PR、DHR、SHR 可能产生大量边，因此应先运行估算：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode estimate \
  --output data/rebuild/tcg
```

估算报告输出到：

```text
data/rebuild/reports/tcg_edge_estimation_report.md
```

## TCG 分区写出

仅生成 CR 做检查：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode build \
  --relation-types CR \
  --output data/rebuild/tcg \
  --output-format parquet \
  --partition-by relation_type
```

全量分区生成：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode build \
  --relation-types CR,PR,DHR,SHR \
  --output data/rebuild/tcg \
  --output-format parquet \
  --partition-by relation_type \
  --chunk-size 1000000
```

输出目录：

```text
data/rebuild/tcg/causes_full_parts/relation_type=CR/
data/rebuild/tcg/causes_full_parts/relation_type=PR/
data/rebuild/tcg/causes_full_parts/relation_type=DHR/
data/rebuild/tcg/causes_full_parts/relation_type=SHR/
```

这些分区是无时间窗口约束的 full TCG 构图结果。

## delta_seconds 查询视图

时间过滤只属于查询、采样、实验或嵌入训练阶段。示例：

```bash
PYTHONPATH=src python3 scripts/query_tcg_by_delta.py \
  --input data/rebuild/tcg/causes_full_parts \
  --output data/rebuild/tcg/query_views/causes_delta_60s.parquet \
  --max-delta-seconds 60 \
  --relation-types CR,PR,DHR,SHR
```

`causes_delta_60s.parquet`、`causes_delta_300s.parquet`、`causes_delta_3600s.parquet` 是查询阶段派生子图，不是原始 TCG 构图结果。

## 与旧版图的差异

旧版 TCG 使用 `shared_endpoint_time_window`：两条流共享端点且时间差在窗口内就建边，并在构图阶段使用默认 60 秒窗口和最多 3 个前驱限制。该规则曾导致报告中出现默认 60 秒窗口但 `delta_seconds` 最大值为 7873 秒的现象，因此不再作为论文对齐版 TCG。

新版 TCG 使用 CR、PR、DHR、SHR 四类因果关系；`causes_full` 不带时间窗口，`delta_seconds` 只作为边属性保存。下游实验必须明确使用的是 `causes_full` 还是 `causes_delta_60s` 等查询视图。
