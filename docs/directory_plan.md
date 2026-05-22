# 目录规划

本项目按“原始数据、派生数据、代码、文档、归档”分层。

| 目录 | 用途 |
| --- | --- |
| `data/raw/` | 原始下载数据，只做只读输入。当前 CSV 已移动到这里。 |
| `data/processed/` | 清洗、抽样、聚合后的中间文件。 |
| `data/exports/` | 从 TuGraph 或脚本导出的结果文件。 |
| `scripts/` | 可直接运行的入口脚本。 |
| `src/tugraph_homework/` | 共享 Python 工具代码。 |
| `docs/` | 数据结构、建模方案、运行说明。 |
| `archive/` | 旧脚本、旧文档、历史实验输出归档。 |

兼容处理：`data/Dataset-Unicauca-Version2-87Atts.csv` 保留为指向 `data/raw/` 的符号链接。
