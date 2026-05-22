# TuGraph 数据导入报告

> 生成时间: 2026-05-22
> 数据集: Unicauca 87 属性网络流 (Dataset-Unicauca-Version2-87Atts)
> 原始记录数: 3,577,296 条
> TuGraph 地址: bolt://localhost:7687

---

## 1. 总览

| 维度 | HCG (主机通信图) | TCG (流量因果图) |
|------|------------------|------------------|
| 子图名 | `hcg` | `tcg` |
| 顶点标签 | Endpoint | Flow |
| 顶点数 | 935,600 | 3,577,296 |
| 边标签 | COMMUNICATES | CAUSES |
| 边数 | 1,716,084 | 8,762,187 |
| 点边比 | 1:1.83 | 1:2.45 |
| 顶点属性数 | 3 | 15 |
| 边属性数 | 9 | 4 |
| 索引总数 | 3 | 8 |
| 数据完整率 | 100% | 100% |

---

## 2. HCG — 主机通信图 (Host Communication Graph)

以 `{IP, Port}` 端点为顶点，端点间的聚合通信关系为边。

### 2.1 Endpoint 顶点

| 指标 | 值 |
|------|-----|
| 总数 | **935,600** |
| 去重 IP 数 | 23,513 |
| 端口范围 | 0 ~ 65,534 |
| 去重端口数 | 40,979 |

**属性定义:**

| 属性 | 类型 | 可选 | 索引 | 说明 |
|------|------|------|------|------|
| `endpoint_id` | STRING | 否 | unique | 主键，格式 `IP:Port` |
| `ip` | STRING | 否 | 普通 | IP 地址 |
| `port` | INT64 | 否 | 普通 | 端口号 |

**Top 10 IP (按端点数):**

| IP | 端点数 |
|----|--------|
| 10.200.7.199 | 28,089 |
| 10.200.7.218 | 28,049 |
| 10.200.7.217 | 27,941 |
| 10.200.7.195 | 27,831 |
| 10.200.7.194 | 27,732 |
| 10.200.7.196 | 27,677 |
| 192.168.90.98 | 8,835 |
| 192.168.180.14 | 7,781 |
| 192.168.112.14 | 5,437 |
| 192.168.90.65 | 4,816 |

### 2.2 COMMUNICATES 边

| 指标 | 值 |
|------|-----|
| 总数 | **1,716,084** |
| 约束 | Endpoint → Endpoint |

**属性定义:**

| 属性 | 类型 | 可选 | 索引 | 说明 |
|------|------|------|------|------|
| `flow_count` | INT64 | 否 | — | 聚合的流数量 |
| `first_seen` | STRING | 是 | — | 首次通信时间 |
| `last_seen` | STRING | 是 | — | 最近通信时间 |
| `protocol_names` | STRING | 是 | — | 涉及的协议列表 |
| `total_fwd_packets` | INT64 | 否 | — | 正向包总数 |
| `total_bwd_packets` | INT64 | 否 | — | 反向包总数 |
| `total_fwd_bytes` | INT64 | 否 | — | 正向字节总数 |
| `total_bwd_bytes` | INT64 | 否 | — | 反向字节总数 |
| `avg_duration` | DOUBLE | 否 | — | 平均持续时间 (ms) |

**聚合统计:**

| 指标 | 最小值 | 最大值 | 平均值 | 总和 |
|------|--------|--------|--------|------|
| flow_count | 1 | 368 | 2.08 | 3,577,296 |
| total_fwd_bytes | — | — | 97,627 | 167,536,312,611 |
| total_bwd_bytes | — | — | 176,057 | 302,129,206,737 |
| avg_duration (ms) | — | — | 15,729,475 | — |

**协议分布 (按边数):**

| 协议 | 边数 | 占比 |
|------|------|------|
| GOOGLE | 425,061 | 24.8% |
| HTTP | 348,864 | 20.3% |
| HTTP_PROXY | 239,023 | 13.9% |
| SSL | 203,783 | 11.9% |
| HTTP_CONNECT | 177,015 | 10.3% |
| YOUTUBE | 95,877 | 5.6% |
| AMAZON | 51,439 | 3.0% |
| MICROSOFT | 36,732 | 2.1% |
| WINDOWS_UPDATE | 24,304 | 1.4% |
| SKYPE | 15,720 | 0.9% |

**度数统计:**

| 指标 | 值 |
|------|-----|
| 平均出度 / 入度 | 1.83 |
| Top 出度节点 | 10.200.7.9:3128 (44,838) |
| Top 入度节点 | 10.200.7.8:3128 (143,098) |

**Top 5 出度节点:**

| 端点 | 出度 |
|------|------|
| 10.200.7.9:3128 | 44,838 |
| 10.200.7.8:3128 | 41,459 |
| 10.200.7.4:3128 | 40,990 |
| 10.200.7.6:3128 | 39,670 |
| 10.200.7.5:3128 | 39,137 |

**Top 5 入度节点:**

| 端点 | 入度 |
|------|------|
| 10.200.7.8:3128 | 143,098 |
| 10.200.7.7:3128 | 127,403 |
| 10.200.7.9:3128 | 124,700 |
| 10.200.7.5:3128 | 111,630 |
| 10.200.7.6:3128 | 106,710 |

---

## 3. TCG — 流量因果图 (Traffic Causality Graph)

> 说明：本节中已有的边数量、`shared_endpoint_time_window`、默认 60s 窗口和最多 3 个前驱统计属于旧版 TCG 结果，仅用于历史对照。论文对齐版 TCG 已改为 CR、PR、DHR、SHR 四类因果关系构图，构图阶段不使用时间窗口，也不使用 `max_predecessors` 截断。`delta_seconds` 仅作为边属性，供查询视图、采样、实验和嵌入训练阶段过滤。

以每条网络流为顶点，流之间通过共享端点和时间窗口建立的因果关系为边。

### 3.1 Flow 顶点

| 指标 | 值 |
|------|-----|
| 总数 | **3,577,296** |
| 去重源端点数 | 865,950 |
| 去重目标端点数 | 297,327 |
| 去重 flow_id 数 | 1,522,917 |

**属性定义:**

| 属性 | 类型 | 可选 | 索引 | 说明 |
|------|------|------|------|------|
| `record_id` | STRING | 否 | unique | 主键，记录序号 |
| `flow_id` | STRING | 否 | 普通 | 流标识 |
| `src_endpoint` | STRING | 否 | 普通 | 源端点 `IP:Port` |
| `dst_endpoint` | STRING | 否 | 普通 | 目标端点 `IP:Port` |
| `protocol` | INT64 | 否 | — | 传输层协议号 |
| `timestamp` | STRING | 是 | — | 时间戳文本 |
| `timestamp_epoch` | INT64 | 否 | 普通 | Unix 时间戳 |
| `duration` | DOUBLE | 否 | — | 流持续时间 (ms) |
| `fwd_packets` | INT64 | 否 | — | 正向包数 |
| `bwd_packets` | INT64 | 否 | — | 反向包数 |
| `fwd_bytes` | INT64 | 否 | — | 正向字节数 |
| `bwd_bytes` | INT64 | 否 | — | 反向字节数 |
| `label` | STRING | 是 | — | 流量标签 |
| `l7_protocol` | INT64 | 否 | — | L7 协议编号 |
| `protocol_name` | STRING | 是 | 普通 | L7 协议名称 |

**传输层协议分布:**

| 协议号 | 条数 | 占比 | 说明 |
|--------|------|------|------|
| 6 | 3,572,975 | 99.88% | TCP |
| 17 | 2,684 | 0.07% | UDP |
| 0 | 1,637 | 0.05% | 未知 |

**L7 协议分布 (Top 10):**

| L7 协议 | 条数 | 占比 |
|---------|------|------|
| GOOGLE | 959,110 | 26.8% |
| HTTP | 683,734 | 19.1% |
| HTTP_PROXY | 623,210 | 17.4% |
| SSL | 404,883 | 11.3% |
| HTTP_CONNECT | 317,526 | 8.9% |
| YOUTUBE | 170,781 | 4.8% |
| AMAZON | 86,875 | 2.4% |
| MICROSOFT | 54,710 | 1.5% |
| GMAIL | 40,260 | 1.1% |
| WINDOWS_UPDATE | 34,471 | 1.0% |

**标签分布:**

| 标签 | 条数 | 占比 |
|------|------|------|
| BENIGN | 3,577,296 | 100% |

**流量统计:**

| 指标 | 值 |
|------|-----|
| 总正向包数 | 223,144,541 |
| 总反向包数 | 233,743,492 |
| 总正向字节数 | 167,536,312,611 (~156 GB) |
| 总反向字节数 | 302,129,206,737 (~281 GB) |
| 平均持续时间 | 25,442,466 ms |

### 3.2 CAUSES 边

| 指标 | 值 |
|------|-----|
| 总数 | **8,762,187** |
| 约束 | Flow → Flow |
| 生成规则 | 旧版：shared_endpoint_time_window (默认 60s 窗口, 最多 3 个前驱) |

新版 TCG 的 `CAUSES` 边定义如下：

| 字段 | 新版规则 |
|------|----------|
| 顶点 | 每条原始 flow 记录为一个 `Flow` 节点，主键为 `record_id`；`flow_id` 仅作为普通属性。 |
| 关系类型 | `CR`, `PR`, `DHR`, `SHR` |
| 优先级 | `CR = 1`, `PR = 2`, `DHR = 3`, `SHR = 4` |
| 时间处理 | 构图阶段不按 `delta_seconds` 过滤；较早 flow 指向较晚 flow，同时间按 `record_id` 排序。 |
| 查询视图 | `causes_delta_60s.parquet`、`causes_delta_300s.parquet` 等是派生子图，不是原始 TCG。 |

**属性定义:**

| 属性 | 类型 | 可选 | 索引 | 说明 |
|------|------|------|------|------|
| `relation_id` | STRING | 否 | unique | 关系唯一标识 |
| `shared_endpoint` | STRING | 否 | 普通 | 共享端点 |
| `delta_seconds` | INT64 | 否 | — | 时间差 (秒) |
| `rule` | STRING | 否 | — | 因果推断规则 |

**delta_seconds 统计:**

| 指标 | 值 |
|------|-----|
| 最小值 | 0 |
| 最大值 | 7,873 |
| 平均值 | 67.36 |

**度数统计:**

| 指标 | 值 |
|------|-----|
| 平均出度 / 入度 | 2.45 |

**Top 10 共享端点 (因果枢纽):**

| 共享端点 | 因果边数 | 占比 |
|----------|----------|------|
| 10.200.7.8:3128 | 875,712 | 10.0% |
| 10.200.7.7:3128 | 865,652 | 9.9% |
| 10.200.7.9:3128 | 740,254 | 8.4% |
| 10.200.7.6:3128 | 625,111 | 7.1% |
| 10.200.7.5:3128 | 621,007 | 7.1% |
| 10.200.7.4:3128 | 589,289 | 6.7% |
| 64.233.186.189:443 | 66,239 | 0.8% |
| 64.233.190.189:443 | 61,090 | 0.7% |
| 104.91.156.236:80 | 52,502 | 0.6% |
| 179.1.4.210:443 | 51,398 | 0.6% |

---

## 4. 文件存储

| 路径 | 大小 | 说明 |
|------|------|------|
| `data/raw/Dataset-Unicauca-Version2-87Atts.csv` | ~1.9 GB | 原始数据 |
| `data/processed/hcg/endpoints.csv` | 37 MB | HCG 端点 |
| `data/processed/hcg/communicates.csv` | 183 MB | HCG 通信边 |
| `data/processed/tcg/flows.csv` | 531 MB | TCG 流顶点 |
| `data/processed/tcg/causes.csv` | 815 MB | TCG 因果边 |
| **合计** | **~3.4 GB** | |

---

## 5. Schema 对比

### HCG Schema

```
Endpoint (VERTEX)
  ├── endpoint_id : STRING  [PK, unique index]
  ├── ip          : STRING  [index]
  └── port        : INT64   [index]

COMMUNICATES (EDGE: Endpoint → Endpoint)
  ├── flow_count        : INT64
  ├── first_seen        : STRING  (optional)
  ├── last_seen         : STRING  (optional)
  ├── protocol_names    : STRING  (optional)
  ├── total_fwd_packets : INT64
  ├── total_bwd_packets : INT64
  ├── total_fwd_bytes   : INT64
  ├── total_bwd_bytes   : INT64
  └── avg_duration      : DOUBLE
```

### TCG Schema

```
Flow (VERTEX)
  ├── record_id      : STRING  [PK, unique index]
  ├── flow_id        : STRING  [index]
  ├── src_endpoint   : STRING  [index]
  ├── dst_endpoint   : STRING  [index]
  ├── protocol       : INT64
  ├── timestamp      : STRING  (optional)
  ├── timestamp_epoch: INT64   [index]
  ├── duration       : DOUBLE
  ├── fwd_packets    : INT64
  ├── bwd_packets    : INT64
  ├── fwd_bytes      : INT64
  ├── bwd_bytes      : INT64
  ├── label          : STRING  (optional)
  ├── l7_protocol    : INT64
  └── protocol_name  : STRING  [index, optional]

CAUSES (EDGE: Flow → Flow)
  ├── relation_id              : STRING  [unique index]
  ├── src_record_id            : STRING  [index]
  ├── dst_record_id            : STRING  [index]
  ├── relation_type            : STRING  [index]
  ├── relation_priority        : INT64
  ├── delta_seconds            : INT64   [index]
  ├── same_timestamp           : BOOL
  ├── matched_rule             : STRING
  ├── src_flow_timestamp_epoch : INT64
  ├── dst_flow_timestamp_epoch : INT64
  ├── shared_ip                : STRING  [index]
  ├── shared_endpoint          : STRING  [index]
  ├── src_ip_pair              : STRING
  ├── src_port_pair            : STRING
  ├── dst_ip_pair              : STRING
  ├── dst_port_pair            : STRING
  └── protocol_pair            : STRING
```

---

## 6. 建模思路

### HCG (Host Communication Graph)

- **顶点**: 每个 `{IP, Port}` 二元组为一个 Endpoint 节点
- **边**: 两个端点之间的所有流聚合为一条 COMMUNICATES 边，携带流量统计
- **适用场景**: 端点通信行为分析、网络拓扑发现、异常主机检测

### TCG (Traffic Causality Graph)

- **顶点**: 每条原始网络流记录为一个 Flow 节点，`record_id` 为主键，`flow_id` 不作为主键
- **边**: 两条流满足 `CR`、`PR`、`DHR`、`SHR` 之一时建立 `CAUSES` 因果边
- **时间处理**: 构图阶段不使用 `window_seconds`，不做 `delta_seconds <= 60/300` 过滤，不使用 `max_predecessors`
- **查询视图**: 后续按 `delta_seconds` 过滤得到 `causes_delta_60s.parquet` 等派生子图
- **适用场景**: 攻击链追踪、流量因果推理、横向移动检测
