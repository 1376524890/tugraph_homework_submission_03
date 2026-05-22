# 目录规划

本项目按“原始数据、重建结果、代码、文档、导出结果”分层。

| 目录 | 用途 |
| --- | --- |
| `data/raw/` | 原始下载数据，只做只读输入。 |
| `data/rebuild/hcg/` | HCG 中间 CSV：`endpoints.csv`、`communicates.csv`。 |
| `data/rebuild/tcg/` | TCG 中间文件：`flows` 和 `causes_full_parts/` 分区。 |
| `data/rebuild/reports/` | TCG 边数量估算报告。 |
| `data/exports/` | 从 TuGraph 或脚本导出的结果文件。 |
| `docker/tugraph-import/` | 可选的 TuGraph 原生导入 CSV 目录；CSV 生成脚本可把输出写到这里。 |
| `scripts/` | 可直接运行的入口脚本。 |
| `src/tugraph_homework/` | 共享 Python 工具代码。 |
| `docs/` | 数据结构、建模方案、运行说明。 |

推荐所有重新生成的中间文件写入 `data/rebuild/`，便于审阅和重复实验。

## CSV 生成

CSV 生成功能已完成，统一入口为 `scripts/prepare_processed_csv.py`。它只生成
中间文件，不连接 TuGraph：

```bash
PYTHONPATH=src python3 scripts/prepare_processed_csv.py \
  --csv data/raw/Dataset-Unicauca-Version2-87Atts.csv \
  --graph all \
  --output-root data/rebuild \
  --relation-types CR,PR,DHR,SHR \
  --chunk-size 1000000 \
  --max-candidate-edges 150000000
```

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

如需给 TuGraph 原生导入准备 CSV，可把 `--output-root` 改成
`docker/tugraph-import`，输出结构会保持一致。
