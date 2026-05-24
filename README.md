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

**重要：精简属性导入（针对 TCG）**
由于 TCG 边数据量极大，为了在有限磁盘空间内完成导入并支持 node2vec 任务，本项目采用了**精简属性**策略。导入器会从包含 19 个字段的 CSV 中提取核心 9 个字段，自动忽略冗余描述性字段。

### 5.1 HCG 导入

生成配置并执行导入：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
# 1. 生成 HCG 导入配置
PYTHONPATH=src python3 scripts/create_tugraph_import_config.py \
  --graph-type hcg \
  --processed-dir data/processed/hcg \
  --output docker/tugraph-import/hcg/import.json

# 2. 执行 HCG 导入
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

当前 HCG 验证结果：`Endpoint=935600`, `COMMUNICATES=1716084`。

### 5.2 TCG 导入

**策略说明**：
TCG 边仅保留 `relation_id`, `record_id`, `relation_type`, `relation_priority`, `delta_seconds` 等核心结构。这能减少约 60% 的存储空间，且完全支持 node2vec 随机游走。

执行前确认可用空间：

```bash
df -h /home  # 建议剩余空间 > 80GB
```

执行导入流程：

```bash
# 1. 生成精简版 TCG 导入配置（此步会根据最新 Schema 定义映射字段）
PYTHONPATH=src python3 scripts/create_tugraph_import_config.py \
  --graph-type tcg \
  --processed-dir data/processed/tcg \
  --output docker/tugraph-import/tcg/import.json

# 2. 预演导入（检查参数和空间预检）
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --dry-run

# 3. 执行 TCG 导入
# 如果空间非常紧张，可添加 --skip-preflight 跳过脚本的 3 倍空间硬性检查
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --force --skip-preflight
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

预期 Flow 数为 `3,577,296`，CAUSES 边数约 `134,240,414`。

### 5.3 导入后服务检查

每次导入完成后执行：

```bash
cd /home/marktom/tugraph
docker compose ps
curl --max-time 5 -s -o /tmp/tugraph-http-body -w 'http_code=%{http_code}\n' http://127.0.0.1:7070/
timeout 3 bash -lc '</dev/tcp/127.0.0.1/7687' && echo bolt_port_open
```

TuGraph 停止或启动过程中可能输出 Python plugin 的 `KeyboardInterrupt` 日志，这是服务停止时插件任务进程被中断的日志。只要 `docker compose ps` 显示服务运行、HTTP/Bolt 检查通过、点边数量可查询，即可认为导入流程完成。

如果 TCG 导入报：

```text
Opening DB failed, error: IO error: No space left on device: While mkdir if missing: ./.import_tmp/db
```

先确认 dry-run 命令中包含 `--workdir /tmp`，并确认 `/tmp` 挂载到 `/dev/sdb1`：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --dry-run
cd /home/marktom/tugraph
docker exec tugraph-db sh -lc 'df -h /tmp /var/lib/lgraph/data /import'
```

如果 TCG 导入报：

```text
IO error: While open a file for random read: ./.import_tmp/db/003246.sst: Too many open files
```

先确认 dry-run 命令中包含 `--ulimit nofile=1048576:1048576`。如宿主机策略不允许该
上限，可用环境变量或参数调低到允许的最大值后重新导入：

```bash
TUGRAPH_IMPORT_NOFILE=262144:262144 PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --force
```

当前 TCG 数据规模较大。若 dry-run 输出类似：

```text
tmp_free_after_clean=75.5GiB min_required=98.4GiB
```

不要直接重跑导入；先释放同一文件系统上的空间。确认空间足够后再执行：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --force
```

## 6. HCG Node2Vec Walks

当前可用方案是 Python 存储过程在 TuGraph 数据库侧生成 walks，本地只负责上传/调用存储过程、检查 walks，并在后续执行 walk2vec/Word2Vec 训练。

不可用方案已归档：

```text
procedures/archived_node2vec/hcg_node2vec_walk_v2_unusable.cpp
```

该 C++ node2vec 版本能编译并可能写出部分 walks，但在当前 TuGraph 4.5.2 runtime 中调用返回/清理阶段会导致服务或插件 runner 崩溃。因此默认构建脚本不再生成 `hcg_node2vec_walk_v2.so`，不要上传或执行该 C++ 版本。

### 6.1 Python 存储过程 Smoke

上传并执行小规模 smoke：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure.py \
  --upload \
  --delete-first \
  --call \
  --max-start-nodes 1000 \
  --walk-length 10 \
  --num-walks 2 \
  --output-path /tmp/hcg_walks_node2vec_py_smoke_1000.txt \
  --id-map-path /tmp/hcg_node_id_map_node2vec_py_smoke_1000.csv \
  --timeout 600
```

检查 walks 文件：

```bash
python3 scripts/check_walks_file.py \
  --walks docker/tugraph-tmp/hcg_walks_node2vec_py_smoke_1000.txt \
  --expected-min-lines 2000 \
  --min-walk-len 2 \
  --report data/features/hcg/reports/hcg_node2vec_py_procedure_smoke_1000_check.md \
  --json-report data/features/hcg/reports/hcg_node2vec_py_procedure_smoke_1000_check.json
```

当前 smoke 结果：

| 指标 | 值 |
| --- | ---: |
| start nodes | 1,000 |
| walks | 2,000 |
| procedure elapsed | 15.01 秒 |
| average walk length | 7.499 |
| min / max walk length | 2 / 10 |
| unique token count | 7,845 |
| checks | PASS |

### 6.2 全量执行评估

HCG 当前有 `865,950` 个有出边 Endpoint。若使用 `num_walks=5`，全量需要生成约 `4,329,750` 条 walk。

根据 1000 起点 smoke 的吞吐：

```text
2000 walks / 15.01s = 约 133 walks/s
```

全量 `walk_length=10,num_walks=5` 估算约 `9.0` 小时；若提高到 `walk_length=20`，保守估计约 `10-18` 小时，并会长时间占用 TuGraph Python plugin runner 和持续写 `/tmp` 输出文件。因此目前**不自动启动全量 node2vec walks**。全量执行前应先确认机器可持续运行窗口、磁盘空间和是否接受 TuGraph 插件长任务占用。

确认要跑全量时使用：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure.py \
  --call \
  --max-start-nodes 0 \
  --walk-length 20 \
  --num-walks 5 \
  --p 1.0 \
  --q 1.0 \
  --output-path /tmp/hcg_walks_node2vec_py_full.txt \
  --id-map-path /tmp/hcg_node_id_map_node2vec_py_full.csv \
  --timeout 86400
```

生成完成后，本地 walk2vec/Word2Vec 训练应读取：

```text
docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt
docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv
```

## 7. 查询视图

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

## 8. 校验重点

- `flows.csv` 中的 `record_id` 必须唯一。
- `flow_id` 只作为普通属性，不作为 Flow 主键。
- `CAUSES` 不包含自环。
- `relation_id` 必须唯一。
- `delta_seconds` 作为边属性保存；查询视图可按该字段继续过滤。
- TCG 构建前先查看 `data/processed/reports/tcg_edge_estimation_report.md`。

更多字段说明见 [docs/graph_modeling.md](docs/graph_modeling.md)、[docs/dataset_structure.md](docs/dataset_structure.md) 和 [docs/data_report.md](docs/data_report.md)。
