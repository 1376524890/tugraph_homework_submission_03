# HCG Endpoint Embedding Check

Overall status: **PASS**

## Inputs

| Item | Path |
| --- | --- |
| embeddings | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet` |
| id map | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/hcg_node_id_map_node2vec_py_full.csv` |
| walks | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/hcg_walks_node2vec_py_full.txt` |
| log file | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/reports/hcg_endpoint_node2vec_d64_check.log` |

## Metrics

| Metric | Value |
| --- | ---: |
| `row_count` | `933050` |
| `column_count` | `66` |
| `embedding_dim` | `64` |
| `expected_dim` | `64` |
| `missing_required_column_count` | `0` |
| `missing_required_columns` | `` |
| `extra_embedding_column_count` | `0` |
| `endpoint_id_unique_count` | `933050` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `id_map_token_count` | `933050` |
| `embedding_id_map_intersection_count` | `933050` |
| `embedding_not_in_id_map_token_count` | `0` |
| `id_map_not_trained_token_count` | `0` |
| `id_map_coverage_percent` | `100.000000` |
| `walk_unique_token_count` | `933050` |
| `walk_tokens_covered_count` | `933050` |
| `walk_tokens_missing_count` | `0` |
| `walk_token_coverage_percent` | `100.000000` |
| `check_elapsed_seconds` | `14.052392` |

## Checks

| Check | Result |
| --- | --- |
| `parquet_readable` | PASS |
| `required_columns_present` | PASS |
| `endpoint_id_non_empty` | PASS |
| `endpoint_id_unique` | PASS |
| `embedding_dim_matches_expected` | PASS |
| `no_extra_embedding_columns` | PASS |
| `no_nan` | PASS |
| `no_inf` | PASS |
| `row_count_at_least_expected_min` | PASS |
| `row_count_equals_expected` | PASS |
| `all_embeddings_in_id_map` | PASS |
| `all_walk_tokens_covered` | PASS |
