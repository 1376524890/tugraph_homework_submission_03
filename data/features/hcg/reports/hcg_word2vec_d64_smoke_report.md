# HCG Word2Vec Endpoint Embedding Report

Overall status: **PASS**

## Inputs and Outputs

| Item | Path |
| --- | --- |
| walks | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt` |
| id map | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv` |
| parquet | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/node2vec/hcg_endpoint_node2vec_d64_smoke.parquet` |
| gensim model | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/node2vec/hcg_endpoint_node2vec_d64_smoke.model` |
| log file | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/reports/hcg_word2vec_d64_smoke_report.log` |

## Training Parameters

| Parameter | Value |
| --- | ---: |
| `vector_size` | `64` |
| `window` | `5` |
| `min_count` | `1` |
| `sg` | `1` |
| `negative` | `5` |
| `sample` | `0.0001` |
| `epochs` | `1` |
| `workers` | `8` |
| `seed` | `20260525` |
| `max_lines` | `100000` |

## Metrics

| Metric | Value |
| --- | ---: |
| `walk_line_count` | `100000` |
| `sentence_count` | `100000` |
| `empty_line_count` | `0` |
| `average_walk_length` | `10.209230` |
| `min_walk_length` | `2` |
| `max_walk_length` | `20` |
| `walk_unique_token_count` | `177761` |
| `id_map_token_count` | `933050` |
| `word2vec_vocab_token_count` | `177761` |
| `parquet_row_count` | `177761` |
| `missing_id_map_token_count` | `0` |
| `id_map_coverage` | `1.000000` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `vector_size` | `64` |
| `training_elapsed_seconds` | `11.047280` |
| `training_elapsed_minutes` | `0.184121` |
| `seed` | `20260525` |
| `id_map_coverage_percent` | `100.000000` |

## Runtime Dependencies

| Package | Version |
| --- | --- |
| `gensim` | `4.4.0` |
| `numpy` | `2.4.6` |
| `pandas` | `3.0.3` |
| `pyarrow` | `24.0.0` |

## Checks

| Check | Result |
| --- | --- |
| `walks_read` | PASS |
| `vocab_non_empty` | PASS |
| `parquet_rows_equal_vocab` | PASS |
| `no_nan` | PASS |
| `no_inf` | PASS |
| `id_map_no_missing_tokens` | PASS |
| `vocab_equals_walk_unique_tokens` | PASS |

## Downstream Join Design

The parquet file contains Endpoint-level features, not flow-level features. Join `endpoint_id` to flow `src_endpoint` and `dst_endpoint`, then build:

```text
src_emb = emb(src_endpoint)
dst_emb = emb(dst_endpoint)
flow_emb = concat(src_emb, dst_emb, abs(src_emb - dst_emb), src_emb * dst_emb)
```

For 64-dimensional endpoint embeddings, `flow_emb` has 256 dimensions.

## Nearest Samples

- `10.200.7.7:3128`: 10.200.7.6:3128 (0.9986), 10.200.7.8:3128 (0.9986), 10.200.7.9:3128 (0.9985), 10.200.7.4:3128 (0.9984), 179.1.4.224:443 (0.9982)
- `10.200.7.8:3128`: 10.200.7.4:3128 (0.9997), 10.200.7.6:3128 (0.9997), 179.1.4.245:443 (0.9990), 179.1.4.238:443 (0.9990), 179.1.4.231:443 (0.9990)
- `10.200.7.6:3128`: 10.200.7.8:3128 (0.9997), 10.200.7.4:3128 (0.9996), 179.1.4.217:443 (0.9991), 179.1.4.209:443 (0.9989), 179.1.4.224:443 (0.9988)
- `10.200.7.9:3128`: 10.200.7.8:3128 (0.9988), 10.200.7.4:3128 (0.9988), 10.200.7.6:3128 (0.9987), 10.200.7.7:3128 (0.9985), 172.217.29.45:443 (0.9983)
- `10.200.7.4:3128`: 10.200.7.8:3128 (0.9997), 10.200.7.6:3128 (0.9996), 179.1.4.223:443 (0.9988), 179.1.4.245:443 (0.9988), 179.1.4.217:443 (0.9988)
- `10.200.7.5:3128`: 10.200.7.4:3128 (0.9958), 10.200.7.6:3128 (0.9957), 10.200.7.8:3128 (0.9956), 162.208.22.34:80 (0.9953), 52.1.10.16:80 (0.9952)
- `179.1.4.230:443`: 10.200.7.4:3128 (0.9988), 10.200.7.8:3128 (0.9988), 179.1.4.216:443 (0.9986), 10.200.7.6:3128 (0.9985), 93.184.215.201:443 (0.9985)
- `104.91.156.236:80`: 10.200.7.8:3128 (0.9987), 179.1.4.216:443 (0.9986), 10.200.7.6:3128 (0.9986), 10.200.7.4:3128 (0.9983), 216.58.222.195:443 (0.9982)
- `179.1.4.244:443`: 179.1.4.245:443 (0.9984), 10.200.7.6:3128 (0.9984), 10.200.7.8:3128 (0.9984), 38.90.226.11:80 (0.9984), 10.200.7.4:3128 (0.9983)
- `179.1.4.251:443`: 10.200.7.8:3128 (0.9987), 179.1.4.223:443 (0.9987), 10.200.7.4:3128 (0.9986), 213.239.207.69:80 (0.9986), 179.1.4.217:443 (0.9986)
