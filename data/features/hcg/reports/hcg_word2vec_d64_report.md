# HCG Word2Vec Endpoint Embedding Report

Overall status: **PASS**

## Inputs and Outputs

| Item | Path |
| --- | --- |
| walks | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt` |
| id map | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv` |
| parquet | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet` |
| gensim model | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.model` |
| log file | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/reports/hcg_word2vec_d64_report.log` |

## Training Parameters

| Parameter | Value |
| --- | ---: |
| `vector_size` | `64` |
| `window` | `5` |
| `min_count` | `1` |
| `sg` | `1` |
| `negative` | `5` |
| `sample` | `0.0001` |
| `epochs` | `5` |
| `workers` | `4` |
| `seed` | `20260525` |
| `max_lines` | `0` |

## Metrics

| Metric | Value |
| --- | ---: |
| `walk_line_count` | `4329750` |
| `sentence_count` | `4329750` |
| `empty_line_count` | `0` |
| `average_walk_length` | `10.013793` |
| `min_walk_length` | `2` |
| `max_walk_length` | `20` |
| `walk_unique_token_count` | `933050` |
| `id_map_token_count` | `933050` |
| `word2vec_vocab_token_count` | `933050` |
| `parquet_row_count` | `933050` |
| `missing_id_map_token_count` | `0` |
| `id_map_coverage` | `1.000000` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `vector_size` | `64` |
| `training_elapsed_seconds` | `537.667627` |
| `training_elapsed_minutes` | `8.961127` |
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
| `full_rows_equal_expected_933050` | PASS |

## Downstream Join Design

The parquet file contains Endpoint-level features, not flow-level features. Join `endpoint_id` to flow `src_endpoint` and `dst_endpoint`, then build:

```text
src_emb = emb(src_endpoint)
dst_emb = emb(dst_endpoint)
flow_emb = concat(src_emb, dst_emb, abs(src_emb - dst_emb), src_emb * dst_emb)
```

For 64-dimensional endpoint embeddings, `flow_emb` has 256 dimensions.

## Nearest Samples

- `10.200.7.8:3128`: 192.168.142.40:53635 (0.9723), 192.168.142.61:2449 (0.9715), 192.168.10.115:49804 (0.9714), 192.168.42.114:50218 (0.9713), 10.230.1.3:49365 (0.9709)
- `10.200.7.7:3128`: 192.168.41.41:52573 (0.9736), 192.168.180.37:1845 (0.9722), 192.168.180.14:40203 (0.9706), 192.168.150.5:41813 (0.9703), 192.168.10.74:52446 (0.9700)
- `10.200.7.9:3128`: 192.168.60.7:49492 (0.9387), 192.168.72.93:50079 (0.9386), 192.168.42.57:64484 (0.9371), 192.168.42.77:65410 (0.9369), 192.168.72.35:55832 (0.9367)
- `10.200.7.5:3128`: 192.168.142.68:49249 (0.8968), 192.168.32.80:52800 (0.8932), 192.168.220.176:59212 (0.8931), 192.168.60.29:49533 (0.8910), 192.168.42.31:50683 (0.8909)
- `10.200.7.6:3128`: 192.168.81.7:49210 (0.8439), 192.168.112.14:58688 (0.8415), 10.230.1.240:62495 (0.8413), 192.168.72.35:50349 (0.8408), 192.168.72.35:50377 (0.8406)
- `10.200.7.4:3128`: 192.168.130.93:51084 (0.8178), 192.168.110.20:54695 (0.8100), 192.168.72.50:50849 (0.8080), 192.168.31.3:51150 (0.8078), 192.168.180.51:57859 (0.8074)
- `179.1.4.230:443`: 10.200.7.199:46331 (0.9807), 10.200.7.217:55169 (0.9708), 10.200.7.218:55023 (0.9696), 10.200.7.196:60711 (0.9664), 104.16.144.50:443 (0.9651)
- `179.1.4.244:443`: 10.200.7.218:45609 (0.9753), 74.125.3.57:443 (0.9717), 54.192.90.80:80 (0.9689), 10.200.7.217:54750 (0.9663), 34.206.168.166:443 (0.9645)
- `179.1.4.251:443`: 10.200.7.194:43600 (0.9714), 198.145.13.11:443 (0.9688), 10.200.7.218:48586 (0.9669), 72.246.211.85:443 (0.9660), 10.200.7.218:42487 (0.9657)
- `179.1.4.231:443`: 54.192.160.223:443 (0.9717), 199.187.193.133:443 (0.9694), 10.200.7.218:41071 (0.9690), 10.200.7.196:54834 (0.9664), 54.192.90.6:80 (0.9647)
