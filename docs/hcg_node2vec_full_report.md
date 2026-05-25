# HCG Node2Vec 全量 Walk 生成报告

检查日期：2026-05-25

## 结论

HCG Node2Vec 全量 random walks 已生成并完成本地校验。产物覆盖 TuGraph HCG 图中所有有出边的 `Endpoint` 起点，共 `865,950` 个起点；按每个起点 `5` 条 walk 生成，共 `4,329,750` 条 walk。walk 文件无空行、无长度为 1 的 walk，最短长度为 `2`，最长长度为 `20`，可进入后续 Word2Vec / skip-gram 训练阶段。

## 生成配置

| 项目 | 值 |
| --- | --- |
| 图 | TuGraph `hcg` |
| 存储过程 | `hcg_node2vec_walk_py_batch` |
| 本地过程源码 | `procedures/hcg_node2vec_walk_py_batch.py` |
| 调用脚本 | `scripts/run_hcg_node2vec_procedure_batch.py` |
| 起点选择 | 仅选择有出边的 `Endpoint` |
| 起点数 | `865,950` |
| `walk_length` | `20` |
| `num_walks` | `5` |
| `p` | `1.0` |
| `q` | `1.0` |
| 边权字段 | `COMMUNICATES.flow_count` |
| 权重变换 | `log1p(flow_count)` |
| token 字段 | `Endpoint.endpoint_id` |
| batch size | `1,000` |
| batch 数 | `866` |
| seed | `20260524 + batch_index` |

执行命令：

```bash
PYTHONPATH=src python3 scripts/run_hcg_node2vec_procedure_batch.py \
  --batch-size 1000 \
  --walk-length 20 \
  --num-walks 5 \
  --p 1.0 \
  --q 1.0
```

## 输出文件

| 文件 | 规模 | 行数 |
| --- | ---: | ---: |
| `docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt` | `752M` | `4,329,750` |
| `docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv` | `25M` | `933,051` |

`id_map` 包含表头，所以有效映射行数为 `933,050`。检查结果：

| 项目 | 值 |
| --- | ---: |
| id map 有效行数 | `933,050` |
| 唯一 `vid` | `933,050` |
| 唯一 `token` | `933,050` |
| 空字段行数 | `0` |

## 运行统计

| 指标 | 值 |
| --- | ---: |
| 实际 batch 数 | `866` |
| 完成起点数 | `865,950` |
| 生成 walk 数 | `4,329,750` |
| 总耗时 | `27,048.01` 秒 |
| 总耗时 | `7.51` 小时 |
| 平均 batch 耗时 | `31.23` 秒 |
| 最短 batch 耗时 | `2.88` 秒 |
| 最长 batch 耗时 | `57.83` 秒 |
| 平均吞吐 | `160.08` walks/s |
| 平均起点吞吐 | `32.02` start nodes/s |
| 最后一个 batch | `865` |
| 最后一个 batch 起点数 | `950` |
| 剩余起点数 | `0` |

运行日志：

```text
logs/node2vec_batch_20260524_195009.log
```

日志尾部显示最后一个 batch `status=ok`，`weight_field=flow_count`，`weight_transform=log1p`，`token_field=endpoint_id`，`weight_fallback_count=0`，且最终合并到全量 walks 和 id map 文件。

## Walk 文件校验

校验命令：

```bash
PYTHONPATH=src python3 scripts/check_walks_file.py \
  --walks docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt \
  --expected-min-lines 4329750 \
  --min-walk-len 2 \
  --report data/features/hcg/reports/hcg_node2vec_py_full_check.md \
  --json-report data/features/hcg/reports/hcg_node2vec_py_full_check.json
```

校验结果：

| 指标 | 值 |
| --- | ---: |
| walk 行数 | `4,329,750` |
| 平均 walk 长度 | `10.0138` |
| 最短 walk 长度 | `2` |
| 最长 walk 长度 | `20` |
| 唯一 token 数 | `933,050` |
| 空行数 | `0` |
| 长度为 1 的 walk 比例 | `0.000000` |

检查项：

| 检查项 | 结果 |
| --- | --- |
| `line_count_at_least_expected` | PASS |
| `no_empty_lines` | PASS |
| `min_walk_len_ok` | PASS |

校验报告：

```text
data/features/hcg/reports/hcg_node2vec_py_full_check.md
data/features/hcg/reports/hcg_node2vec_py_full_check.json
```

## 说明

平均 walk 长度小于最大长度 `20`，原因是 HCG 是有向图；当游走到无出边顶点时，当前 walk 会提前结束。这不影响本次检查结论，因为所有输出 walk 长度均不小于 `2`，且起点覆盖和总行数与实验配置完全一致。

下一步进入 Endpoint embedding 训练，目标输出：

```text
data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet
```
