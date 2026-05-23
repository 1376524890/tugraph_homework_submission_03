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
