# 图建模方案

实现基于 TuGraph Bolt 协议。TuGraph 兼容 Neo4j Bolt 驱动，脚本使用 `neo4j` Python 包连接环境变量 `TUGRAPH_URI` 指定的地址。TuGraph 子图需要显式指定 graph 名称，本机已探测到 `default`、`hw2`、`plk` 三个已有子图；本项目新建 `hcg` 和 `tcg`。

## HCG：`{IP, port}` 作为顶点

图：`hcg`

点类型：`Endpoint`

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `endpoint_id` | STRING | 主键，格式为 `IP:port`。 |
| `ip` | STRING | IP 地址。 |
| `port` | INT64 | 端口号。 |

边类型：`COMMUNICATES`

方向从源端点指向目的端点。由于 TuGraph 普通 `upsertEdge` 对同一对点同一边类型只保留一条边，HCG 在 Python 侧按 `(src_endpoint, dst_endpoint)` 聚合后写入。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `flow_count` | INT64 | 该通信方向上的流记录数。 |
| `first_seen`, `last_seen` | STRING | 首末出现时间。 |
| `protocol_names` | STRING | 抽样保留的应用协议名，逗号分隔。 |
| `total_fwd_packets`, `total_bwd_packets` | INT64 | 聚合包数。 |
| `total_fwd_bytes`, `total_bwd_bytes` | INT64 | 聚合字节数。 |
| `avg_duration` | DOUBLE | 平均流持续时间。 |

中间文件：

| 文件 | 内容 |
| --- | --- |
| `data/processed/hcg/endpoints.csv` | `Endpoint` 点数据。 |
| `data/processed/hcg/communicates.csv` | `COMMUNICATES` 边数据。 |

运行：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py --graph hcg --max-rows 10000
PYTHONPATH=src python3 scripts/create_hcg_db.py
PYTHONPATH=src python3 scripts/prepare_processed_csv.py --graph hcg
PYTHONPATH=src python3 scripts/create_hcg_db.py
```

## TCG：流作为顶点

图：`tcg`

点类型：`Flow`

`Flow.ID` 在数据集中重复，所以使用 CSV 行号字符串 `record_id` 作为主键，同时保留原始 `flow_id`。

边类型：`CAUSES`

TCG 的边表示流间因果关系。当前脚本采用可解释、可调参的规则：

1. 两条流共享同一个端点，即同一个 `{IP, port}` 同时出现在前后两条流的源或目的端点中。
2. 后一条流的时间戳不早于前一条流。
3. 时间差不超过 `--window-seconds`，默认 60 秒。
4. 每个共享端点最多连接最近 `--max-predecessors` 条前驱流，默认 3，避免边爆炸。

边属性包含 `relation_id`、`shared_endpoint`、`delta_seconds` 和 `rule`。`relation_id` 上建立 pair unique edge index，使同一对流之间可按不同共享端点区分边。

中间文件：

| 文件 | 内容 |
| --- | --- |
| `data/processed/tcg/flows.csv` | `Flow` 点数据。 |
| `data/processed/tcg/causes.csv` | `CAUSES` 边数据。 |

运行：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py --graph tcg --max-rows 10000
PYTHONPATH=src python3 scripts/create_tcg_db.py
PYTHONPATH=src python3 scripts/prepare_processed_csv.py --graph tcg --window-seconds 60 --max-predecessors 3
PYTHONPATH=src python3 scripts/create_tcg_db.py
```

`create_tcg_db.py` 从中间 CSV 入库时先写全部 `Flow` 顶点，再写 `CAUSES` 边，避免边引用尚未写入的顶点。

## 中间 CSV 与 Docker 存储

导入前先运行：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py --graph all
du -sh data/raw data/processed data/processed/hcg data/processed/tcg
```

这一步不会连接 TuGraph，只用于生成可检查、可复用的中间数据。当前数据集按默认 TCG 参数估算：

| 项 | 估算 |
| --- | ---: |
| 原始 CSV | 约 1.77 GB |
| HCG 中间 CSV | 约 0.23 GB |
| TCG 中间 CSV | 约 1.36 GB |
| 原始数据 + 中间 CSV | 约 3.35 GB |

TuGraph 数据文件、索引、事务日志和 Docker 写入层会继续增加空间占用。建议给数据库预留至少 8-12 GB；如果 Docker 默认数据盘空间不充足，应将 TuGraph 的数据目录通过 volume/bind mount 映射到宿主机的大容量目录。

## 连接参数

连接参数从 `.env` 读取，`.env` 已加入 `.gitignore`，不要提交真实账号密码。复制 `.env.example` 后填写本机配置即可。

| 参数 | 值 |
| --- | --- |
| URI | `TUGRAPH_URI` |
| 用户 | `TUGRAPH_USER` |
| 密码 | `TUGRAPH_PASSWORD` |

可通过命令行覆盖：`--uri`、`--user`、`--password`、`--graph`。

## 依据

TuGraph 官方开发指南说明：TuGraph 兼容 Neo4j Bolt 驱动；子图可用 `CALL dbms.graph.createGraph` 创建；schema 可用 `CALL db.createVertexLabelByJson` / `CALL db.createEdgeLabelByJson` 创建；批量导入可用 `CALL db.upsertVertex` / `CALL db.upsertEdge`。
