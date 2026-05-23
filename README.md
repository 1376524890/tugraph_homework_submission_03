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
| `data/processed/hcg/` | HCG 中间文件：`endpoints.csv`、`communicates.csv`。 |
| `data/processed/tcg/` | TCG 中间文件：`flows.csv`、`causes_full_parts/`。 |
| `data/processed/reports/` | TCG 边数量估算报告。 |
| `data/exports/` | 导出结果。 |
| `scripts/` | 数据检查、构图、查询视图和 TuGraph 原生导入入口脚本。 |
| `src/tugraph_homework/` | 共享转换和通用工具代码。 |
| `docs/` | 数据结构、目录规划、图建模说明和唯一实验记录。 |

实验过程统一维护在 [docs/experiment_record.md](docs/experiment_record.md)。后续数据下载、处理、校验、导入和查询实验只追加或更新这一个实验记录文档，避免多份记录相互不一致。

## 环境与容器启动

脚本通过 `PYTHONPATH=src` 运行。生成 Parquet 或读取 Parquet 查询视图时需要 `pandas` 和 `pyarrow`；TuGraph 导入入口通过 Bolt 创建图、通过 Docker 调用原生 `lgraph_import` 导入 CSV，因此需要 `neo4j` Python 驱动和 Docker。

TuGraph 连接信息可写入本地 `.env`：

```bash
cp .env.example .env
```

TuGraph 服务由仓库根目录的 `docker-compose.yml` 管理。根目录 `.env` 已指定作业目录下的持久化路径，启动时会自动挂载数据、日志、导入目录和临时目录：

```bash
cd ..
docker compose up -d
```

挂载关系：

```text
tugraph_homework_submission_03/docker/tugraph-data   -> /var/lib/lgraph/data
tugraph_homework_submission_03/docker/tugraph-logs   -> /var/log/lgraph_log
tugraph_homework_submission_03/docker/tugraph-import -> /import
tugraph_homework_submission_03/docker/tugraph-tmp    -> /tmp
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
| TuGraph 原生导入 HCG | 约 265 万条点边记录 | TuGraph 存储会大于 CSV | 分钟级 | 中 |
| TuGraph 原生导入 TCG | 约 357 万 Flow 点和按窗口生成的 CAUSES 边 | TuGraph 存储会大于中间文件 | 取决于边数量 | 中高 |

TCG 构建按关系使用时间窗口：`CR=5,PR=1,DHR=1,SHR=5`。`delta_seconds` 会作为边属性保存。脚本设置了候选边安全阈值：估算的待构建边数超过 `--max-candidate-edges` 时会拒绝执行 build。当前全关系构建需要把阈值设置到 150,000,000 以上。

推荐安全运行方式：

```bash
nice -n 10 ionice -c2 -n7 env PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode estimate \
  --output data/processed/tcg
```

## HCG

HCG 将每个 `{IP, port}` 端点建模为 `Endpoint` 顶点。任意两个端点之间只要存在 flow 通信，就按 `(src_endpoint, dst_endpoint)` 聚合为一条有向 `COMMUNICATES` 边。

生成 HCG 中间 CSV：

```bash
PYTHONPATH=src python3 scripts/build_hcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --output data/processed/hcg
```

输出文件：

```text
data/processed/hcg/endpoints.csv
data/processed/hcg/communicates.csv
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
  --output data/processed/tcg
```

估算报告输出到：

```text
data/processed/reports/tcg_edge_estimation_report.md
```

生成小规模检查结果：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode build \
  --relation-types CR \
  --output data/processed/tcg \
  --output-format parquet \
  --partition-by relation_type
```

生成完整 TCG 分区结果：

```bash
PYTHONPATH=src python3 scripts/build_tcg.py \
  --input data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --mode build \
  --relation-types CR,PR,DHR,SHR \
  --output data/processed/tcg \
  --output-format parquet \
  --partition-by relation_type \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

输出目录：

```text
data/processed/tcg/flows.parquet
data/processed/tcg/causes_full_parts/relation_type=CR/
data/processed/tcg/causes_full_parts/relation_type=PR/
data/processed/tcg/causes_full_parts/relation_type=DHR/
data/processed/tcg/causes_full_parts/relation_type=SHR/
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
  --output-root data/processed \
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
data/processed/hcg/endpoints.csv
data/processed/hcg/communicates.csv
data/processed/tcg/flows.csv
data/processed/tcg/causes_full_parts/relation_type=CR/*.csv
data/processed/tcg/causes_full_parts/relation_type=PR/*.csv
data/processed/tcg/causes_full_parts/relation_type=DHR/*.csv
data/processed/tcg/causes_full_parts/relation_type=SHR/*.csv
data/processed/reports/tcg_edge_estimation_report.md
```

TCG 生成会先估算候选边数量；如果超过 `--max-candidate-edges` 会停止构建并保留
估算报告。确认磁盘和运行时间足够后，再提高阈值或使用 `--force-large-build`。

## 查询视图

查询视图从 `causes_full_parts` 派生，用于按 `delta_seconds`、关系类型和前驱/后继数量生成子图：

```bash
PYTHONPATH=src python3 scripts/query_tcg_by_delta.py \
  --input data/processed/tcg/causes_full_parts \
  --output data/processed/tcg/query_views/causes_delta_5s.parquet \
  --max-delta-seconds 5 \
  --relation-types CR,PR,DHR,SHR
```

报告会写到查询视图旁边：

```text
data/processed/tcg/query_views/causes_delta_5s.parquet.report.md
```

## TuGraph 导入

HCG 和 TCG 数据统一使用 `scripts/import_tugraph_native.py`。该脚本先通过 Bolt
确保目标图存在，再通过 Docker Compose 停止 `tugraph-db`，用 TuGraph 原生
`lgraph_import` 导入 CSV，最后通过 Docker Compose 启动服务。Bolt 不写入 CSV 数据。

手动复现前确认当前 Python 环境可导入 Bolt 驱动：

```bash
python3 -m pip install neo4j -i https://mirrors.aliyun.com/pypi/simple
```

启动 TuGraph 服务并确认挂载：

```bash
cd /home/marktom/tugraph
docker compose up -d
docker compose ps
docker exec tugraph-db sh -lc 'for p in /var/lib/lgraph/data /var/log/lgraph_log /import /tmp; do printf "%s -> " "$p"; df -h "$p" | tail -1; done'
```

`/tmp` 应显示在宿主机 `/home` 所在文件系统上，而不是 Docker overlay。

生成 HCG 和 TCG CSV：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph all \
  --output-root docker/tugraph-import \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

导入前可先打印实际会执行的 Docker 命令：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py \
  --graph-type hcg \
  --dry-run
```

执行 HCG 导入：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg
```

如果当前环境已经导入过 HCG，再次复现导入时需要显式确认覆盖：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg --force
```

导入后验证 HCG 点边数量：

```bash
PYTHONPATH=src python3 - <<'PY'
from neo4j import GraphDatabase
from tugraph_homework.common import DEFAULT_URI, DEFAULT_USER, DEFAULT_PASSWORD

driver = GraphDatabase.driver(DEFAULT_URI, auth=(DEFAULT_USER, DEFAULT_PASSWORD))
try:
    with driver.session(database="hcg") as session:
        print("Endpoint=", session.run("MATCH (n:Endpoint) RETURN count(n) AS c").single()["c"])
        print("COMMUNICATES=", session.run("MATCH ()-[r:COMMUNICATES]->() RETURN count(r) AS c").single()["c"])
finally:
    driver.close()
PY
```

当前 HCG 导入验证结果应为：

```text
Endpoint=935600
COMMUNICATES=1716084
```

导入脚本会生成 `docker/tugraph-import/<graph-type>/import.json`。服务容器由
Docker Compose 自动挂载 `/import` 和 `/tmp`；临时导入容器也使用同一组
`docker/tugraph-import:/import`、`docker/tugraph-tmp:/tmp` 挂载，避免大规模导入
临时文件写入 Docker overlay。当前全量 TCG CSV 预估约 24.01 GiB，TuGraph 导入后
存储会进一步放大；TCG 全量导入前应确认磁盘空间和目标图容量。

## 校验重点

- `flows.csv` 或 `flows.parquet` 中的 `record_id` 必须唯一。
- `flow_id` 不作为 Flow 主键。
- `CAUSES` 不包含自环。
- `relation_id` 必须唯一。
- `delta_seconds` 作为边属性保存；查询视图可按该字段继续过滤。
- TCG 构建前先查看 `data/processed/reports/tcg_edge_estimation_report.md`。

更多字段说明见 [docs/graph_modeling.md](docs/graph_modeling.md) 和 [docs/data_report.md](docs/data_report.md)。
