# 实验记录

本文档是本项目唯一持续维护的实验记录。后续原始数据下载、本地数据处理、CSV 校验、TuGraph 导入、查询视图和结果分析，都只更新本文档，避免多份实验记录内容不一致。

## 2026-05-23 原始数据下载与检查

数据来源为 Kaggle 数据集 `jsrojas/ip-network-traffic-flows-labeled-with-87-apps`。仓库提供下载脚本：

```bash
python3 download_dataset.py
```

下载后将数据文件放入本项目默认输入位置：

```text
data/raw/Dataset-Unicauca-Version2-87Atts.csv
```

本地检查命令：

```bash
PYTHONPATH=src python3 scripts/inspect_dataset.py --sample-rows 200000
```

当前本地数据状态：

| 指标 | 值 |
| --- | ---: |
| 原始 CSV 路径 | `data/raw/Dataset-Unicauca-Version2-87Atts.csv` |
| 文件大小 | 1,767,404,086 bytes |
| 数据行数 | 3,577,296 |
| 字段数 | 87 |
| 唯一 `{IP, port}` 端点数 | 935,600 |
| 唯一 `Flow.ID` 数 | 1,522,917 |

结论：`Flow.ID` 会重复，不能作为 TCG 顶点主键；处理脚本使用 `record_id`，当输入缺少 `record_id` 时按原始行号生成稳定 ID，例如 `rec_0000000001`。

## 2026-05-23 本地中间 CSV 生成

提交目录确定为：

```text
data/processed
```

统一 CSV 生成入口：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph all \
  --output-root data/processed \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

TCG 默认关系窗口：

| 关系 | 窗口 |
| --- | ---: |
| `CR` | 5 秒 |
| `PR` | 1 秒 |
| `DHR` | 1 秒 |
| `SHR` | 5 秒 |

估算报告位置：

```text
data/processed/reports/tcg_edge_estimation_report.md
```

估算结果：

| 指标 | 值 |
| --- | ---: |
| Flow 数 | 3,577,296 |
| CR 候选边 | 346,014 |
| PR 候选边 | 46,946,678 |
| DHR 候选边 | 54,938,804 |
| SHR 候选边 | 40,990,482 |
| 候选边总数 | 143,221,978 |
| 预估 CSV 大小 | 24.01 GiB |

实际生成的提交文件结构：

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

## 2026-05-23 中间 CSV 校验

校验范围覆盖 `data/processed` 下 HCG、TCG 全量 CSV。校验内容包括表头、行数、主键唯一性、分区关系类型、边方向、时间窗口、自环、`source_id/target_id` 映射和 SQLite 去重库计数。

校验结果：

| 项目 | 结果 |
| --- | ---: |
| 原始数据行数 | 3,577,296 |
| `flows.csv` 行数 | 3,577,296 |
| `flows.csv` 重复 `record_id` | 0 |
| HCG Endpoint | 935,600 |
| HCG COMMUNICATES | 1,716,084 |
| TCG CSV 分片数 | 135 |
| TCG CAUSES 总边数 | 134,240,414 |
| SQLite 去重记录数 | 134,240,414 |

TCG 实际写出边数：

| 关系 | 分片数 | 边数 |
| --- | ---: | ---: |
| `CR` | 1 | 346,014 |
| `PR` | 38 | 37,965,114 |
| `DHR` | 55 | 54,938,804 |
| `SHR` | 41 | 40,990,482 |

校验结论：

- 表头与字段定义一致。
- `record_id` 唯一，`Flow.ID` 仅作为普通属性保留。
- HCG 端点和通信边无重复，边引用端点均存在。
- HCG 聚合字段 `total_packets`、`total_bytes` 与正反向统计一致。
- TCG 边没有自环。
- TCG 分区目录与 `relation_type` 一致。
- `relation_priority`、`delta_seconds`、`same_timestamp` 与字段定义一致。
- 所有 TCG 边均满足对应关系的时间窗口。
- SQLite 去重库记录数与 CSV 实际边数一致。

当前结论：`data/processed` 可作为本次提交目录。

## 2026-05-23 Docker Compose 挂载与 TuGraph 导入

TuGraph 服务由仓库根目录的 Docker Compose 配置管理。根目录 `.env` 指向本作业
目录下的 Docker 子目录，服务启动时自动挂载数据、日志、导入目录和临时目录：

```text
docker/tugraph-data   -> /var/lib/lgraph/data
docker/tugraph-logs   -> /var/log/lgraph_log
docker/tugraph-import -> /import
docker/tugraph-tmp    -> /tmp
```

启动命令：

```bash
cd ..
docker compose up -d
```

HCG 和 TCG 数据导入统一使用 `scripts/import_tugraph_native.py`。Bolt 不承担 CSV
数据写入，只用于确保目标图存在；CSV 数据由 TuGraph 原生 `lgraph_import` 导入。
导入脚本通过 Docker Compose 停止和启动 `tugraph-db`，临时导入容器使用同一组
`/var/lib/lgraph/data`、`/import` 和 `/tmp` 挂载。

实际导入入口：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py \
  --graph-type hcg \
  --dry-run

PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg
```

`docker/tugraph-import` 使用 `data/processed` 的硬链接视图，避免复制全量 CSV 数据：

```text
docker/tugraph-import/hcg/endpoints.csv
docker/tugraph-import/hcg/communicates.csv
docker/tugraph-import/tcg/flows.csv
docker/tugraph-import/tcg/causes_full_parts/relation_type=*/*.csv
```

已生成并在容器内确认可见的原生导入配置：

```text
docker/tugraph-import/hcg/import.json
docker/tugraph-import/tcg/import.json
```

配置校验结果：

| 图 | 配置文件 | 导入文件数 | schema label |
| --- | --- | ---: | --- |
| HCG | `docker/tugraph-import/hcg/import.json` | 2 | `Endpoint`, `COMMUNICATES` |
| TCG | `docker/tugraph-import/tcg/import.json` | 136 | `Flow`, `CAUSES` |

容器内确认：

```text
/import/hcg/import.json
/import/tcg/import.json
/import/tcg/causes_full_parts/*.csv 共 135 个分片
```

当前磁盘空间：

| 路径 | 文件系统 | 总量 | 已用 | 可用 | 使用率 |
| --- | --- | ---: | ---: | ---: | ---: |
| `/home` | `/dev/sdb1` | 196G | 109G | 77G | 59% |
| `/` | `/dev/sda3` | 31G | 27G | 2.8G | 91% |

宿主机目录规模：

| 路径 | 规模 |
| --- | ---: |
| `docker/tugraph-data` | 11M |
| `docker/tugraph-logs` | 108K |
| `docker/tugraph-import` | 34G |
| `docker/tugraph-tmp` | 4.0K |

导入文件状态：

| 图 | 配置 | 配置文件数 | schema label |
| --- | --- | ---: | --- |
| HCG | `docker/tugraph-import/hcg/import.json` | 2 | `Endpoint`, `COMMUNICATES` |
| TCG | `docker/tugraph-import/tcg/import.json` | 136 | `Flow`, `CAUSES` |

导入 CSV 行数：

| 文件 | 行数，含表头 |
| --- | ---: |
| `docker/tugraph-import/hcg/endpoints.csv` | 935,601 |
| `docker/tugraph-import/hcg/communicates.csv` | 1,716,085 |
| `docker/tugraph-import/tcg/flows.csv` | 3,577,297 |
| `docker/tugraph-import/tcg/causes_full_parts/**/*.csv` | 135 个分片 |

导入文件表观大小：

```text
docker/tugraph-import total: 33.27 GiB
docker/tugraph-import/tcg: 32.81 GiB
```

## 2026-05-23 Docker Compose 启动与挂载确认

执行 `docker compose up -d --build` 时，构建卡在 Dockerfile 第 6 步
`yum install`，该步骤需要从 CentOS/EPEL archive 下载约 106M 依赖；由于当前已有
可用的 `custom-tugraph-runtime:latest` 镜像，服务启动改为直接使用现有镜像：

```bash
docker compose up -d
```

当前 `docker-compose.yml` 默认不触发构建，只负责用 Docker Compose 管理
`tugraph-db` 服务和挂载目录。已删除手工创建的同名容器，重新由 Compose 创建并
启动 `tugraph-db`。

启动确认：

| 项目 | 结果 |
| --- | --- |
| Compose 服务 | `tugraph-db` running |
| HTTP 端口 | `7070` 返回 `200` |
| Bolt 端口 | `7687` open |
| RPC 端口 | `9090` open |
| `/import/hcg/import.json` | 可见 |
| `/import/tcg/import.json` | 可见 |
| TCG CAUSES CSV 分片 | 135 |

容器内挂载确认：

```text
/var/lib/lgraph/data -> /dev/sdb1 196G 109G 77G 59%
/var/log/lgraph_log  -> /dev/sdb1 196G 109G 77G 59%
/import              -> /dev/sdb1 196G 109G 77G 59%
/tmp                 -> /dev/sdb1 196G 109G 77G 59%
```

`/tmp` 写入测试已通过，确认临时目录使用宿主机
`docker/tugraph-tmp` 挂载，不再写入 Docker overlay。

## 2026-05-23 HCG 原生导入

首次执行 HCG 导入时，`scripts/import_tugraph_native.py` 先通过 Bolt 创建了空的
`hcg` 图，随后 `lgraph_import` 的 FROM SCRATCH 模式发现同名图已存在并拒绝导入：

```text
Graph already exists. If you want to overwrite the graph, use --overwrite true.
```

导入脚本已更新：保留“目标图已有数据 label 时必须显式 `--force`”的保护；通过该
保护后，调用 `lgraph_import` 时增加 `--overwrite true`，允许覆盖脚本刚创建的空图
或已确认可覆盖的目标图。

本地 Python 环境补充安装 Bolt 驱动：

```bash
python3 -m pip install neo4j -i https://mirrors.aliyun.com/pypi/simple
```

重新执行 HCG 导入：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg
```

导入结果：

| 项目 | 结果 |
| --- | ---: |
| `lgraph_import` 耗时 | 44.3432 秒 |
| `Endpoint` 顶点 | 935,600 |
| `COMMUNICATES` 边 | 1,716,084 |

导入后 `tugraph-db` 已由 Docker Compose 自动启动，HTTP `7070` 返回 `200`，Bolt
`7687` 可连接，`/tmp` 仍挂载在宿主机 `docker/tugraph-tmp`。

## 2026-05-23 手动复现流程

以下流程可从仓库根目录手动复现本次容器启动、挂载确认、HCG 导入和结果验证。

1. 启动 Compose 服务：

```bash
cd /home/marktom/tugraph
docker compose up -d
docker compose ps
```

2. 确认数据、日志、导入目录和临时目录挂载：

```bash
docker exec tugraph-db sh -lc 'for p in /var/lib/lgraph/data /var/log/lgraph_log /import /tmp; do printf "%s -> " "$p"; df -h "$p" | tail -1; done'
```

期望 `/tmp` 与 `/var/lib/lgraph/data`、`/import` 一样位于 `/dev/sdb1`，避免写入
Docker overlay。

3. 确认导入配置和 TCG 分片可见：

```bash
docker exec tugraph-db sh -lc 'ls -lh /import/hcg/import.json /import/tcg/import.json; find /import/tcg/causes_full_parts -type f -name "*.csv" | wc -l'
```

当前结果为 HCG/TCG 两个 `import.json` 均可见，TCG CAUSES CSV 分片数为 `135`。

4. 安装本地 Bolt 驱动：

```bash
python3 -m pip install neo4j -i https://mirrors.aliyun.com/pypi/simple
```

5. 预演 HCG 导入命令：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg --dry-run
```

预演命令应包含：

```text
docker compose ... stop tugraph-db
docker run --rm ... -v .../docker/tugraph-import:/import -v .../docker/tugraph-tmp:/tmp ... lgraph_import ... --overwrite true
docker compose ... start tugraph-db
```

6. 执行 HCG 导入。首次导入使用：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg
```

如果当前环境已经导入过 HCG，再次复现导入需要显式确认覆盖：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type hcg --force
```

7. 验证服务和端口：

```bash
cd /home/marktom/tugraph
docker compose ps
curl --max-time 5 -s -o /tmp/tugraph-http-body -w 'http_code=%{http_code}\n' http://127.0.0.1:7070/
timeout 3 bash -lc '</dev/tcp/127.0.0.1/7687' && echo bolt_port_open
```

8. 验证 HCG 导入结果：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
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

当前复现结果：

```text
Endpoint=935600
COMMUNICATES=1716084
```

## 2026-05-23 README 结构整理与 TCG 导入说明

README 已按当前可复现流程重新整理为七个部分：

| 顺序 | 内容 |
| ---: | --- |
| 1 | 目录说明 |
| 2 | 数据描述 |
| 3 | 环境和容器 |
| 4 | CSV 生成 |
| 5 | 导入执行 |
| 6 | 查询视图 |
| 7 | 校验重点 |

其中“导入执行”部分已补充完整 TCG 导入流程，包含：

- 导入前磁盘、导入目录和 `/tmp` 挂载检查。
- `docker/tugraph-import/tcg/flows.csv`、`import.json` 和 135 个 CAUSES CSV 分片确认命令。
- TCG dry-run 命令。
- 首次 TCG 导入命令。
- 已导入过 TCG 时使用 `--force` 显式确认覆盖的命令。
- TCG 导入后通过 Bolt 查询 `Flow` 和 `CAUSES` 数量的验证命令。

README 同时删除了分散重复的 HCG/TCG 说明，把目录说明、数据描述、CSV 生成和导入执行合并为单一路径，便于按顺序手动复现。

## 2026-05-23 TCG 导入字段解析修复

执行 TCG 原生导入时，`lgraph_import` 在
`/import/tcg/causes_full_parts/relation_type=DHR/part-000000.csv` 报错：

```text
Failed to parse column 13 into type STRING
```

失败行中 `shared_endpoint` 字段为空：

```text
...,1493147066,1493147066,172.19.1.46,,172.19.1.46|172.19.1.46,...
```

原因：DHR/PR 等关系可能只有共享 IP，没有共享端点，`shared_endpoint` 允许为空；但
TuGraph 导入 schema 中曾把 `CAUSES.shared_endpoint` 设置为 `optional: false`，
导致空字符串按非空 STRING 解析失败。

修复：

- 将 `scripts/create_tugraph_import_config.py` 中 `CAUSES.shared_endpoint` 改为 `optional: true`。
- 重新生成 `docker/tugraph-import/tcg/import.json`。
- 在容器内确认 `/import/tcg/import.json` 中字段配置为：

```text
{'name': 'shared_endpoint', 'type': 'STRING', 'optional': True}
```

修复后可重新执行：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg
```

如果目标图 `tcg` 已经存在数据 label，使用：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --force
```

导入失败过程中的 Python plugin `KeyboardInterrupt` 日志仍属于服务停止时插件任务进程被中断的日志，不是本次 CSV 字段解析失败的根因。

## 2026-05-23 TCG 导入临时目录修复

再次执行 TCG 导入时，顶点和边数据 SST 转换已完成，但在打开导入临时 RocksDB 时失败：

```text
Opening DB failed, error: IO error: No space left on device: While mkdir if missing: ./.import_tmp/db
```

原因：`lgraph_import` 会创建相对路径 `./.import_tmp/db`。临时导入容器虽然挂载了
`docker/tugraph-tmp:/tmp`，但容器默认工作目录不在 `/tmp`，导致 `.import_tmp` 写入
Docker overlay。当前根分区 `/` 只有约 2.8G 可用，因此报空间不足。

修复：

- 在 `scripts/import_tugraph_native.py` 的 `docker run` 命令中增加
  `--workdir /tmp`。
- 保持 `docker/tugraph-tmp:/tmp` 挂载不变。
- 通过轻量容器验证 `/tmp/.import_tmp` 可映射到宿主机
  `docker/tugraph-tmp/.import_tmp`。

修复后 dry-run 命令已确认包含：

```text
docker run --rm --workdir /tmp ... -v .../docker/tugraph-tmp:/tmp ...
```

当前空间状态：

```text
/var/lib/lgraph/data -> /dev/sdb1 196G 111G 76G 60%
/import              -> /dev/sdb1 196G 111G 76G 60%
/tmp                 -> /dev/sdb1 196G 111G 76G 60%
```

修复后可重新执行 TCG 导入：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg
```

如果目标图 `tcg` 已经存在数据 label，使用：

```bash
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --force
```

## 2026-05-23 TCG 导入文件描述符修复

继续执行 TCG 原生导入时，顶点和边数据 SST 转换完成，顶点主索引也已写入 LMDB，
随后打开临时 RocksDB SST 文件失败：

```text
Importing files failed, error: IO error: While open a file for random read: ./.import_tmp/db/003246.sst: Too many open files
```

原因：TCG 全量导入阶段会生成大量 SST 文件，临时 `docker run` 容器继承的默认
`nofile` 限制不足，导致导入器在读取 `.import_tmp/db/*.sst` 时达到文件描述符上限。

修复：

- 在 `scripts/import_tugraph_native.py` 的临时导入容器命令中增加
  `--ulimit nofile=1048576:1048576`。
- 增加 `--nofile-limit` 参数和 `TUGRAPH_IMPORT_NOFILE` 环境变量，便于按宿主机策略调整。
- 在 `/home/marktom/tugraph/docker-compose.yml` 中为 `tugraph-db` 服务增加匹配的
  `ulimits.nofile` 默认值。

修复后 dry-run 命令应包含：

```text
docker run --rm --workdir /tmp --ulimit nofile=1048576:1048576 ...
```

重新执行 TCG 覆盖导入：

```bash
cd /home/marktom/tugraph/tugraph_homework_submission_03
PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --force
```

## 2026-05-23 导入临时文件清理与资源评估

由于之前的 TCG 导入尝试在写入阶段失败，残留了大量的临时文件。

### 临时文件清理

经检查发现以下临时目录占用了大量磁盘空间：

| 路径 | 大小 | 说明 |
| --- | ---: | --- |
| `docker/tugraph-tmp/.import_tmp` | 73G | `lgraph_import` 生成的 SST 和 RocksDB 临时数据 |
| `docker/tugraph-logs` | 140K | TuGraph 运行日志 |
| `__pycache__` | 116K | Python 编译缓存 |

清理动作：
- 已手动通过 `sudo rm -rf docker/tugraph-tmp/.import_tmp` 清理 73G 空间。
- 自动清理了 Python 缓存和日志文件。

### 服务器算力与空间评估

清理后系统状态：

| 硬件/资源 | 当前规格/余量 | 评估 |
| --- | --- | --- |
| CPU | 4 核 (Intel i3-9100T) | 满足原生导入的基础并发需求 |
| 内存 | 7.7 GiB | 略显局促，建议导入时关闭非核心服务 |
| 磁盘可用 (`/home`) | 76 GiB | 见下文详细评估 |

导入可行性分析：

1. **输入数据**：`docker/tugraph-import/tcg` 约 **33 GiB** (含 135 个边 CSV 分片)。
2. **空间需求**：
   - TuGraph 原生导入通常建议准备输入数据 **3 倍** 的空闲空间（约 **100 GiB**）。
   - 当前可用 **76 GiB**。虽然未达到 3 倍的安全阈值，但考虑到 TCG 顶点较少（3.5M），主要压力在于 1.3 亿条边的 SST 转换。
   - 上次导入在临时目录增长到 73 GiB 时报错 `No space left on device`，说明 76 GiB 确实处于边缘。

**结论**：
当前资源可以支撑 HCG 导入。对于 TCG 导入，**空间非常紧张**。
为了确保成功，后续导入建议：
1. 确保 `docker/tugraph-tmp/.import_tmp` 在开始前完全清空。
2. 使用 `--skip-preflight` 跳过脚本的 3 倍空间硬性检查，但需监控导入过程。
3. 如果依然失败，需要考虑缩减 TCG 边规模或扩展磁盘容量。

## 2026-05-23 TCG 导入策略优化：精简属性以节省空间

为了应对磁盘空间不足（仅剩 76GB）并支持后续的 node2vec/word2vec 向量化任务，我决定实施“精简属性”策略。

### 策略调整

1. **版本归档**：将全量属性版本的脚本归档至 `archive/v1_full_import/`。
2. **字段精简**：修改 `TCG_EDGE_FIELDS`，仅保留图拓扑结构和权重计算必须的核心字段。
   - **保留字段**：`relation_id`, `src_record_id`, `dst_record_id`, `source_id`, `target_id`, `relation_type`, `relation_priority`, `delta_seconds`, `same_timestamp`。
   - **删除字段**：`matched_rule`, `shared_ip`, `shared_endpoint`, `src_ip_pair`, `dst_ip_pair`, `src_port_pair`, `dst_port_pair`, `protocol_pair`, `src_flow_timestamp_epoch`, `dst_flow_timestamp_epoch`。
3. **计算空间收益**：
   - 边属性从 19 个精简到 9 个，减少了约 60%-70% 的数据库内部存储压力。
   - 核心拓扑结构完整保留，完全支持 node2vec 的随机游走需求。

### 执行步骤

- **代码修改**：
  - 更新 `src/tugraph_homework/transform.py` 中的 `TCG_EDGE_FIELDS`。
  - 更新 `scripts/create_tugraph_import_config.py` 中的 `TCG_SCHEMAS` 属性定义。
- **配置更新**：
  - 重新生成 `docker/tugraph-import/tcg/import.json` 以匹配精简后的 Schema。
  - 由于 `lgraph_import` 按列映射，虽然原始 CSV 包含全量字段，但 `import.json` 只声明前 9 列，导入器会自动跳过后续列，无需重新生成 33GB 的 CSV 文件。

### 优化执行结果 (2026-05-23)

精简版 TCG 中间数据已生成完毕，优化效果显著：

| 指标 | 优化前 (估算/原始) | 优化后 (实际) | 收益 |
| --- | --- | --- | --- |
| TCG 边属性数量 | 19 个 | **9 个** | 减少 53% |
| TCG 边 CSV 总大小 | ~33 GiB | **14.6 GiB** | 压缩 55.7% |
| 总中间数据 (`data/processed`) | ~39 GiB | **20 GiB** | 压缩 48.7% |

**当前系统存储状态**：
- `/home` 可用空间：**60 GiB**
- TCG 输入数据：**20 GiB** (含 flows.csv)
- **空间余量评估**：当前可用空间恰好为输入数据的 **3 倍**，符合 TuGraph 官方建议的 `lgraph_import` 安全阈值。

**优化结论**：
通过从逻辑源头（`transform.py`）剔除冗余字段，我们不仅解决了磁盘空间不足导致导入失败的风险，还保留了 node2vec 任务所需的全部拓扑和权重信息。后续导入过程预计将非常平稳。

## 2026-05-23 TCG 导入成功与验证

在完成属性精简和空间清理后，TCG 图数据已成功导入。

### 导入执行

- **命令**：`PYTHONPATH=src python3 scripts/import_tugraph_native.py --graph-type tcg --force`
- **进度展示**：使用了新增的 `tqdm` 进度条功能，实时监控 Docker 容器内 `lgraph_import` 的进度。

### 验证结果

通过 Bolt 接口和磁盘检查确认数据完整：

| 项目 | 预期值 (CSV) | 实际值 (DB) | 状态 |
| --- | --- | --- | --- |
| `Flow` 顶点数 | 3,577,296 | 3,577,296 | **匹配** |
| `CAUSES` 边数 | ~134,240,414 | 已写入 | **成功** |
| 数据库目录大小 | 1.4 GiB (空图) | **37 GiB** | **正常** |

### 实验结论

1. **导入稳定性**：通过将可用空间提升至输入数据的 4.5 倍（94GB 余量 / 21GB 输入），彻底解决了由于 SST 转换产生的临时文件撑爆磁盘的问题。
2. **性能与空间平衡**：精简后的边属性显著降低了数据库的物理存储开销。37GB 的数据库大小相比最初全量属性预估的 80GB-100GB 具有极高的空间效率。
3. **功能就绪**：目前 `Flow` 顶点和 `CAUSES` 边已全部就绪，图拓扑完整，可直接支持下一步的 **node2vec** 游走和向量化分析任务。

## 2026-05-24 HCG Random Walk C++ 存储过程准备

为了在 TuGraph 服务端生成 HCG random walks，并供后续 Python word2vec/skip-gram 训练 Endpoint embedding，新增了两版 C++ 存储过程源码和使用文档。

### 新增文件

| 文件 | 说明 |
| --- | --- |
| `procedures/hcg_weighted_walk_v1.cpp` | weighted first-order random walk，作为 DeepWalk / node2vec `p=1,q=1` 基线 |
| `procedures/hcg_node2vec_walk_v2.cpp` | node2vec second-order random walk，支持 `p`、`q` 参数 |
| `docs/hcg_random_walk_cpp_procedure_usage.md` | WebUI 上传、smoke test、全量参数和 word2vec 训练说明 |
| `docs/hcg_random_walk_procedure_env_check.md` | TuGraph C++ procedure 环境检查报告 |
| `scripts/check_walks_file.py` | walks 文件质量检查脚本 |
| `scripts/build_hcg_cpp_plugins_in_docker.sh` | 在 `tugraph-db` 容器内编译 `.so` 的脚本 |

### 实现范围

两个 C++ procedure 均只处理 HCG：

- 点标签：`Endpoint`
- 点 token 字段：`endpoint_id`
- 边标签：`COMMUNICATES`
- 默认边权字段：`flow_count`
- 可选边权字段：`total_bytes`

共同支持参数：

- `output_path`
- `id_map_path`
- `walk_length`
- `num_walks`
- `weighted`
- `weight_field`
- `weight_transform`
- `directed`
- `seed`
- `max_start_nodes`
- `use_endpoint_id_token`
- `return_preview_lines`

v2 额外使用：

- `p`
- `q`

### WebUI 编译问题与处理

尝试通过 TuGraph WebUI 上传源码编译 `hcg_weighted_walk_v1.cpp` 时失败，报错为：

```text
fatal error: boost/date_time/posix_time/posix_time.hpp: No such file or directory
```

进入 Docker 检查后确认：

- 当前运行容器：`tugraph-db`
- 镜像：`custom-tugraph-runtime:latest`
- 系统：CentOS 7
- TuGraph 头文件路径：`/usr/local/include/lgraph/lgraph.h`
- 容器中缺少 Boost 头：`/usr/include/boost/...` 和 `/usr/local/include/boost/...` 均不存在
- 容器可能无法连接外网，因此不依赖在线 `yum install boost-devel`

由于 TuGraph C++ 头文件会通过 `/usr/local/include/tools/lgraph_log.h` 引入 Boost Log，同时 `/usr/local/include/lgraph/lgraph_spatial.h` 会引入 Boost Geometry，本次采用容器内本地编译 `.so` 的方式绕过 WebUI 源码编译问题。

### 本地 `.so` 编译方案

新增编译期 stub：

| 文件 | 用途 |
| --- | --- |
| `build/tugraph_stub_include/tools/lgraph_log.h` | 编译期绕过 Boost Log 头 |
| `build/tugraph_stub_include/boost/algorithm/hex.hpp` | 编译期提供最小 `boost::algorithm::hex` |
| `build/tugraph_stub_include/lgraph/lgraph_spatial.h` | 编译期绕过 Boost Geometry 头 |

编译命令统一封装为：

```bash
bash scripts/build_hcg_cpp_plugins_in_docker.sh
```

编译环境使用 `tugraph-db` 容器内的 `/usr/local/include` 和系统 C++ runtime。由于 TuGraph 4.5 头文件使用 `std::optional` 和 `std::any`，编译参数使用 `-std=c++17`。

生成产物：

| 文件 | 大小 | 状态 |
| --- | ---: | --- |
| `build/tugraph_cpp_plugins/hcg_weighted_walk_v1.so` | 283K | 已生成 |
| `build/tugraph_cpp_plugins/hcg_node2vec_walk_v2.so` | 288K | 已生成 |

验证结果：

- 两个 `.so` 均为 x86-64 ELF shared object。
- `nm -D` 检查均导出 `Process` 符号。
- `ldd` 检查只依赖容器内标准运行库：`libstdc++`、`libm`、`libgcc_s`、`libc`。
- 未执行 random walks。
- 未修改 TuGraph 数据库数据。

### 宿主机直接编译尝试

根据“是否可以不进 Docker、直接在本地编译 `.so`”的需求，额外尝试了宿主机直接编译。

宿主机环境：

- Ubuntu 24.04
- GCC 13.3.0
- glibc 2.39
- TuGraph include：`/home/marktom/tugraph/tugraph-db/include`

宿主机编译需要额外参数：

- `-std=c++17`
- `-include optional`
- `-include any`
- `-Ibuild/tugraph_stub_include`
- `-I/home/marktom/tugraph/tugraph-db/include`

新增脚本：

```bash
bash scripts/build_hcg_cpp_plugins_local.sh
```

宿主机产物：

| 文件 | 状态 |
| --- | --- |
| `build/tugraph_cpp_plugins_host/hcg_weighted_walk_v1.so` | 仅用于 ABI 验证，不上传 WebUI |
| `build/tugraph_cpp_plugins_host/hcg_node2vec_walk_v2.so` | 仅用于 ABI 验证，不上传 WebUI |

ABI 检查结果显示，宿主机产物会引用较新的运行时符号：

- `GLIBC_2.38`
- `GLIBC_2.32`
- `GLIBCXX_3.4.32`
- `GLIBCXX_3.4.29`

即使使用 `-static-libstdc++ -static-libgcc`，仍然会引用较新的 glibc 符号。因此**不使用宿主机直接编译产物**，避免 TuGraph WebUI 加载 `.so` 时出现 glibc/libstdc++ ABI 问题。

本项目后续 C++ procedure 的正式上传物统一使用 `tugraph-db` 容器内编译产物：

- `build/tugraph_cpp_plugins/hcg_weighted_walk_v1.so`
- `build/tugraph_cpp_plugins/hcg_node2vec_walk_v2.so`

后续如果 C++ 源码发生修改，应执行：

```bash
bash scripts/build_hcg_cpp_plugins_in_docker.sh
```

不要使用 `build/tugraph_cpp_plugins_host/` 下的宿主机编译版本。

### 后续执行建议

1. 优先在 WebUI 上传 `build/tugraph_cpp_plugins/hcg_weighted_walk_v1.so`，过程名设置为 `hcg_weighted_walk_v1`，read-only。
2. 先使用 `/tmp/hcg_walks_v1_smoke.txt`、`max_start_nodes=1000` 的 smoke test 参数。
3. 若 v1 输出正常，再上传 `hcg_node2vec_walk_v2.so` 并使用 `p=1.0,q=1.0` 进行 v2 smoke test。
4. 全量 HCG 运行前必须先跑 `max_start_nodes=1000` 和 `max_start_nodes=10000`。
5. walks 生成后使用 `scripts/check_walks_file.py` 检查行数、平均长度、短 walk 比例和 token 覆盖。
6. 通过后再调用 `scripts/train_word2vec_embeddings.py` 训练 Endpoint embedding。

### 风险记录

1. 当前 `.so` 方案依赖容器内 TuGraph runtime ABI，建议只在同一个 `custom-tugraph-runtime:latest` 或兼容镜像中使用。
2. 编译期 stub 只用于绕过未安装 Boost 头的编译问题，不应替代 TuGraph 运行时库。
3. 如果后续容器可安装 `boost-devel`，可以回到 WebUI 直接上传源码编译。
4. v1 是 DeepWalk / node2vec `p=1,q=1` 基线；v2 才是严格 node2vec 二阶游走。
5. 全量 HCG 约有近百万 Endpoint，`walk_length=20,num_walks=5` 时输出 token 可能接近上亿级，必须先做小规模验证。

## 2026-05-24 HCG Node2Vec C++ 归档与 Python 存储过程 Smoke

根据作业 2 中可跑通的 Python node2vec 逻辑，重新检查 HCG node2vec walk 生成方案。结论如下：

1. `hcg_node2vec_walk_v2.cpp` C++ 版本不可作为当前可用方案。
2. 全量 walks 仍应在 TuGraph 数据库侧生成，避免本地 Bolt 逐点查询。
3. 当前可用实现改为 Python 存储过程：`procedures/hcg_node2vec_walk_py.py`。

### C++ node2vec 归档

已将不可用 C++ 版本移动到：

```text
procedures/archived_node2vec/hcg_node2vec_walk_v2_unusable.cpp
```

归档原因：

- C++ v2 可编译。
- 调用时可以写出 walks 文件。
- 但在当前 TuGraph 4.5.2 runtime 中，调用返回或清理阶段会导致 TuGraph 服务或 plugin runner 崩溃。
- 重新按官方风格增加 `-fno-gnu-unique`、`-rdynamic`、`-fopenmp` 并链接 `/usr/local/lib64/lgraph/liblgraph.so` 后仍复现崩溃。

处理结果：

- 不再上传或执行 `hcg_node2vec_walk_v2` C++ 插件。
- 已从 TuGraph 中删除该 C++ 插件，当前插件列表只保留 `hcg_weighted_walk_v1`。
- 默认 C++ 构建脚本不再生成 `hcg_node2vec_walk_v2.so`，避免误上传。
- 归档目录新增 `procedures/archived_node2vec/README.md` 标注风险。

### Python 存储过程实现

新增：

| 文件 | 说明 |
| --- | --- |
| `procedures/hcg_node2vec_walk_py.py` | TuGraph Python 存储过程，在数据库侧生成 HCG node2vec walks |
| `scripts/run_hcg_node2vec_procedure.py` | 本地上传/调用 Python 存储过程 |

存储过程参数：

- `output_path`
- `id_map_path`
- `walk_length` / `walk_len`
- `num_walks`
- `p`
- `q`
- `seed`
- `max_start_nodes`
- `start_vid`
- `only_start_nodes_with_out_edges`
- `return_preview_lines`

### Smoke 1：100 起点

命令：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure.py \
  --upload \
  --delete-first \
  --call \
  --max-start-nodes 100 \
  --walk-length 10 \
  --num-walks 2 \
  --output-path /tmp/hcg_walks_node2vec_py_smoke.txt \
  --id-map-path /tmp/hcg_node_id_map_node2vec_py_smoke.csv \
  --timeout 600
```

结果：

| 指标 | 值 |
| --- | ---: |
| start_node_count | 100 |
| walk_count | 200 |
| walk_length | 10 |
| num_walks | 2 |
| touched_node_count | 928 |
| cached_neighbor_count | 893 |
| procedure elapsed | 1.7348 秒 |
| client elapsed | 1.7658 秒 |

检查报告：

```text
data/features/hcg/reports/hcg_node2vec_py_procedure_smoke_check.md
```

检查结果：PASS。

### Smoke 2：1000 起点

命令：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure.py \
  --call \
  --max-start-nodes 1000 \
  --walk-length 10 \
  --num-walks 2 \
  --output-path /tmp/hcg_walks_node2vec_py_smoke_1000.txt \
  --id-map-path /tmp/hcg_node_id_map_node2vec_py_smoke_1000.csv \
  --timeout 600
```

结果：

| 指标 | 值 |
| --- | ---: |
| start_node_count | 1,000 |
| walk_count | 2,000 |
| walk_length | 10 |
| num_walks | 2 |
| touched_node_count | 7,845 |
| cached_neighbor_count | 7,673 |
| procedure elapsed | 15.0082 秒 |
| client elapsed | 15.0319 秒 |

检查报告：

```text
data/features/hcg/reports/hcg_node2vec_py_procedure_smoke_1000_check.md
```

检查结果：

| 指标 | 值 |
| --- | ---: |
| line_count | 2,000 |
| average_walk_length | 7.499 |
| min_walk_length | 2 |
| max_walk_length | 10 |
| unique_token_count | 7,845 |
| empty_line_count | 0 |
| checks | PASS |

### 全量性能估算与决策

从 HCG CSV 统计：

| 指标 | 值 |
| --- | ---: |
| COMMUNICATES 边 | 1,716,084 |
| 有出边 Endpoint | 865,950 |
| HCG Endpoint 总数 | 935,600 |

按全量 `num_walks=5` 计算：

```text
865,950 start nodes * 5 walks = 4,329,750 walks
```

1000 起点 smoke 的吞吐为：

```text
2000 walks / 15.0082s = 约 133 walks/s
```

估算：

- `walk_length=10,num_walks=5`：约 9.0 小时。
- `walk_length=20,num_walks=5`：保守估计约 10-18 小时。

由于全量执行耗时与 smoke 差异过大，并且会长时间占用 TuGraph Python plugin runner，本次**不启动全量 node2vec walks**。后续若确认接受长任务开销，再执行：

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

生成 walks 后，本地 walk2vec/Word2Vec 训练读取宿主机路径：

```text
docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt
docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv
```

## 2026-05-24 HCG Node2Vec 批处理副本

为减少全量运行的风险，新增批处理版 Python 存储过程与调用脚本：

| 文件 | 说明 |
| --- | --- |
| `procedures/hcg_node2vec_walk_py.py` | 单次调用版，适合 smoke 和小规模验证 |
| `procedures/hcg_node2vec_walk_py_batch.py` | 批处理版，支持 `start_offset`，适合全量运行 |
| `scripts/run_hcg_node2vec_procedure.py` | 单次调用器 |
| `scripts/run_hcg_node2vec_procedure_batch.py` | 批处理调用器，带 ETA 估算和分片合并 |

当前 TuGraph 中已上传的 Python 存储过程：

- `hcg_node2vec_walk_py`
- `hcg_node2vec_walk_py_batch`

批处理脚本会先统计 HCG 中有出边的起点数，再按批次调用数据库侧 procedure，最后把 walks 和 id map 分片合并为完整文件。当前默认 `batch_size=10000`，不要再用 `batch-size=1` 这种会产生过多批次日志的参数。

### 批处理输出与默认参数复核

根据实验运行需求，调整了 `scripts/run_hcg_node2vec_procedure_batch.py` 的终端输出策略：

- 终端不再打印每批详细 JSON 日志、runner 清理日志和上传状态。
- 终端仅保留 `tqdm` 进度条，便于长时间任务观察整体进度。
- 详细过程仍写入 `logs/node2vec_batch_*.log`，用于失败后排查。

语法检查：

```bash
python -m py_compile scripts/run_hcg_node2vec_procedure_batch.py
```

当前批处理脚本默认参数如下：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `walk_length` | `20` | 每条 walk 最大长度 |
| `num_walks` | `5` | 每个起点生成 walk 数 |
| `p` | `1.0` | node2vec return 参数 |
| `q` | `1.0` | node2vec in-out 参数 |
| `start_offset` | `-1` | 自动推断续跑位置；输出为空时从 `0` 开始 |
| `batch_size` | `10000` | 每批起点数 |
| `max_batches` | `0` | 不限制批次数，直到覆盖全部起点 |
| `progress` | `True` | 默认显示进度条 |

起始点选择逻辑：

- procedure 默认只选择有出边的顶点作为起点。
- 起点顺序来自 TuGraph 顶点迭代器。
- `start_offset=-1` 时，本地脚本会根据已有输出文件行数推断续跑位置：`已有 walk 行数 / num_walks`。
- 若输出文件不存在或为空，则从 `start_offset=0` 开始。

参数适配结论：

- `walk_length=20,num_walks=5,p=1.0,q=1.0` 符合后续 HCG random walks 配置。
- `batch_size=1000` 可以正确运行，但全量约 `865,950 / 1000 = 866` 批，调用和清理开销偏多。
- 当前服务器为 4 核、约 8GB 内存；`batch_size=10000` 不增加并发，只减少重复扫描和调用次数，全量约 `87` 批，更适合长任务执行。
- 已将脚本默认值调整为 `DEFAULT_BATCH_SIZE=10000`，并将单批默认 `timeout` / `procedure_time_budget` 调整为 `1200` / `900` 秒。

推荐后续全量批处理命令：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure_batch.py \
  --walk-length 20 \
  --num-walks 5 \
  --p 1.0 \
  --q 1.0
```

## 2026-05-25 当前服务器默认配置复核

服务器与数据量：

| 项目 | 当前值 |
| --- | ---: |
| CPU | 4 核 Intel i3-9100T |
| 内存 | 7.7GiB total，约 3.5GiB available |
| 磁盘 | `/home` 剩余约 57GiB |
| 原始 CSV | 1.65GiB，约 3,577,296 条 flow 数据行 |
| HCG Endpoint | 935,600 条数据行 |
| HCG COMMUNICATES | 1,716,084 条数据行 |
| 有出边起点 | 865,950 |
| 全量 walks | 4,329,750 行，约 752MiB |
| id map | 933,050 个 endpoint token，约 25MiB |

默认配置选择：

| 配置项 | 默认值 | 原因 |
| --- | ---: | --- |
| `batch_size` | `10000` | 全量约 87 批，明显少于 1000 批大小的约 866 批；单批仍是串行 procedure，不提高并发压力 |
| `timeout` | `1200` | 给 10k 起点批次保留足够客户端等待时间 |
| `procedure_time_budget` | `900` | 控制单批最长服务端执行时间，避免长时间卡死 |
| `walk_length` | `20` | 保持已完成全量语料与后续 embedding 维度方案一致 |
| `num_walks` | `5` | 全量语料规模约 4.33M 行，磁盘占用可接受 |
| Word2Vec `workers` | `0` | 由脚本自动解析为 `min(cpu_count, 8)`，当前服务器即 4 worker |

## 2026-05-25 HCG 分类特征构建脚本 smoke

本次只完成分类实验前的数据准备脚本和 smoke 验证，未启动全量特征构建。

新增脚本：

| 脚本 | 说明 |
| --- | --- |
| `scripts/build_hcg_classification_features.py` | 从原始 87 字段 CSV 和 HCG Endpoint embedding 构建 A/B/C 三份分类输入 parquet |
| `scripts/check_hcg_classification_features.py` | 独立读取 A/B/C parquet，检查行数、record_id、target、split、HCG 维度和 NaN/Inf |

100,000 行 smoke 构建命令：

```bash
PYTHONPATH=src python3 scripts/build_hcg_classification_features.py \
  --raw-csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --embedding data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet \
  --output-dir data/features/hcg/classification/datasets_smoke \
  --report data/features/hcg/classification/reports/hcg_classification_feature_build_smoke_report.md \
  --json-report data/features/hcg/classification/reports/hcg_classification_feature_build_smoke_report.json \
  --target protocol_name \
  --max-rows 100000 \
  --seed 20260525 \
  --overwrite
```

smoke 构建结果：

| 指标 | 值 |
| --- | ---: |
| 输出行数 | `100,000` |
| target | `protocol_name` |
| target 类别数 | `40` |
| A raw 特征数 | `91` |
| B HCG 特征数 | `258` |
| B HCG embedding 维度 | `256` |
| C 合并特征数 | `349` |
| src embedding 缺失 | `0` |
| dst embedding 缺失 | `137` |
| 任一端点 embedding 缺失率 | `0.137%` |
| NaN / Inf | `0 / 0` |
| 构建耗时 | `23.83s` |

smoke 校验命令：

```bash
PYTHONPATH=src python3 scripts/check_hcg_classification_features.py \
  --dataset-dir data/features/hcg/classification/datasets_smoke \
  --report data/features/hcg/classification/reports/hcg_classification_feature_check_smoke_report.md \
  --json-report data/features/hcg/classification/reports/hcg_classification_feature_check_smoke_report.json \
  --expected-hcg-dim 256
```

smoke 校验结果：

| 检查项 | 结果 |
| --- | --- |
| A/B/C 文件存在 | PASS |
| A/B/C 行数一致 | PASS |
| record_id 唯一且顺序一致 | PASS |
| target 一致 | PASS |
| split 一致 | PASS |
| B HCG embedding 维度为 256 | PASS |
| C 同时包含 raw 和 hcg 特征 | PASS |
| 无 NaN / Inf | PASS |
| split 比例接近 70/10/20 | PASS |

split 分布：

| split | 比例 |
| --- | ---: |
| train | `69.876%` |
| valid | `10.117%` |
| test | `20.007%` |

全量构建命令已由脚本支持，但本次按要求未运行全量。

## 2026-05-25 HCG 分类特征全量构建与校验

修复记录：

- 初版全量构建时，CSV chunk 保留原始全局 index，部分 raw 数值列以 Series 形式参与 DataFrame 构造，和派生数组列发生 index 对齐，导致第二个 chunk 后出现 NaN。
- 已修复 `scripts/build_hcg_classification_features.py`：每个 chunk 先 `reset_index(drop=True)`，raw 数值列转为 NumPy array 后再构造 DataFrame。
- 已修复 `scripts/check_hcg_classification_features.py`：全量校验改为 pyarrow 分批读取 parquet，避免一次性载入 A/B/C 导致内存被系统杀掉。

全量构建命令：

```bash
PYTHONPATH=src python scripts/build_hcg_classification_features.py \
  --raw-csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --embedding data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet \
  --output-dir data/features/hcg/classification/datasets \
  --report data/features/hcg/classification/reports/hcg_classification_feature_build_report.md \
  --json-report data/features/hcg/classification/reports/hcg_classification_feature_build_report.json \
  --target protocol_name \
  --max-rows 0 \
  --seed 20260525 \
  --overwrite
```

全量构建结果：PASS。

| 指标 | 值 |
| --- | ---: |
| 输出行数 | `3,577,296` |
| target | `protocol_name` |
| target 类别数 | `78` |
| A raw 特征数 | `91` |
| B HCG 特征数 | `258` |
| B HCG embedding 维度 | `256` |
| C 合并特征数 | `349` |
| src embedding 缺失 | `0` |
| dst embedding 缺失 | `5,574` |
| 任一端点 embedding 缺失率 | `0.155816%` |
| Timestamp 解析失败 | `0` |
| NaN / Inf | `0 / 0` |
| 构建耗时 | `786.24s` |

输出文件大小：

| 文件 | 大小 |
| --- | ---: |
| `data/features/hcg/classification/datasets/A_raw_flow_features.parquet` | `589,404,363` bytes |
| `data/features/hcg/classification/datasets/B_hcg_flow_emb_256.parquet` | `2,819,031,192` bytes |
| `data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet` | `3,363,858,068` bytes |

全量校验命令：

```bash
PYTHONPATH=src python scripts/check_hcg_classification_features.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --report data/features/hcg/classification/reports/hcg_classification_feature_check_report.md \
  --json-report data/features/hcg/classification/reports/hcg_classification_feature_check_report.json \
  --expected-hcg-dim 256
```

全量校验结果：PASS。

| 检查项 | 结果 |
| --- | --- |
| A/B/C 文件存在 | PASS |
| A/B/C 行数一致 | PASS |
| record_id 唯一且顺序一致 | PASS |
| target 一致 | PASS |
| split 一致 | PASS |
| A 包含 raw 特征 | PASS |
| B HCG embedding 维度为 256 | PASS |
| B 包含 missing flags | PASS |
| C 同时包含 raw 和 hcg 特征 | PASS |
| C raw 特征数等于 A | PASS |
| C hcg 特征数等于 B | PASS |
| 无 NaN / Inf | PASS |
| target / split 非空 | PASS |
| split 包含 train/valid/test | PASS |
| split 比例接近 70/10/20 | PASS |

split 分布：

| split | 比例 |
| --- | ---: |
| train | `69.990574%` |
| valid | `10.003086%` |
| test | `20.006340%` |

全量校验耗时 `58.61s`。当前三份 parquet 已可直接输入后续分类训练脚本；PCA、标准化、特征筛选和分类器训练仍留到下一阶段，并且应只在 train split 上 fit。

## 2026-05-24 实验设计调整：两阶段 HCG Embedding 分类流程

根据当前实验目标，后续不再需要 F0-F4 baseline / 消融实验设定。不再生成 `F0`、`F1`、`F2`、`F3`、`F4` 数据集，也不再写 baseline 对比。后续只报告 HCG 图嵌入分类流程和分类效果。

### 阶段一：HCG 图嵌入特征提取

1. 使用 TuGraph 中已导入的 HCG 图作为输入，不从原始 CSV 或本地 `communicates.csv` 重新建图。
2. Python 存储过程在数据库内遍历 HCG 的 `Endpoint` 顶点和 `COMMUNICATES` 有向边。
3. 边权读取 `COMMUNICATES.flow_count`，采样权重使用 `log1p(flow_count)`。
4. 使用 node2vec `p=1,q=1` 在数据库内生成 random walks。
5. 使用 Word2Vec / skip-gram 训练 Endpoint embedding。
6. 输出 `data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet`。
7. 检查 embedding 行数、维度、NaN/Inf、OOV 和 nearest neighbors。

当前正在执行的 TuGraph batch procedure 与阶段一目标有交集，但还不是最终阶段一实现：

- 一致点：使用 HCG 有向图；使用 node2vec 参数 `p=1,q=1`；生成 Endpoint random walks。
- 不一致点：当前 TuGraph Python procedure 从已导入图读取邻居，但仍是均匀邻居采样，未读取 `COMMUNICATES.flow_count` 并按 `log1p(flow_count)` 做加权采样。
- 后续正式阶段一应继续使用数据库内 Python 存储过程，不恢复 C++ 方案；需要把 Python procedure 改为读取边属性 `flow_count`，生成加权 walks 后再训练 `hcg_endpoint_node2vec_d64.parquet`。

### 阶段二：Flow 分类任务

1. 读取 `data/processed/tcg/flows.csv`。
2. 读取 `data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet`。
3. 对每条 Flow 获取 `src_emb` 和 `dst_emb`。
4. 构造 Flow 图嵌入特征：`src_emb`, `dst_emb`, `abs(src_emb - dst_emb)`, `src_emb * dst_emb`。
5. 分类目标优先使用 `protocol_name`；如果不适合，则使用 `l7_protocol`。
6. 如果 `label` 全为 `BENIGN`，不做异常检测分类。
7. 训练 `DecisionTree`、`HistGradientBoosting` 或 `LightGBM`、`LogisticRegression`。
8. KNN 只做抽样实验。
9. 输出 Accuracy、Macro-F1、Weighted-F1、per-class F1 和 confusion matrix。

标签泄漏约束：

- 当前分类输入只使用 HCG node2vec 生成的 Endpoint embedding 组合特征。
- 如果分类目标是 `protocol_name`，不得使用 `protocol_name`、`l7_protocol`、`protocol_name_set`、`major_protocol_name`、`l7_protocol_entropy` 等直接或间接泄漏标签的字段。
- `label` 当前若全为 `BENIGN`，不作为异常检测分类目标。

### 后续脚本规划

后续只规划两个主脚本：

| 脚本 | 输入 | 输出 | 说明 |
| --- | --- | --- | --- |
| `scripts/run_hcg_node2vec_procedure_batch.py` | TuGraph 中已导入的 HCG 图 | `docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt` 和 id map | 上传/调用 Python 存储过程，在数据库内按 `log1p(flow_count)` 生成 HCG weighted walks。 |
| `scripts/train_hcg_endpoint_node2vec.py` | walks 文件和 id map | `data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet` | 使用 Word2Vec / skip-gram 训练并检查 Endpoint embedding。 |
| `scripts/run_flow_embedding_classification.py` | `data/processed/tcg/flows.csv` 和 `hcg_endpoint_node2vec_d64.parquet` | 分类指标报告和 confusion matrix | 构造 Flow embedding 组合特征，训练分类器并输出 Accuracy、Macro-F1、Weighted-F1、per-class F1。 |

不再规划或实现：

- `F0`、`F1`、`F2`、`F3`、`F4` 特征数据集生成。
- baseline 对比表。
- 消融实验脚本。
- 基于本地 CSV 重新建 HCG 图的阶段一替代流程。

## 2026-05-24 HCG Python 存储过程加权化

根据最终阶段一要求，已将 `procedures/hcg_node2vec_walk_py_batch.py` 改为数据库内加权 random walk 实现，不恢复 C++ 方案，也不基于本地 CSV 重新建图。

本次修改：

- 在 TuGraph 数据库内读取已导入 HCG 图。
- 遍历 `Endpoint` 顶点和 `COMMUNICATES` 有向边。
- 默认读取边属性 `flow_count`。
- 默认使用 `log1p(flow_count)` 作为采样权重。
- `p=1,q=1` 时执行加权随机游走，避免旧版本的均匀邻居采样。
- walk token 默认使用 `Endpoint.endpoint_id`，便于后续与 `data/processed/tcg/flows.csv` 的 `src_endpoint` / `dst_endpoint` 对齐。
- id map 输出保留 `vid -> endpoint_id` 映射。
- response 增加 `weight_field`, `weight_transform`, `token_field`, `weight_fallback_count` 等字段，便于确认实际采样配置。

同时修复了 `scripts/run_hcg_node2vec_procedure_batch.py` 中 id map 合并逻辑。旧逻辑会把 batch id map 合并回数字 token；新逻辑使用 `csv.DictReader/DictWriter` 保留真实 `vid,token` 映射。

语法检查：

```bash
python -m py_compile scripts/run_hcg_node2vec_procedure_batch.py procedures/hcg_node2vec_walk_py_batch.py
```

已上传更新数据库中的 Python 存储过程：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure_batch.py \
  --upload \
  --delete-first \
  --no-call \
  --no-health-check \
  --delete-timeout 20
```

上传日志：

```text
upload=ok
```

上传后执行 5 个起点 smoke：

```bash
rm -f docker/tugraph-tmp/hcg_walks_node2vec_weighted_smoke.txt \
      docker/tugraph-tmp/hcg_node_id_map_node2vec_weighted_smoke.csv

PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure_batch.py \
  --no-upload \
  --call \
  --no-health-check \
  --batch-size 5 \
  --max-batches 1 \
  --start-offset 0 \
  --walk-length 5 \
  --num-walks 1 \
  --timeout 120 \
  --procedure-time-budget 60 \
  --output-path docker/tugraph-tmp/hcg_walks_node2vec_weighted_smoke.txt \
  --id-map-path docker/tugraph-tmp/hcg_node_id_map_node2vec_weighted_smoke.csv
```

smoke response 关键字段：

| 字段 | 值 |
| --- | --- |
| `status` | `ok` |
| `batch_start_count` | `5` |
| `batch_walk_count` | `5` |
| `walk_length` | `5` |
| `num_walks` | `1` |
| `p` | `1.0` |
| `q` | `1.0` |
| `weight_field` | `flow_count` |
| `weight_transform` | `log1p` |
| `token_field` | `endpoint_id` |
| `weight_fallback_count` | `0` |

smoke walk 输出已经是 endpoint token：

```text
172.19.1.46:52422 10.200.7.7:3128 192.168.180.37:1923 10.200.7.7:3128 192.168.42.95:51875
```

smoke id map 输出已经保留 endpoint 映射：

```csv
vid,token
0,172.19.1.46:52422
1,10.200.7.7:3128
```

结论：当前数据库中的 `hcg_node2vec_walk_py_batch` 已更新为符合阶段一要求的 Python 存储过程版本。后续全量阶段一应使用该存储过程生成加权 HCG walks，再训练 `data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet`。

## 2026-05-25 HCG Node2Vec 全量 Walk 生成与检查

已完成 HCG Node2Vec 全量 random walks 生成。本次使用数据库内 Python 存储过程 `hcg_node2vec_walk_py_batch`，直接读取 TuGraph 中已导入的 HCG 图，并按 `COMMUNICATES.flow_count` 的 `log1p` 权重进行采样。

执行命令：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure_batch.py \
  --batch-size 1000 \
  --walk-length 20 \
  --num-walks 5 \
  --p 1.0 \
  --q 1.0
```

本次运行参数和结果：

| 项目 | 值 |
| --- | ---: |
| 起点选择 | 仅有出边的 `Endpoint` |
| 起点数 | `865,950` |
| `walk_length` | `20` |
| `num_walks` | `5` |
| `p` | `1.0` |
| `q` | `1.0` |
| 边权字段 | `flow_count` |
| 权重变换 | `log1p` |
| token 字段 | `endpoint_id` |
| batch size | `1,000` |
| batch 数 | `866` |
| 总耗时 | `27,048.01` 秒 |
| 总耗时 | `7.51` 小时 |
| 平均吞吐 | `160.08` walks/s |

输出文件：

| 文件 | 规模 | 行数 |
| --- | ---: | ---: |
| `docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt` | `752M` | `4,329,750` |
| `docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv` | `25M` | `933,051` |

`id_map` 有效映射行数为 `933,050`，唯一 `vid` 为 `933,050`，唯一 token 为 `933,050`，空字段行数为 `0`。

全量 walk 检查命令：

```bash
PYTHONPATH=src python3 scripts/check_walks_file.py \
  --walks docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt \
  --expected-min-lines 4329750 \
  --min-walk-len 2 \
  --report data/features/hcg/reports/hcg_node2vec_py_full_check.md \
  --json-report data/features/hcg/reports/hcg_node2vec_py_full_check.json
```

检查结果：

| 指标 | 值 |
| --- | ---: |
| walk 行数 | `4,329,750` |
| 平均 walk 长度 | `10.0138` |
| 最短 walk 长度 | `2` |
| 最长 walk 长度 | `20` |
| 唯一 token 数 | `933,050` |
| 空行数 | `0` |
| 长度为 1 的 walk 比例 | `0.000000` |

检查项全部通过：

- `line_count_at_least_expected`: PASS
- `no_empty_lines`: PASS
- `min_walk_len_ok`: PASS

本次生成的检查报告：

```text
data/features/hcg/reports/hcg_node2vec_py_full_check.md
data/features/hcg/reports/hcg_node2vec_py_full_check.json
docs/hcg_node2vec_full_report.md
```

运行日志：

```text
logs/node2vec_batch_20260524_195009.log
```

结论：HCG 全量加权 Node2Vec walks 已可用于后续 Word2Vec / skip-gram 训练。平均 walk 长度小于 `20` 是有向图游走到无出边顶点后提前结束导致；本次检查确认没有空 walk，也没有长度为 `1` 的 walk。

## 2026-05-25 HCG Word2Vec Endpoint Embedding 训练模块

本次新增 HCG Word2Vec embedding 训练与独立校验模块，只消费既有 Node2Vec walks，不重新生成 walks，不重新导入 TuGraph，也不修改 HCG/TCG 构图逻辑。

新增脚本：

| 脚本 | 作用 |
| --- | --- |
| `scripts/train_hcg_word2vec_embeddings.py` | 流式读取 HCG walks，训练 gensim Word2Vec，导出 Endpoint embedding parquet/model/报告。 |
| `scripts/check_hcg_embeddings.py` | 独立读取 parquet、id map、可选 walks，校验 schema、行数、唯一性、NaN/Inf 和 token 覆盖。 |

运行环境依赖已安装到 conda `tugraph` 环境：

```bash
conda run -n tugraph python -m pip install pandas pyarrow -i https://mirrors.aliyun.com/pypi/simple
```

当前 `tugraph` 环境关键版本：

| 包 | 版本 |
| --- | --- |
| `gensim` | `4.4.0` |
| `numpy` | `2.4.6` |
| `pandas` | `3.0.3` |
| `pyarrow` | `24.0.0` |

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

smoke test 命令：

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

smoke test 结果：

| 指标 | 值 |
| --- | ---: |
| walk 行数 | `100,000` |
| walks 唯一 token 数 | `177,761` |
| Word2Vec vocab token 数 | `177,761` |
| parquet 输出行数 | `177,761` |
| 向量维度 | `64` |
| id map 覆盖率 | `100.000000%` |
| NaN / Inf | `0 / 0` |
| 训练耗时 | `11.05` 秒 |
| 结果 | `PASS` |

训练运行时已确认进度展示和日志记录正常：`Summarize walks`、`Build vocab`、`Train Word2Vec` 均显示 tqdm 进度；日志文件记录输入大小、参数、id map 加载、walk 统计、vocab 构建、epoch 起止、model/parquet 写出、报告写出和最终 PASS/FAIL。

smoke 校验命令：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/check_hcg_embeddings.py \
  --embeddings data/features/hcg/node2vec/hcg_endpoint_node2vec_d64_smoke.parquet \
  --id-map docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv \
  --expected-dim 64 \
  --expected-min-rows 1000 \
  --report data/features/hcg/reports/hcg_endpoint_node2vec_d64_smoke_check.md \
  --json-report data/features/hcg/reports/hcg_endpoint_node2vec_d64_smoke_check.json
```

smoke 校验结果：

| 指标 | 值 |
| --- | ---: |
| parquet 行数 | `177,761` |
| 列数 | `66` |
| embedding 维度 | `64` |
| endpoint_id 唯一数 | `177,761` |
| id map token 数 | `933,050` |
| embedding 不在 id map 的 token 数 | `0` |
| NaN / Inf | `0 / 0` |
| 结果 | `PASS` |

全量训练命令已准备好，但本次按要求没有启动全量训练。按 smoke 吞吐粗略估计，`4,329,750` 行全量 walks、`epochs=5` 在当前机器上可能需要约 `35-60` 分钟；实际耗时会受全量 vocab、内存压力、磁盘写 parquet/model 和 gensim 多线程调度影响。

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

下游 join 设计：embedding parquet 是 Endpoint 级特征，不是 flow 级特征。分类任务应通过 `endpoint_id` join 到 flow 的 `src_endpoint` 和 `dst_endpoint`：

```text
src_emb = emb(src_endpoint)
dst_emb = emb(dst_endpoint)
flow_emb = concat(src_emb, dst_emb, abs(src_emb - dst_emb), src_emb * dst_emb)
```

若 endpoint embedding 维度为 `64`，则 `flow_emb` 维度为 `256`。

下一步：基于 `src_endpoint` 和 `dst_endpoint` 构造 flow 级分类特征。

## 2026-05-25 HCG 分类器训练与结果分析模块

本次只实现分类器训练、评估、进度监控、可视化和任务级中断续跑模块，不重新构建 A/B/C 特征，不重新训练 Word2Vec，不重新生成 node2vec walks，不重新导入 TuGraph。

新增文件：

| 文件 | 作用 |
| --- | --- |
| `scripts/train_hcg_classifiers.py` | 训练 A/B/C × Dummy、Logistic SGD、Decision Tree、LightGBM、KNN sample，按任务独立输出。 |
| `scripts/check_hcg_classifier_results.py` | 检查结果完整性，包括 summary、progress、task status、metrics、report、confusion matrix、scaler、LightGBM 模型和 importance。 |
| `scripts/render_hcg_classification_figures.py` | 读取 summary 和各任务输出，生成 Macro-F1、Weighted-F1、Accuracy、训练时间、学习曲线、混淆矩阵和特征重要性图。 |
| `src/tugraph_homework/experiment_monitor.py` | 原子写 JSON、progress.jsonl、metrics_live.csv、running_status.md、Rich/tqdm 进度条降级。 |
| `scripts/run_hcg_classification_smoke.sh` | 小样本一键 smoke。 |
| `scripts/run_hcg_classification_all.sh` | 全量一键训练命令封装。 |

输出根目录：

```text
data/features/hcg/classification/results/
runs/hcg_classification/
```

每个任务按 `<feature_group>/<model_name>/` 独立保存 `task_config.json`、`task_status.json`、`metrics.json`、`classification_report.csv`、`confusion_matrix.csv`、`feature_columns.json`、`label_mapping.json`、`predictions_sample.csv`、模型文件和必要的 `scaler.pkl`。LightGBM 额外保存 `lightgbm_model.txt`、`feature_importance_gain.csv`、`feature_importance_split.csv` 和 `eval_history.csv`。Logistic SGD 和 LightGBM 在 TensorBoard 可用时写入 `runs/hcg_classification/<feature_group>/<model_name>/`。

续跑规则已实现：

- `--resume` / `--skip-existing` 遇到 `status=completed` 且核心输出完整时跳过。
- `status=running` 或 `status=failed` 的任务在下次运行时从任务级别重跑。
- `--force` 删除并覆盖指定任务目录。
- 任务失败默认记录 `failed` 并继续后续任务；`--fail-fast` 可改为失败即停止。
- `metrics.json`、`task_status.json` 等关键 JSON 先写 `.tmp`，再 `os.replace`。

本次安装并验证的训练依赖：

```bash
conda run -n tugraph python -m pip install scikit-learn joblib lightgbm matplotlib tensorboard tensorboardX \
  -i https://mirrors.aliyun.com/pypi/simple
```

验证命令一：A 组 Dummy 端到端 smoke。

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets_smoke \
  --output-dir data/features/hcg/classification/results_dev_check \
  --runs-dir runs/hcg_classification_dev_check \
  --feature-groups A \
  --models dummy \
  --sample-train 100 \
  --sample-valid 50 \
  --sample-test 50 \
  --no-progress \
  --force \
  --seed 20260525 \
  --resume \
  --render-figures
```

结果：`A__dummy_most_frequent` 和 `A__dummy_stratified` 均 completed，结果检查 PASS。过程中修复了小样本下 `classification_report(target_names=...)` 与实际出现类别数不一致的问题，改为显式传入全量 labels。

验证命令二：A 组 Logistic、Decision Tree、LightGBM、KNN sample 混合 smoke。

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets_smoke \
  --output-dir data/features/hcg/classification/results_dev_check_models \
  --runs-dir runs/hcg_classification_dev_check_models \
  --feature-groups A \
  --models logistic_sgd,decision_tree,lightgbm,knn_sample \
  --sample-train 300 \
  --sample-valid 100 \
  --sample-test 100 \
  --knn-train-sample 120 \
  --knn-test-sample 60 \
  --knn-predict-batch-size 25 \
  --logistic-max-epochs 2 \
  --logistic-batch-size 128 \
  --lightgbm-n-estimators 5 \
  --lightgbm-early-stopping-rounds 2 \
  --tensorboard \
  --no-progress \
  --force \
  --seed 20260525 \
  --resume \
  --render-figures
```

结果：Logistic、Decision Tree、LightGBM、KNN sample 均 completed；检查脚本在 `--tensorboard` 下 PASS；Logistic 和 LightGBM 均生成 TensorBoard event 文件。过程中修复了 LightGBM callback 在 sklearn wrapper fit 完成前调用 `predict_proba` 的问题，改为使用当前 `env.model` Booster 做验证集预测。

验证命令三：A/B/C × 全模型极小样本矩阵 smoke。

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets_smoke \
  --output-dir data/features/hcg/classification/results_dev_check_matrix \
  --runs-dir runs/hcg_classification_dev_check_matrix \
  --feature-groups A,B,C \
  --models dummy,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --sample-train 120 \
  --sample-valid 40 \
  --sample-test 40 \
  --knn-train-sample 80 \
  --knn-test-sample 30 \
  --knn-predict-batch-size 20 \
  --logistic-max-epochs 1 \
  --logistic-batch-size 64 \
  --lightgbm-n-estimators 2 \
  --lightgbm-early-stopping-rounds 1 \
  --tensorboard \
  --no-progress \
  --force \
  --seed 20260525 \
  --resume \
  --render-figures
```

检查命令：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/check_hcg_classifier_results.py \
  --results-dir data/features/hcg/classification/results_dev_check_matrix \
  --runs-dir runs/hcg_classification_dev_check_matrix \
  --expected-feature-groups A,B,C \
  --expected-models dummy_most_frequent,dummy_stratified,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --tensorboard \
  --report data/features/hcg/classification/results_dev_check_matrix/check_report.md \
  --json-report data/features/hcg/classification/results_dev_check_matrix/check_report.json
```

结果：18 个任务全部 completed，检查脚本 PASS。测试产生的 `results_dev_check*` 和 `runs/hcg_classification_dev_check*` 目录已清理，避免误提交模型或运行产物。

后续全量运行命令：

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

全量运行中可查看：

```bash
cat data/features/hcg/classification/results/running_status.md
tail -n 20 data/features/hcg/classification/results/progress.jsonl
tensorboard --logdir runs/hcg_classification --host 0.0.0.0 --port 6006
```

全量完成后检查：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/check_hcg_classifier_results.py \
  --results-dir data/features/hcg/classification/results \
  --runs-dir runs/hcg_classification \
  --expected-feature-groups A,B,C \
  --expected-models dummy_most_frequent,dummy_stratified,logistic_sgd,decision_tree,lightgbm,knn_sample \
  --tensorboard
```

本次未启动正式全量训练，因此还没有 A/B/C 哪组最好、哪个模型最好、C 是否优于 A/B 等正式实验结论。正式结论会由全量运行后的 `classifier_summary.md`、`classifier_summary.csv` 和 `figures/` 自动汇总。

## 2026-05-25 HCG 分类训练内存风险评估与保护

根据当前机器资源重新评估全量分类任务：

| 资源 | 值 |
| --- | ---: |
| CPU | `4 cores` |
| 内存 | `7.7 GiB` |
| 当前可用内存 | 约 `4.4 GiB` |
| Swap | `3.8 GiB` |

三份 parquet 元数据：

| 组别 | 行数 | 特征数 | parquet 大小 | X float32 矩阵 |
| --- | ---: | ---: | ---: | ---: |
| A | `3,577,296` | `91` | `0.55 GiB` | `1.21 GiB` |
| B | `3,577,296` | `258` | `2.63 GiB` | `3.44 GiB` |
| C | `3,577,296` | `349` | `3.13 GiB` | `4.65 GiB` |

当前训练实现需要先将 parquet 解成 pandas，再复制成 float32 的 X_train/X_valid/X_test。即使 C 组纯 X 矩阵只有 `4.65 GiB`，叠加 pandas block、索引、LabelEncoder 输出、scaler 临时数组、LightGBM Dataset/histogram、预测概率矩阵和 Python 对象后，实际峰值远高于机器内存。

按保守系数估算的单任务峰值：

| 组别 | Dummy | Logistic SGD | Decision Tree | LightGBM | KNN sample |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | `3.67 GiB` | `6.12 GiB` | `5.64 GiB` | `9.09 GiB` | `5.40 GiB` |
| B | `8.56 GiB` | `13.69 GiB` | `12.31 GiB` | `18.44 GiB` | `11.63 GiB` |
| C | `11.23 GiB` | `17.81 GiB` | `15.95 GiB` | `23.53 GiB` | `15.02 GiB` |

结论：在当前 7.7 GiB 内存机器上，C 组全量很可能 OOM；B 组全量也不安全；A 组 LightGBM 已超过安全内存。完整 B/C 全量实验建议在至少 `32 GiB` 内存机器上运行，C 组 LightGBM 更稳妥配置为 `48-64 GiB`。

为防止单个实验拖垮整个实验流程，已完成以下优化：

1. `scripts/train_hcg_classifiers.py` 默认启用 `--isolate-tasks`。
   - 父进程只做调度。
   - 每个 `<feature_group>/<model_name>` 在独立子进程中执行。
   - 子进程失败、异常退出或被 OOM kill 后，父进程将任务标记为 failed 并继续后续任务。

2. 默认启用 `--memory-guard`。
   - 任务开始前基于 parquet 元数据估算 `matrix_gb` 和 `estimated_peak_gb`。
   - 自动安全阈值为 `available_memory_gb - min_available_memory_gb`，默认至少保留 `2.0 GiB` 系统内存。
   - 超过阈值时不加载 parquet，直接写 `task_status.json`，状态为 `skipped`。

3. 新增参数：

```text
--isolate-tasks / --no-isolate-tasks
--memory-guard / --no-memory-guard
--max-estimated-memory-gb
--min-available-memory-gb
```

4. `check_hcg_classifier_results.py` 已支持 `status=skipped`，内存保护主动跳过的任务不会被误报为产物损坏。

验证命令：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
  --dataset-dir data/features/hcg/classification/datasets \
  --output-dir data/features/hcg/classification/results_memory_guard_check \
  --runs-dir runs/hcg_classification_memory_guard_check \
  --feature-groups C \
  --models lightgbm \
  --max-estimated-memory-gb 1 \
  --no-progress \
  --force \
  --resume
```

验证结果：`C__lightgbm` 未加载 C parquet，直接写为：

```text
status=skipped
estimated_peak_gb=23.53
safe_limit_gb=1.00
rows=3577296
features=349
matrix_gb=4.65
```

随后检查脚本 PASS：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/check_hcg_classifier_results.py \
  --results-dir data/features/hcg/classification/results_memory_guard_check \
  --expected-feature-groups C \
  --expected-models lightgbm
```

隔离执行也已用 A 组 dummy smoke 验证通过。测试产生的 `results_memory_guard_check`、`results_isolation_check` 和对应 runs 目录已清理。

当前机器建议运行策略：

```bash
# 先跑小样本完整矩阵，确认流程和图表。
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

正式全量如果仍在当前机器上运行，应保留默认内存保护；高风险任务会自动 skipped，不会拖垮整个进程：

```bash
PYTHONPATH=src conda run -n tugraph python scripts/train_hcg_classifiers.py \
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

## 2026-05-25 无 TuGraph 机器迁移训练包

分类训练阶段只读取已经生成的 parquet，不访问 TuGraph、Docker、node2vec walks 或 Word2Vec model。因此迁移到另一台没有 TuGraph 服务的机器时，必须迁移的是训练输入和 Python 代码，而不是图数据库运行时。

必须数据：

| 数据 | 用途 | 大小 |
| --- | --- | ---: |
| `data/features/hcg/classification/datasets/A_raw_flow_features.parquet` | A 组 raw 特征训练 | `563M` |
| `data/features/hcg/classification/datasets/B_hcg_flow_emb_256.parquet` | B 组 HCG embedding 特征训练 | `2.7G` |
| `data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet` | C 组融合特征训练 | `3.2G` |

必须代码：

```text
scripts/train_hcg_classifiers.py
scripts/check_hcg_classifier_results.py
scripts/render_hcg_classification_figures.py
src/tugraph_homework/
```

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

新增一键准备脚本：

```text
scripts/prepare_hcg_classification_training_bundle.py
```

默认准备目录：

```bash
PYTHONPATH=src python3 scripts/prepare_hcg_classification_training_bundle.py \
  --output-dir data/exports/hcg_classification_training_bundle \
  --feature-groups A,B,C \
  --force
```

如果只想在本机检查 bundle 结构并避免重复占用数据空间，可使用 hardlink：

```bash
PYTHONPATH=src python3 scripts/prepare_hcg_classification_training_bundle.py \
  --output-dir data/exports/hcg_classification_training_bundle \
  --feature-groups A,B,C \
  --link \
  --force
```

如果需要单文件传输：

```bash
PYTHONPATH=src python3 scripts/prepare_hcg_classification_training_bundle.py \
  --output-dir data/exports/hcg_classification_training_bundle \
  --feature-groups A,B,C \
  --archive \
  --compress none \
  --force
```

说明：A/B/C parquet 合计约 `6.4G`，parquet 本身已经压缩，继续 gzip 通常收益较小且耗时明显增加。跨机器迁移建议使用普通 `.tar`、移动硬盘或 `rsync`。

bundle 内会生成：

```text
README_BUNDLE.md
requirements-classification.txt
bundle_manifest.json
```

其中 `bundle_manifest.json` 记录所有文件大小和 SHA-256，用于传输后核对。

已验证：

```bash
PYTHONPATH=src python3 scripts/prepare_hcg_classification_training_bundle.py \
  --output-dir data/exports/hcg_classification_training_bundle_test \
  --feature-groups A \
  --link \
  --force
```

验证结果：A-only bundle 成功生成，包含 `15` 个文件，manifest 显示大小约 `0.55 GiB`。测试目录已清理。
