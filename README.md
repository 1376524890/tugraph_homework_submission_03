# TuGraph Homework Submission 03

本项目基于 Unicauca 87 属性网络流数据集，生成两类可用于 TuGraph 导入和后续分析的图数据：

- HCG：Host Communication Graph，以 `{IP, port}` 端点为顶点，以端点之间的聚合通信关系为有向边。
- TCG：Traffic Causality Graph，以每条 flow 记录为顶点，以 flow 之间的 CR、PR、DHR、SHR 因果关系为有向边。

默认原始数据文件：

```text
data/raw/Dataset-Unicauca-Version2-87Atts.csv
```

## 目录

| 路径 | 说明 |
| --- | --- |
| `data/raw/` | 原始数据，只作为输入读取。 |
| `data/rebuild/hcg/` | HCG 中间文件：`endpoints.csv`、`communicates.csv`。 |
| `data/rebuild/tcg/` | TCG 中间文件：`flows.csv`、`causes_full_parts/`。 |
| `data/rebuild/reports/` | TCG 边数量估算报告。 |
| `data/exports/` | 导出结果。 |
| `scripts/` | 数据检查、构图、查询视图和 TuGraph 导入脚本。 |
| `src/tugraph_homework/` | 共享转换和导入工具代码。 |
| `docs/` | 数据结构、目录规划和图建模说明。 |

## 环境

脚本通过 `PYTHONPATH=src` 运行。生成 Parquet 或读取 Parquet 查询视图时需要 `pandas` 和 `pyarrow`；导入 TuGraph 时需要 `neo4j` Python 驱动。

TuGraph 连接信息可写入本地 `.env`：

```bash
cp .env.example .env
```

## 数据检查

查看数据规模、字段和关键字段统计：

```bash
PYTHONPATH=src python3 scripts/inspect_dataset.py --sample-rows 200000
```

## 资源预估

当前数据集共 3,577,296 条 flow，原始 CSV 约 1.7G。本机环境为 4 核 CPU、约 10 GiB 可用内存、`/home` 剩余约 115G。以下预估基于当前数据文件的流式统计结果：

| 步骤 | 规模 | 预计落盘 | 预计耗时 | 风险 |
| --- | ---: | ---: | ---: | --- |
| 数据检查 | 读取 CSV 抽样或全量扫描 | 不新增大文件 | 数十秒到数分钟 | 低 |
| HCG 构建 | 935,600 个端点，1,716,084 条聚合边 | 约 0.7G 到 1.5G | 约数分钟 | 中低 |
| TCG 估算 | 3,577,296 条 flow 计数统计 | 仅报告文件 | 约 2 到 4 分钟 | 低 |
| TCG 全关系构建 | 约 143,221,978 条候选边 | Parquet 约 8.40 GiB，CSV 约 24.01 GiB | 预计较长 | 中高 |
| TCG 查询视图 | 取决于输入边文件和过滤条件 | 通常小于输入边文件 | 分钟级到小时级 | 取决于输入规模 |
| TuGraph 导入 HCG | 约 265 万条点边记录 | TuGraph 存储会大于 CSV | 分钟级到十几分钟 | 中 |
| TuGraph 导入 TCG | 约 357 万 Flow 点和按窗口生成的 CAUSES 边 | TuGraph 存储会大于中间文件 | 取决于边数量 | 中高 |

TCG 构建按关系使用时间窗口：`CR=5,PR=1,DHR=1,SHR=5`。`delta_seconds` 会作为边属性保存。脚本设置了候选边安全阈值：估算的待构建边数超过 `--max-candidate-edges` 时会拒绝执行 build。当前全关系构建需要把阈值设置到 150,000,000 以上。

推荐安全运行方式：

```bash
nice -n 10 ionice -c2 -n7 env PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode estimate \
  --output data/rebuild/tcg
```

## HCG

HCG 将每个 `{IP, port}` 端点建模为 `Endpoint` 顶点。任意两个端点之间只要存在 flow 通信，就按 `(src_endpoint, dst_endpoint)` 聚合为一条有向 `COMMUNICATES` 边。

生成 HCG 中间 CSV：

```bash
PYTHONPATH=src python3 scripts/build_hcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --output data/rebuild/hcg
```

输出文件：

```text
data/rebuild/hcg/endpoints.csv
data/rebuild/hcg/communicates.csv
```

HCG 使用 flow 级统计数据近似通信关系。原始数据如缺少 TCP flags 或 SYN 字段，脚本不会构造额外的 SYN 判定。

## TCG

TCG 将每条 flow 记录建模为 `Flow` 顶点，主键为 `record_id`。如果输入数据没有 `record_id`，脚本会按原始行号生成稳定 ID，例如 `rec_0000000001`。原始 `flow_id` 作为普通属性写入。

`CAUSES` 边使用四类关系，优先级为 `CR > PR > DHR > SHR`：

| 关系 | 规则 |
| --- | --- |
| `CR` | 协议相同，五元组方向相反。 |
| `PR` | `dstIp(f1) == srcIp(f2)`。 |
| `DHR` | `srcIp(f1) == srcIp(f2)` 且 `srcPort(f1) != srcPort(f2)`。 |
| `SHR` | `srcIp(f1) == srcIp(f2)` 且 `srcPort(f1) == srcPort(f2)`。 |

同一对 flow 同时满足多个关系时，只采用优先级最高的关系。边方向由时间决定：较早 flow 指向较晚 flow；时间相同时按 `record_id` 字典序确定方向。`delta_seconds` 作为边属性保存。

构建窗口：

| 关系 | 窗口 |
| --- | ---: |
| `CR` | 5 秒 |
| `PR` | 1 秒 |
| `DHR` | 1 秒 |
| `SHR` | 5 秒 |

先估算 TCG 边数量：

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

生成小规模检查结果：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode build \
  --relation-types CR \
  --output data/rebuild/tcg \
  --output-format parquet \
  --partition-by relation_type
```

生成完整 TCG 分区结果：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode build \
  --relation-types CR,PR,DHR,SHR \
  --output data/rebuild/tcg \
  --output-format parquet \
  --partition-by relation_type \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

输出目录：

```text
data/rebuild/tcg/flows.parquet
data/rebuild/tcg/causes_full_parts/relation_type=CR/
data/rebuild/tcg/causes_full_parts/relation_type=PR/
data/rebuild/tcg/causes_full_parts/relation_type=DHR/
data/rebuild/tcg/causes_full_parts/relation_type=SHR/
```

全关系构建推荐使用 Parquet 输出。

## 统一 CSV 生成

CSV 生成功能已完成，统一入口是 `scripts/prepare_processed_csv.py`。该脚本只生成
中间 CSV，不连接 TuGraph，也不写入 TuGraph 数据目录。需要一次性生成 HCG 和 TCG
的 CSV 中间文件时，可以运行：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph all \
  --output-root data/rebuild \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

小样本 smoke test：

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

当前验证结果：HCG 生成 1,297 个 Endpoint、1,471 条 COMMUNICATES；TCG 生成
2,000 个 Flow，以及 CR=686、PR=27,132、DHR=17,516、SHR=43,352 条 CAUSES
边。输出表头与字段定义一致，并按 `causes_full_parts/relation_type=*/part-*.csv`
分区。

输出结构：

```text
data/rebuild/hcg/endpoints.csv
data/rebuild/hcg/communicates.csv
data/rebuild/tcg/flows.csv
data/rebuild/tcg/causes_full_parts/relation_type=CR/*.csv
data/rebuild/tcg/causes_full_parts/relation_type=PR/*.csv
data/rebuild/tcg/causes_full_parts/relation_type=DHR/*.csv
data/rebuild/tcg/causes_full_parts/relation_type=SHR/*.csv
data/rebuild/reports/tcg_edge_estimation_report.md
```

TCG 生成会先估算候选边数量；如果超过 `--max-candidate-edges` 会停止构建并保留
估算报告。确认磁盘和运行时间足够后，再提高阈值或使用 `--force-large-build`。

## 查询视图

查询视图从 `causes_full_parts` 派生，用于按 `delta_seconds`、关系类型和前驱/后继数量生成子图：

```bash
PYTHONPATH=src python3 scripts/query_tcg_by_delta.py \
  --input data/rebuild/tcg/causes_full_parts \
  --output data/rebuild/tcg/query_views/causes_delta_5s.parquet \
  --max-delta-seconds 5 \
  --relation-types CR,PR,DHR,SHR
```

报告会写到查询视图旁边：

```text
data/rebuild/tcg/query_views/causes_delta_5s.parquet.report.md
```

## TuGraph 导入

TCG 边数量较大，推荐使用 TuGraph 原生 `lgraph_import` 导入 CSV。Bolt 写入适合 HCG、小样本 TCG 或导入链路验证，不适合全量 TCG。

生成 TCG CSV：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph tcg \
  --output-root docker/tugraph-import \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

生成 `lgraph_import` 配置：

```bash
PYTHONPATH=src python3 scripts/create_tugraph_import_config.py \
  --graph-type tcg \
  --processed-dir docker/tugraph-import/tcg \
  --local-import-root docker/tugraph-import \
  --container-import-root /import \
  --output docker/tugraph-import/tcg/import.json
```

运行原生导入时，容器需要能访问 `/import`。当前运行中的 `tugraph-db` 容器没有挂载 `docker/tugraph-import`，因此需要使用带 `/import` 挂载的容器运行 `lgraph_import`，或重新启动 TuGraph 容器时加入该挂载。离线导入会写入数据库目录，运行前先停止正在使用同一数据目录的 TuGraph 服务。

```bash
set -a
. ./.env
set +a

docker stop tugraph-db

docker run --rm \
  -v "$PWD/docker/tugraph-data:/var/lib/lgraph/data" \
  -v "$PWD/docker/tugraph-import:/import" \
  custom-tugraph-runtime:latest \
  lgraph_import \
  --dir /var/lib/lgraph/data \
  --config_file /import/tcg/import.json \
  --graph tcg \
  --user "$TUGRAPH_USER" \
  --password "$TUGRAPH_PASSWORD"

docker start tugraph-db
```

Bolt 导入 HCG：

```bash
PYTHONPATH=src python3 scripts/create_hcg_db.py \
  --processed-dir data/rebuild/hcg \
  --progress-interval 500000
```

Bolt 导入 TCG 小样本：

```bash
PYTHONPATH=src python3 scripts/create_tcg_db.py \
  --processed-dir data/rebuild/tcg \
  --progress-interval 500000
```

Bolt 脚本依赖 `neo4j` Python 驱动；Parquet 生成或读取依赖 `pandas` 和 `pyarrow`。当前全量 TCG CSV 预估约 24.01 GiB，TuGraph 导入后存储会进一步放大，运行前应确认磁盘空间和目标图容量。

## 校验重点

- `flows.csv` 或 `flows.parquet` 中的 `record_id` 必须唯一。
- `flow_id` 不作为 Flow 主键。
- `CAUSES` 不包含自环。
- `relation_id` 必须唯一。
- `delta_seconds` 作为边属性保存；查询视图可按该字段继续过滤。
- TCG 构建前先查看 `data/rebuild/reports/tcg_edge_estimation_report.md`。

更多字段说明见 [docs/graph_modeling.md](docs/graph_modeling.md) 和 [docs/data_report.md](docs/data_report.md)。
