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

### 6.3 批处理运行

如果你想按批看到耗时和剩余时间估算，用批处理副本：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure_batch.py \
  --upload \
  --delete-first \
  --call \
  --walk-length 20 \
  --num-walks 5 \
  --output-path docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt \
  --id-map-path docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv
```

它会把每批结果写到临时分片目录，最后合并成完整 walks 和 id map 文件。

当前默认批处理配置按 4 核、约 8GB 内存、HCG `865,950` 个有出边起点选择：

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `batch_size` | `10000` | 全量约 87 批，减少重复扫描和调用开销 |
| `timeout` | `1200` | 单批客户端请求超时，单位秒 |
| `procedure_time_budget` | `900` | 单批服务端执行预算，单位秒 |
| `walk_length` | `20` | 保持当前全量语料配置 |
| `num_walks` | `5` | 全量约 4,329,750 条 walk |

### 6.4 HCG Word2Vec Endpoint Embeddings

全量 HCG Node2Vec walks 已作为 Word2Vec 语料使用：每条 walk 是一句 sentence，每个 `endpoint_id` 是一个 token。训练脚本只读取现有 walks 和 id map，不重新生成 walks，不重新导入 TuGraph。

如果当前 Python 环境缺依赖，先安装：

```bash
conda run -n tugraph python -m pip install gensim numpy pandas pyarrow
```

默认输入：

```text
docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt
docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv
```

默认输出：

```text
data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet
data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.model
data/features/hcg/reports/hcg_word2vec_d64_report.md
data/features/hcg/reports/hcg_word2vec_d64_report.json
data/features/hcg/reports/hcg_word2vec_d64_report.log
```

默认训练参数：

| 参数 | 值 |
| --- | ---: |
| `vector_size` | `64` |
| `window` | `5` |
| `min_count` | `1` |
| `sg` | `1` |
| `negative` | `5` |
| `sample` | `1e-4` |
| `epochs` | `5` |
| `workers` | `min(cpu_count, 8)`；当前 4 核服务器默认为 `4` |
| `seed` | `20260525` |

parquet schema：

```text
endpoint_id
vid
emb_000
emb_001
...
emb_063
```

smoke test：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_word2vec_embeddings.py \
  --walks docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt \
  --id-map docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv \
  --output data/features/hcg/node2vec/hcg_endpoint_node2vec_d64_smoke.parquet \
  --model-output data/features/hcg/node2vec/hcg_endpoint_node2vec_d64_smoke.model \
  --report data/features/hcg/reports/hcg_word2vec_d64_smoke_report.md \
  --json-report data/features/hcg/reports/hcg_word2vec_d64_smoke_report.json \
  --vector-size 64 \
  --window 5 \
  --min-count 1 \
  --sg 1 \
  --negative 5 \
  --sample 1e-4 \
  --epochs 1 \
  --seed 20260525 \
  --max-lines 100000 \
  --overwrite
```

校验 smoke 输出：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/check_hcg_embeddings.py \
  --embeddings data/features/hcg/node2vec/hcg_endpoint_node2vec_d64_smoke.parquet \
  --id-map docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv \
  --expected-dim 64 \
  --expected-min-rows 1000 \
  --report data/features/hcg/reports/hcg_endpoint_node2vec_d64_smoke_check.md \
  --json-report data/features/hcg/reports/hcg_endpoint_node2vec_d64_smoke_check.json
```

全量训练命令：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_word2vec_embeddings.py \
  --walks docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt \
  --id-map docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv \
  --output data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet \
  --model-output data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.model \
  --report data/features/hcg/reports/hcg_word2vec_d64_report.md \
  --json-report data/features/hcg/reports/hcg_word2vec_d64_report.json \
  --vector-size 64 \
  --window 5 \
  --min-count 1 \
  --sg 1 \
  --negative 5 \
  --sample 1e-4 \
  --epochs 5 \
  --seed 20260525 \
  --overwrite
```

全量校验命令：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/check_hcg_embeddings.py \
  --embeddings data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet \
  --id-map docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv \
  --walks docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt \
  --expected-dim 64 \
  --expected-rows 933050 \
  --report data/features/hcg/reports/hcg_endpoint_node2vec_d64_check.md \
  --json-report data/features/hcg/reports/hcg_endpoint_node2vec_d64_check.json
```

下游分类任务 join 设计：embedding parquet 是 Endpoint 级特征，不是 flow 级特征。后续应使用 `endpoint_id` 分别与 flow 的 `src_endpoint`、`dst_endpoint` 对齐：

```text
src_emb = emb(src_endpoint)
dst_emb = emb(dst_endpoint)
flow_emb = concat(src_emb, dst_emb, abs(src_emb - dst_emb), src_emb * dst_emb)
```

若 endpoint embedding 维度为 `64`，则 `flow_emb` 维度为 `256`。

## 7. 数据集获取

核心分类数据集 A 和 B 已上传到 HuggingFace Hub 和 ModelScope，可直接下载使用。数据集 C 可由 A + B 自动合成，无需单独下载。

仓库地址：

| 平台 | 地址 |
| --- | --- |
| ModelScope | https://modelscope.cn/datasets/MarkTom/IP-Network-Flow-HCG |
| HuggingFace | https://huggingface.co/datasets/MarkTom/IP-Network-Flow-HCG |

### 7.1 从 ModelScope 下载

```bash
# 安装依赖
pip install modelscope

# 下载数据集（自动合成 C）
PYTHONPATH=src python3 scripts/download_datasets_from_hub.py \
  --hub modelscope \
  --repo-id MarkTom/IP-Network-Flow-HCG
```

### 7.2 从 HuggingFace 下载

```bash
# 安装依赖
pip install huggingface_hub

# 下载数据集（自动合成 C）
PYTHONPATH=src python3 scripts/download_datasets_from_hub.py \
  --hub huggingface \
  --repo-id MarkTom/IP-Network-Flow-HCG
```

### 7.3 一键脚本自动下载

运行一键训练脚本时，如果检测到数据集缺失，会自动提示从 Hub 下载：

```bash
bash scripts/run_hcg_classification_all.sh
```

### 7.4 上传数据集到 Hub

上传到 ModelScope：

```bash
# 安装依赖
pip install modelscope

# 上传数据集
PYTHONPATH=src python3 scripts/upload_datasets_to_hub.py \
  --hub modelscope \
  --repo-id MarkTom/IP-Network-Flow-HCG
```

上传到 HuggingFace：

```bash
# 安装依赖
pip install huggingface_hub

# 登录 HuggingFace
huggingface-cli login

# 上传数据集 A 和 B
PYTHONPATH=src python3 scripts/upload_datasets_to_hub.py \
  --hub huggingface \
  --repo-id MarkTom/IP-Network-Flow-HCG
```

### 7.5 数据集说明

| 数据集 | 文件 | 大小 | 说明 |
| --- | --- | --- | --- |
| A | `A_raw_flow_features.parquet` | ~562 MB | 91 个原始流统计特征 |
| B | `B_hcg_flow_emb_256.parquet` | ~2.7 GB | 258 个 HCG 图嵌入特征 |
| C | `C_raw_plus_hcg_flow_emb.parquet` | ~3.3 GB | A + B 融合（自动合成） |

## 8. HCG 分类器训练

分类训练只消费已构建并校验通过的 A/B/C parquet，不重新构建特征、不重新训练 Word2Vec、不重新生成 walks、不重新导入 TuGraph。

输入数据：

| 组别 | 路径 | 含义 |
| --- | --- | --- |
| A | `data/features/hcg/classification/datasets/A_raw_flow_features.parquet` | 91 个 raw flow 特征 |
| B | `data/features/hcg/classification/datasets/B_hcg_flow_emb_256.parquet` | 258 个 HCG flow embedding 特征 |
| C | `data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet` | raw + HCG 融合特征 |

新增入口：

| 脚本 | 作用 |
| --- | --- |
| `scripts/train_hcg_classifiers.py` | 独立训练 A/B/C × Dummy、Logistic SGD、Decision Tree、LightGBM、KNN sample |
| `scripts/check_hcg_classifier_results.py` | 检查 summary、任务目录、指标、模型、scaler、LightGBM importance 和 TensorBoard 产物 |
| `scripts/render_hcg_classification_figures.py` | 读取结果目录，生成论文可用的 Matplotlib 静态图 |
| `src/tugraph_homework/experiment_monitor.py` | 共享进度事件、原子写入、运行状态 Markdown 和终端进度条 |

安装训练依赖：

```bash
conda run -n tugraph python -m pip install scikit-learn joblib lightgbm matplotlib tensorboard tensorboardX \
  -i https://mirrors.aliyun.com/pypi/simple
```

smoke test：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results_smoke \
  --runs-dir runs/hcg_classification_smoke \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --sample-train 100000 \
  --sample-valid 20000 \
  --sample-test 20000 \
  --knn-train-sample 50000 \
  --knn-test-sample 20000 \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
```

结果检查：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/check_hcg_classifier_results.py \
  --results-dir data/features/hcg/classification/results_smoke \
  --expected-feature-groups A,B,C \
  --expected-models dummy_most_frequent,dummy_stratified,logistic_sgd,decision_tree,lightgbm,knn_sample
```

全量一键运行：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results \
  --runs-dir runs/hcg_classification \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --sample-train 0 \
  --sample-valid 0 \
  --sample-test 0 \
  --knn-train-sample 200000 \
  --knn-test-sample 100000 \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
```

只补跑缺失任务：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results \
  --runs-dir runs/hcg_classification \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --only-missing \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
```

监控文件：

```text
data/features/hcg/classification/results/progress.jsonl
data/features/hcg/classification/results/metrics_live.csv
data/features/hcg/classification/results/running_status.md
data/features/hcg/classification/results/classifier_summary.md
runs/hcg_classification/
```

查看状态：

```bash
cat data/features/hcg/classification/results/running_status.md
tail -n 20 data/features/hcg/classification/results/progress.jsonl
tensorboard --logdir runs/hcg_classification --host 0.0.0.0 --port 6006
```

重新画图，不重新训练：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/render_hcg_classification_figures.py \
  --results-dir data/features/hcg/classification/results
```

每个任务目录独立保存 `task_status.json`、`metrics.json`、`classification_report.csv`、`confusion_matrix.csv`、模型文件和必要的 `scaler.pkl`。`--resume` 会跳过已 completed 且核心输出完整的任务；`--force` 会覆盖指定任务目录；KNN 默认只采样运行。

内存保护和任务隔离默认开启：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--isolate-tasks` | 开启 | 父进程逐个启动子进程执行单任务；子进程异常退出或被 OOM 杀死时，父进程记录 failed 并继续后续任务。 |
| `--memory-guard` | 开启 | 任务开始前基于 parquet 行数、特征数和模型类型估算峰值内存；超过安全阈值时写 `status=skipped`。 |
| `--max-estimated-memory-gb` | `0` | 显式设置单任务估算峰值上限；`0` 表示自动使用可用内存减去保留内存。 |
| `--min-available-memory-gb` | `2.0` | 自动阈值下至少保留的系统内存。 |
| `--no-memory-guard` | 关闭保护 | 仅在确认机器内存足够时使用。 |
| `--no-isolate-tasks` | 关闭隔离 | 仅用于调试；正式长跑不建议关闭。 |

### 7.1 GPU 加速（可选）

训练脚本默认 **纯 CPU 运行**，所有 GPU 加速均为 opt-in（需显式指定 CLI 参数）。不传 GPU 参数时行为与旧版完全一致。

**GPU 前提**：NVIDIA GPU + CUDA 驱动。当前开发环境为 2x RTX 4090 (24GB)，CUDA 13.0。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--lightgbm-device cpu` | `cpu` | `cuda` 需从源码编译 LightGBM（见 experiment_record.md） |
| `--logistic-backend sklearn` | `sklearn` | `pytorch` 使用 GPU tensor + CrossEntropyLoss |
| `--knn-backend sklearn` | `sklearn` | `cuml` 为实验性 GPU 后端（当前环境 ABI 待修复） |
| `--logistic-pytorch-lr 0.01` | `0.01` | PyTorch 后端学习率 |

**GPU 加速版全量训练命令**：

```bash
PYTHONPATH=src conda run -n tugraph python3 scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results \
  --runs-dir runs/hcg_classification \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --no-memory-guard \
  --lightgbm-device cuda \
  --logistic-backend pytorch \
  --logistic-batch-size 200000 \
  --knn-train-sample 300000 \
  --knn-test-sample 100000 \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
```

GPU 加速效果（RTX 4090 vs 24核 CPU 估算）：

| 模型 | CPU 估算 | GPU 估算 | 加速比 |
| --- | ---: | ---: | ---: |
| LightGBM | ~2h | ~15min | **~8x** |
| Logistic SGD | ~20min | ~5min | ~4x |
| KNN | ~1h (采样30万) | ~3min (全量) | ~20x |
| 端到端总计 | ~3.6h | ~0.5h | **~7x** |

**纯 CPU 全量训练**（不指定任何 GPU 参数，与旧版完全兼容）：

```bash
PYTHONPATH=src conda run -n tugraph python3 scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results \
  --runs-dir runs/hcg_classification \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --no-memory-guard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
```

### 7.2 迁移到无 TuGraph 机器训练

分类训练阶段不需要 TuGraph 服务器。目标机器只需要 Python 环境、训练脚本和已经生成好的 A/B/C parquet。

必须迁移：

| 路径 | 是否必须 | 说明 |
| --- | --- | --- |
| `data/features/hcg/classification/datasets/A_raw_flow_features.parquet` | A 组需要 | raw flow 特征。 |
| `data/features/hcg/classification/datasets/B_hcg_flow_emb_256.parquet` | B 组需要 | HCG embedding flow 特征。 |
| `data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet` | C 组需要 | raw + HCG 融合特征。 |
| `scripts/train_hcg_classifiers.py` | 必须 | 分类训练入口。 |
| `scripts/check_hcg_classifier_results.py` | 建议 | 结果完整性检查。 |
| `scripts/render_hcg_classification_figures.py` | 建议 | 单独重画图。 |
| `src/tugraph_homework/` | 必须 | 共享工具和监控代码。 |
| `README.md`、`docs/experiment_record.md` | 建议 | 复现实验说明。 |

不需要迁移：

```text
docker/tugraph-data/
docker/tugraph-import/
docker/tugraph-logs/
docker/tugraph-tmp/
data/raw/
data/processed/
data/features/hcg/node2vec/
procedures/
build/
```

一键准备迁移目录：

```bash
PYTHONPATH=src python3 scripts/prepare_hcg_classification_training_bundle.py \
  --output-dir data/exports/hcg_classification_training_bundle \
  --feature-groups A,B,C \
  --force
```

如果只是同一块磁盘上先检查目录结构，可用 hardlink 避免重复占用 6GB 数据：

```bash
PYTHONPATH=src python3 scripts/prepare_hcg_classification_training_bundle.py \
  --output-dir data/exports/hcg_classification_training_bundle \
  --feature-groups A,B,C \
  --link \
  --force
```

需要生成 tar 包：

```bash
PYTHONPATH=src python3 scripts/prepare_hcg_classification_training_bundle.py \
  --output-dir data/exports/hcg_classification_training_bundle \
  --feature-groups A,B,C \
  --archive \
  --compress none \
  --force
```

全量 A/B/C bundle 约 `6.4 GiB`，主要由三份 parquet 构成。parquet 已压缩，`--compress gz` 通常节省有限且耗时更长，跨机器传输建议优先使用普通 `.tar` 或 `rsync`。

目标机器上解包后：

```bash
cd hcg_classification_training_bundle
python3 -m pip install -r requirements-classification.txt
PYTHONPATH=src python3 scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results \
  --runs-dir runs/hcg_classification \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
```

目标机器示例使用占位符，避免在文档中暴露真实用户名、地址和端口：

```text
<remote_user>@<remote_host> -p <remote_port>
<remote_project_dir>
```

本机准备 tar：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03

PYTHONPATH=src python3 scripts/prepare_hcg_classification_training_bundle.py \
  --output-dir data/exports/hcg_classification_training_bundle \
  --feature-groups A,B,C \
  --archive \
  --compress none \
  --force
```

传输到目标项目目录：

```bash
rsync -avh --progress \
  -e "ssh -p <remote_port>" \
  data/exports/hcg_classification_training_bundle.tar \
  <remote_user>@<remote_host>:<remote_project_dir>/
```

登录目标机器并解包：

```bash
ssh -p <remote_port> <remote_user>@<remote_host>

cd <remote_project_dir>
tar -xf hcg_classification_training_bundle.tar
rsync -avh --progress hcg_classification_training_bundle/ ./
```

安装依赖：

```bash
cd <remote_project_dir>
python3 -m pip install -r requirements.txt
```

确认数据到位：

```bash
ls -lh data/features/hcg/classification/datasets/
```

可选：迁移后重新校验 A/B/C parquet：

```bash
PYTHONPATH=src python3 scripts/check_hcg_classification_features.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --report data/features/hcg/classification/reports/hcg_classification_feature_check_after_transfer.md \
  --json-report data/features/hcg/classification/reports/hcg_classification_feature_check_after_transfer.json
```

先跑 smoke：

```bash
PYTHONPATH=src python3 scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results_smoke \
  --runs-dir runs/hcg_classification_smoke \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --sample-train 100000 \
  --sample-valid 20000 \
  --sample-test 20000 \
  --knn-train-sample 50000 \
  --knn-test-sample 20000 \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
```

正式训练：

```bash
PYTHONPATH=src python3 scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results \
  --runs-dir runs/hcg_classification \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --tensorboard \
  --progress \
  --render-figures \
  --seed 20260525 \
  --resume
```

确认同步无误后可删除目标机器上的传输包和临时解包目录：

```bash
rm -rf hcg_classification_training_bundle hcg_classification_training_bundle.tar
```

## 9. 查询视图

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

## 10. 校验重点

- `flows.csv` 中的 `record_id` 必须唯一。
- `flow_id` 只作为普通属性，不作为 Flow 主键。
- `CAUSES` 不包含自环。
- `relation_id` 必须唯一。
- `delta_seconds` 作为边属性保存；查询视图可按该字段继续过滤。
- TCG 构建前先查看 `data/processed/reports/tcg_edge_estimation_report.md`。

更多字段说明见 [docs/graph_modeling.md](docs/graph_modeling.md)、[docs/dataset_structure.md](docs/dataset_structure.md) 和 [docs/data_report.md](docs/data_report.md)。

## 11. TCG D64-light Node2Vec + Word2Vec

TCG D64-light 使用 CR+PR 关系（38.3M 边，约为全量 TCG 的 28.5%）在 TuGraph 中生成 Node2Vec walks，然后训练 64 维 flow-level Word2Vec embedding。

### 11.1 导入 CR+PR 子图

```bash
# 准备 CR+PR 数据目录
mkdir -p data/processed/tcg_light_crpr/causes_full_parts
ln data/processed/tcg/flows.csv data/processed/tcg_light_crpr/flows.csv
cp -al data/processed/tcg/causes_full_parts/relation_type=CR data/processed/tcg_light_crpr/causes_full_parts/
cp -al data/processed/tcg/causes_full_parts/relation_type=PR data/processed/tcg_light_crpr/causes_full_parts/

# 准备导入目录
mkdir -p docker/tugraph-import-light
cp -al data/processed/tcg_light_crpr docker/tugraph-import-light/tcg

# 导入到 TuGraph
PYTHONPATH=src python3 scripts/import_tugraph_native.py \
  --graph-type tcg --graph tcg_light_crpr \
  --import-root docker/tugraph-import-light --force
```

### 11.2 Node2Vec Walks

```bash
# Smoke test
PYTHONPATH=src python3 scripts/run_tcg_node2vec_procedure_batch.py \
  --graph tcg_light_crpr --delete-first \
  --walk-length 10 --num-walks 2 --batch-size 1000 --max-batches 2 \
  --output-path docker/tugraph-tmp/tcg_walks_d64_light_crpr_smoke.txt \
  --id-map-path docker/tugraph-tmp/tcg_node_id_map_d64_light_crpr_smoke.csv

# 全量（支持断点续跑）
PYTHONPATH=src python3 scripts/run_tcg_node2vec_procedure_batch.py \
  --graph tcg_light_crpr \
  --walk-length 10 --num-walks 2 --batch-size 50000 \
  --output-path docker/tugraph-tmp/tcg_walks_d64_light_crpr.txt \
  --id-map-path docker/tugraph-tmp/tcg_node_id_map_d64_light_crpr.csv \
  --progress --resume --timeout 1200 --procedure-time-budget 900
```

### 11.3 Word2Vec 训练

```bash
PYTHONPATH=src python3 scripts/train_tcg_word2vec_embeddings.py \
  --walks docker/tugraph-tmp/tcg_walks_d64_light_crpr.txt \
  --id-map docker/tugraph-tmp/tcg_node_id_map_d64_light_crpr.csv \
  --output data/features/tcg/node2vec/tcg_flow_node2vec_d64_light_crpr.parquet \
  --model-output data/features/tcg/node2vec/tcg_flow_node2vec_d64_light_crpr.model \
  --report data/features/tcg/reports/tcg_word2vec_d64_light_crpr_report.md \
  --json-report data/features/tcg/reports/tcg_word2vec_d64_light_crpr_report.json \
  --vector-size 64 --window 5 --min-count 1 --sg 1 --negative 5 \
  --sample 1e-4 --epochs 3 --workers 0 --seed 20260528 --overwrite
```

## 12. TCG 分类数据集 D/E/F

| 数据集 | 说明 | 列数 |
|--------|------|------|
| D | TCG 64 维 embedding + missing flag | 69 |
| E | A (raw features) + TCG embedding | 160 |
| F | C (raw + HCG) + TCG embedding | 418 |

### 12.1 构建 D/E/F

```bash
PYTHONPATH=src python3 scripts/build_tcg_classification_features.py \
  --tcg-emb-path data/features/tcg/node2vec/tcg_flow_node2vec_d64_light_crpr.parquet \
  --output-dir data/features/tcg/classification/datasets \
  --report data/features/tcg/reports/tcg_classification_feature_build_d64_light_crpr_report.md \
  --json-report data/features/tcg/reports/tcg_classification_feature_build_d64_light_crpr_report.json
```

### 12.2 从 Hub 下载 D 并合成 E/F

```bash
# 从 ModelScope 下载 D 并自动合成 E/F
PYTHONPATH=src python3 scripts/download_datasets_from_hub.py \
  --hub modelscope \
  --repo-id MarkTom/IP-Network-Flow-Graph \
  --dataset-dir data/features/tcg/classification/datasets
```

### 12.3 数据集说明

| 数据集 | 文件 | 大小 | 说明 |
|--------|------|------|------|
| D | `D_tcg_flow_node2vec_d64_light_crpr.parquet` | ~1.3 GB | TCG 64 维 flow embedding |
| E | `E_raw_plus_tcg_d64_light_crpr.parquet` | ~1.8 GB | A + TCG 融合 |
| F | `F_raw_plus_hcg_plus_tcg_d64_light_crpr.parquet` | ~4.4 GB | C + TCG 融合 |

D/E/F 与 A 的 `record_id, target, split` 完全对齐。缺失 TCG embedding 的行以 0 填充，`tcg_emb_missing=1` 标记。

### 12.4 上传数据集

```bash
PYTHONPATH=src python3 scripts/upload_datasets_to_hub.py \
  --hub modelscope \
  --repo-id MarkTom/IP-Network-Flow-Graph
```

## 13. TCG 分类器训练

```bash
# Smoke test
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/tcg/classification/datasets \
  --output-dir data/features/tcg/classification/results_smoke \
  --runs-dir runs/tcg_classification_smoke \
  --feature-groups D,E,F \
  --models dummy,decision_tree,lightgbm \
  --sample-train 100000 --sample-valid 20000 --sample-test 20000 \
  --tensorboard --progress --render-figures --seed 20260528 --resume

# 全量
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/tcg/classification/datasets \
  --output-dir data/features/tcg/classification/results \
  --runs-dir runs/tcg_classification \
  --feature-groups D,E,F \
  --models dummy,decision_tree,lightgbm \
  --no-memory-guard \
  --tensorboard --progress --render-figures --seed 20260528 --resume
```
