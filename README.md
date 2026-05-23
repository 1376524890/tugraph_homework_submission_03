# TuGraph Homework Submission 03

本项目基于 Unicauca 87 属性网络流数据集，构建两类可导入 TuGraph 的图数据：

- HCG：Host Communication Graph，以 `{IP, port}` 端点为顶点，以端点之间的聚合通信关系为有向边。
- TCG：Traffic Causality Graph，以每条 flow 记录为顶点，以 flow 之间的 CR、PR、DHR、SHR 因果关系为有向边。

实验过程统一维护在 [docs/experiment_record.md](docs/experiment_record.md)。本 README 只保留当前可复现流程，不描述版本切换或旧方案。

## 1. 目录说明

| 路径 | 说明 |
| --- | --- |
| `data/raw/` | 原始数据，只作为输入读取。默认文件为 `Dataset-Unicauca-Version2-87Atts.csv`。 |
| `data/processed/hcg/` | HCG 中间 CSV：`endpoints.csv`、`communicates.csv`。 |
| `data/processed/tcg/` | TCG 中间 CSV：`flows.csv`、`causes_full_parts/`。 |
| `data/processed/reports/` | TCG 边数量估算报告。 |
| `data/exports/` | 查询视图或导出结果。 |
| `docker/tugraph-data/` | Docker Compose 挂载到 `/var/lib/lgraph/data` 的 TuGraph 数据目录。 |
| `docker/tugraph-logs/` | Docker Compose 挂载到 `/var/log/lgraph_log` 的 TuGraph 日志目录。 |
| `docker/tugraph-import/` | Docker Compose 挂载到 `/import` 的原生导入 CSV 目录。 |
| `docker/tugraph-tmp/` | Docker Compose 挂载到 `/tmp` 的临时目录，避免大文件写入 Docker overlay。 |
| `scripts/` | 数据检查、CSV 生成、查询视图、TuGraph 原生导入入口脚本。 |
| `src/tugraph_homework/` | 共享转换和通用工具代码。 |
| `docs/` | 数据结构、目录规划、图建模说明和实验记录。 |

## 2. 数据描述

默认原始数据文件：

```text
data/raw/Dataset-Unicauca-Version2-87Atts.csv
```

当前数据规模：

| 指标 | 值 |
| --- | ---: |
| 原始 CSV 大小 | 1,767,404,086 bytes |
| 数据行数 | 3,577,296 |
| 字段数 | 87 |
| 唯一 `{IP, port}` 端点数 | 935,600 |
| 唯一 `Flow.ID` 数 | 1,522,917 |

`Flow.ID` 会重复，不能作为 TCG 顶点主键。脚本使用 `record_id` 作为 Flow 主键；当输入缺少 `record_id` 时，按原始行号生成稳定 ID，例如 `rec_0000000001`。

检查数据：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/inspect_dataset.py --sample-rows 200000
```

HCG 建模：

| 元素 | 说明 |
| --- | --- |
| `Endpoint` 顶点 | 每个 `{IP, port}` 端点一个顶点，主键为 `endpoint_id`。 |
| `COMMUNICATES` 边 | 按 `(src_endpoint, dst_endpoint)` 聚合的有向通信边。 |

TCG 建模：

| 元素 | 说明 |
| --- | --- |
| `Flow` 顶点 | 每条 flow 记录一个顶点，主键为 `record_id`。 |
| `CAUSES` 边 | flow 之间按 CR、PR、DHR、SHR 规则生成的有向因果边。 |

TCG 关系规则：

| 关系 | 窗口 | 规则 |
| --- | ---: | --- |
| `CR` | 5 秒 | 协议相同，五元组方向相反。 |
| `PR` | 1 秒 | `dstIp(f1) == srcIp(f2)`。 |
| `DHR` | 1 秒 | `srcIp(f1) == srcIp(f2)` 且 `srcPort(f1) != srcPort(f2)`。 |
| `SHR` | 5 秒 | `srcIp(f1) == srcIp(f2)` 且 `srcPort(f1) == srcPort(f2)`。 |

同一对 flow 同时满足多个关系时，只采用优先级最高的关系，优先级为 `CR > PR > DHR > SHR`。边方向由时间决定：较早 flow 指向较晚 flow；时间相同时按 `record_id` 字典序确定方向。`delta_seconds` 作为边属性保存。

当前全量 TCG 估算：

| 指标 | 值 |
| --- | ---: |
| Flow 数 | 3,577,296 |
| CR 候选边 | 346,014 |
| PR 候选边 | 46,946,678 |
| DHR 候选边 | 54,938,804 |
| SHR 候选边 | 40,990,482 |
| 候选边总数 | 143,221,978 |
| 预估 CSV 大小 | 24.01 GiB |

## 3. 环境和容器

脚本通过 `PYTHONPATH=src` 运行。TuGraph 导入入口通过 Bolt 确认目标图，通过 Docker 调用原生 `lgraph_import` 导入 CSV，因此本地 Python 环境需要 `neo4j` 驱动。

安装依赖：

```bash
python3 -m pip install neo4j -i https://mirrors.aliyun.com/pypi/simple
```

TuGraph 服务由仓库根目录的 Docker Compose 管理：

```bash
cd /home/marktom/tugraph
docker compose up -d
docker compose ps
```

确认挂载：

```bash
docker exec tugraph-db sh -lc 'for p in /var/lib/lgraph/data /var/log/lgraph_log /import /tmp; do printf "%s -> " "$p"; df -h "$p" | tail -1; done'
```

期望挂载关系：

```text
tugraph_homework_submission_03/docker/tugraph-data   -> /var/lib/lgraph/data
tugraph_homework_submission_03/docker/tugraph-logs   -> /var/log/lgraph_log
tugraph_homework_submission_03/docker/tugraph-import -> /import
tugraph_homework_submission_03/docker/tugraph-tmp    -> /tmp
```

`/tmp` 应显示在宿主机 `/home` 所在文件系统上，而不是 Docker overlay。

## 4. CSV 生成

CSV 统一由 `scripts/prepare_processed_csv.py` 生成。该脚本只生成中间文件，不连接 TuGraph，也不写入 TuGraph 数据目录。

生成提交目录下的 HCG 和 TCG CSV：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph all \
  --output-root data/processed \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

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

给 TuGraph 原生导入准备 CSV 时，输出到 Docker 挂载目录：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph all \
  --output-root docker/tugraph-import \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

导入目录结构：

```text
docker/tugraph-import/hcg/endpoints.csv
docker/tugraph-import/hcg/communicates.csv
docker/tugraph-import/tcg/flows.csv
docker/tugraph-import/tcg/causes_full_parts/relation_type=CR/*.csv
docker/tugraph-import/tcg/causes_full_parts/relation_type=PR/*.csv
docker/tugraph-import/tcg/causes_full_parts/relation_type=DHR/*.csv
docker/tugraph-import/tcg/causes_full_parts/relation_type=SHR/*.csv
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

当前 smoke test 结果：

| 输出 | 结果 |
| --- | ---: |
| HCG Endpoint | 1,297 |
| HCG COMMUNICATES | 1,471 |
| TCG Flow | 2,000 |
| TCG CR 边 | 686 |
| TCG PR 边 | 27,132 |
| TCG DHR 边 | 17,516 |
| TCG SHR 边 | 43,352 |

TCG 生成会先估算候选边数量。如果超过 `--max-candidate-edges`，脚本会停止构建并保留估算报告；确认磁盘和运行时间足够后，再提高阈值或使用 `--force-large-build`。

## 5. 导入执行

HCG 和 TCG 统一使用 `scripts/import_tugraph_native.py`。脚本会：

1. 生成 `docker/tugraph-import/<graph-type>/import.json`。
2. 通过 Bolt 确保目标图存在。
3. 通过 Docker Compose 停止 `tugraph-db`。
4. 启动临时 Docker 容器执行 `lgraph_import`。
5. 通过 Docker Compose 重新启动 `tugraph-db`。

导入脚本会给临时导入容器挂载：

```text
docker/tugraph-data   -> /var/lib/lgraph/data
docker/tugraph-import -> /import
docker/tugraph-tmp    -> /tmp
```

### 5.1 HCG 导入

预演 HCG 导入：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg --dry-run
```

首次执行 HCG 导入：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg
```

如果当前环境已经导入过 HCG，再次导入需要显式确认覆盖：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg --force
```

验证 HCG 点边数量：

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

当前 HCG 验证结果：

```text
Endpoint=935600
COMMUNICATES=1716084
```

### 5.2 TCG 导入

TCG 全量导入数据量明显大于 HCG。执行前确认 `/home` 可用空间、`docker/tugraph-import` 文件完整性和 `/tmp` 挂载：

```bash
cd /home/marktom/tugraph
df -h /home
du -sh tugraph_homework_submission_03/docker/tugraph-import
docker exec tugraph-db sh -lc 'df -h /var/lib/lgraph/data /import /tmp'
docker exec tugraph-db sh -lc 'ls -lh /import/tcg/import.json /import/tcg/flows.csv; find /import/tcg/causes_full_parts -type f -name "*.csv" | wc -l'
```

当前 TCG 导入文件状态：

| 项目 | 值 |
| --- | ---: |
| `docker/tugraph-import/tcg/flows.csv` 行数，含表头 | 3,577,297 |
| `docker/tugraph-import/tcg/causes_full_parts/**/*.csv` 分片数 | 135 |
| `docker/tugraph-import/tcg/import.json` 配置文件数 | 136 |

预演 TCG 导入：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --dry-run
```

首次执行 TCG 导入：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg
```

如果当前环境已经导入过 TCG，再次导入需要显式确认覆盖：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --force
```

验证 TCG 点边数量：

```bash
PYTHONPATH=src python3 - <<'PY'
from neo4j import GraphDatabase
from tugraph_homework.common import DEFAULT_URI, DEFAULT_USER, DEFAULT_PASSWORD

driver = GraphDatabase.driver(DEFAULT_URI, auth=(DEFAULT_USER, DEFAULT_PASSWORD))
try:
    with driver.session(database="tcg") as session:
        print("Flow=", session.run("MATCH (n:Flow) RETURN count(n) AS c").single()["c"])
        print("CAUSES=", session.run("MATCH ()-[r:CAUSES]->() RETURN count(r) AS c").single()["c"])
finally:
    driver.close()
PY
```

预期 Flow 数为 `3,577,296`。CAUSES 边数以实际生成的 `causes_full_parts` 为准，当前 CSV 校验记录为 `134,240,414`。

### 5.3 导入后服务检查

每次导入完成后执行：

```bash
cd /home/marktom/tugraph
docker compose ps
curl --max-time 5 -s -o /tmp/tugraph-http-body -w 'http_code=%{http_code}\n' http://127.0.0.1:7070/
timeout 3 bash -lc '</dev/tcp/127.0.0.1/7687' && echo bolt_port_open
```

TuGraph 停止或启动过程中可能输出 Python plugin 的 `KeyboardInterrupt` 日志，这是服务停止时插件任务进程被中断的日志。只要 `docker compose ps` 显示服务运行、HTTP/Bolt 检查通过、点边数量可查询，即可认为导入流程完成。

## 6. 查询视图

查询视图从 TCG 的 `causes_full_parts` 派生，用于按 `delta_seconds`、关系类型和前驱/后继数量生成子图：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
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

## 7. 校验重点

- `flows.csv` 中的 `record_id` 必须唯一。
- `flow_id` 只作为普通属性，不作为 Flow 主键。
- `CAUSES` 不包含自环。
- `relation_id` 必须唯一。
- `delta_seconds` 作为边属性保存；查询视图可按该字段继续过滤。
- TCG 构建前先查看 `data/processed/reports/tcg_edge_estimation_report.md`。

更多字段说明见 [docs/graph_modeling.md](docs/graph_modeling.md)、[docs/dataset_structure.md](docs/dataset_structure.md) 和 [docs/data_report.md](docs/data_report.md)。
