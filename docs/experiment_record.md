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

## 2026-05-23 TuGraph 导入策略

HCG 和 TCG 数据导入统一使用 TuGraph 原生 `lgraph_import`。Bolt 不再承担 CSV
数据写入，只保留 `scripts/create_tugraph_schema.py` 用于在线创建图和 schema。

原生导入配置入口：

```bash
PYTHONPATH=src python3 scripts/create_tugraph_import_config.py \
  --graph-type hcg \
  --processed-dir docker/tugraph-import/hcg \
  --local-import-root docker/tugraph-import \
  --container-import-root /import \
  --output docker/tugraph-import/hcg/import.json

PYTHONPATH=src python3 scripts/create_tugraph_import_config.py \
  --graph-type tcg \
  --processed-dir docker/tugraph-import/tcg \
  --local-import-root docker/tugraph-import \
  --container-import-root /import \
  --output docker/tugraph-import/tcg/import.json
```

在线只建图/schema：

```bash
PYTHONPATH=src python3 scripts/create_tugraph_schema.py --graph-type hcg
PYTHONPATH=src python3 scripts/create_tugraph_schema.py --graph-type tcg
```

## 2026-05-23 TuGraph 导入目录挂载与配置生成

为让运行中的 `tugraph-db` 容器访问原生导入目录，已重建同名容器并增加
`docker/tugraph-import:/import` 挂载。未执行 `lgraph_import` 数据导入。

当前 `tugraph-db` 挂载：

```text
docker/tugraph-data   -> /var/lib/lgraph/data
docker/tugraph-logs   -> /var/log/lgraph_log
docker/tugraph-import -> /import
```

为避免原生导入期间临时文件写入 Docker overlay，已创建宿主机临时目录：

```text
docker/tugraph-tmp -> /tmp
```

该目录位于 `/home` 分区，当前可用空间约 `77G`；运行 `lgraph_import` 的临时容器
应显式增加 `-v "$PWD/docker/tugraph-tmp:/tmp"`。

临时停止状态备份容器已按后续清理要求删除：

```text
tugraph-db-before-import-mount-20260523140024
```

`docker/tugraph-import` 使用 `data/processed` 的硬链接视图，避免复制第二份
全量 CSV 数据：

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

## 2026-05-23 原生导入前状态快照

记录时间：

```text
2026-05-23 14:11:09 CST +0800
```

导入前未执行 `lgraph_import`。当前目标容器状态：

| 容器 | 镜像 | 状态 | 端口 |
| --- | --- | --- | --- |
| `tugraph-db` | `custom-tugraph-runtime:latest` | Up 10 minutes | `7070`, `7687`, `9090` 映射到宿主机 |
| `tugraph-db-old-20260522122320` | `custom-tugraph-runtime:latest` | Up 17 hours | 无宿主机端口映射 |

目标容器详情：

```text
container_id=b6b8c0de2b28fbc1085f36b60d4d6e432125ba4a7ac1e1e9a98e5b1e99f7d80e
image=custom-tugraph-runtime:latest
image_id=b9ccb146827f
cmd=["lgraph_server","--enable_plugin","true"]
restart=always
```

目标容器挂载：

```text
/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-data:/var/lib/lgraph/data
/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-logs:/var/log/lgraph_log
/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-import:/import
```

长期运行的旧容器 `tugraph-db-old-20260522122320` 使用另一组宿主机目录：

```text
/home/marktom/tugraph/tugraph_data:/var/lib/lgraph/data
/home/marktom/tugraph/tugraph_logs:/var/log/lgraph_log
```

磁盘空间快照：

| 路径 | 文件系统 | 总量 | 已用 | 可用 | 使用率 |
| --- | --- | ---: | ---: | ---: | ---: |
| `/home` | `/dev/sdb1` | 196G | 109G | 77G | 59% |
| `/` | `/dev/sda3` | 31G | 27G | 2.8G | 91% |
| `/var/lib/lgraph/data` 容器内 | `/dev/sdb1` | 196G | 109G | 77G | 59% |
| `/import` 容器内 | `/dev/sdb1` | 196G | 109G | 77G | 59% |
| `/tmp` 长期运行容器内 | Docker overlay | 31G | 27G | 2.8G | 91% |

注意：长期运行的 `tugraph-db` 容器没有挂载 `/tmp`。执行原生导入时应使用
README 中的临时 `docker run --rm` 导入容器，并显式挂载：

```bash
-v "$PWD/docker/tugraph-tmp:/tmp"
```

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

当前 git 工作区在记录快照时无未提交变更。

导入前建议的回滚信息：

1. 如果 `lgraph_import` 失败且数据库目录不可用，先停止服务：

```bash
docker stop tugraph-db
```

2. 保留失败现场用于排查：

```bash
mv docker/tugraph-data docker/tugraph-data-failed-$(date +%Y%m%d%H%M%S)
mkdir -p docker/tugraph-data
```

3. 重新启动空数据目录的服务容器：

```bash
docker start tugraph-db
```

4. 如需恢复到本次导入前的空目标状态，可使用当前记录：导入前
`docker/tugraph-data` 仅约 `11M`，主要包含 TuGraph 元数据和插件文件。
