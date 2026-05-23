# 目录规划

本项目按“原始数据、处理结果、代码、文档、导出结果”分层。

| 目录 | 用途 |
| --- | --- |
| `data/raw/` | 原始下载数据，只做只读输入。 |
| `data/processed/hcg/` | HCG 中间 CSV：`endpoints.csv`、`communicates.csv`。 |
| `data/processed/tcg/` | TCG 中间文件：`flows` 和 `causes_full_parts/` 分区。 |
| `data/processed/reports/` | TCG 边数量估算报告。 |
| `data/exports/` | 从 TuGraph 或脚本导出的结果文件。 |
| `docker/tugraph-import/` | 可选的 TuGraph 原生导入 CSV 目录；CSV 生成脚本可把输出写到这里。 |
| `scripts/` | 数据检查、构图、查询视图、schema 初始化和原生导入配置入口脚本。 |
| `src/tugraph_homework/` | 共享转换和通用 Python 工具代码。 |
| `docs/` | 数据结构、建模方案、运行说明和唯一实验记录。 |

推荐所有重新生成的中间文件写入 `data/processed/`，该目录作为提交目录。实验过程只维护 [experiment_record.md](experiment_record.md) 这一份记录，后续数据下载、处理、校验、导入和查询实验都应持续更新该文档。

## CSV 生成

CSV 生成功能已完成，统一入口为 `scripts/prepare_processed_csv.py`。它只生成
中间文件，不连接 TuGraph：

```bash
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

如需给 TuGraph 原生导入准备 CSV，可把 `--output-root` 改成
`docker/tugraph-import`，输出结构会保持一致。

TuGraph 数据导入统一使用原生 `lgraph_import`。Bolt 入口只保留
`scripts/create_tugraph_schema.py`，用于在线创建图和 schema，不写入 CSV 数据。
