# TCG Word2Vec Flow Embedding Report

Overall status: **PASS**

## Inputs and Outputs

| Item | Path |
| --- | --- |
| walks | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/tcg_walks_d64_light_crpr.txt` |
| id map | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/tcg_node_id_map_d64_light_crpr.csv` |
| parquet | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/node2vec/tcg_flow_node2vec_d64_light_crpr.parquet` |
| gensim model | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/node2vec/tcg_flow_node2vec_d64_light_crpr.model` |
| log file | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/reports/tcg_word2vec_d64_light_crpr_report.log` |

## Training Parameters

| Parameter | Value |
| --- | ---: |
| `vector_size` | `64` |
| `window` | `5` |
| `min_count` | `1` |
| `sg` | `1` |
| `negative` | `5` |
| `sample` | `0.0001` |
| `epochs` | `3` |
| `workers` | `4` |
| `seed` | `20260528` |
| `max_lines` | `0` |

## Metrics

| Metric | Value |
| --- | ---: |
| `walk_line_count` | `5721388` |
| `sentence_count` | `5721388` |
| `empty_line_count` | `0` |
| `average_walk_length` | `7.683860` |
| `min_walk_length` | `2` |
| `max_walk_length` | `10` |
| `walk_unique_token_count` | `3213039` |
| `id_map_token_count` | `3213039` |
| `word2vec_vocab_token_count` | `3213039` |
| `parquet_row_count` | `3213039` |
| `missing_id_map_token_count` | `0` |
| `id_map_coverage` | `1.000000` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `vector_size` | `64` |
| `training_elapsed_seconds` | `834.774791` |
| `training_elapsed_minutes` | `13.912913` |
| `seed` | `20260528` |
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
| `record_id_non_empty` | PASS |
| `record_id_unique` | PASS |
| `vocab_equals_walk_unique_tokens` | PASS |

## Join Design

The parquet file contains Flow-level embeddings keyed by `record_id`.
Join to A/B/C datasets on `record_id` to create D/E/F feature sets.
Embedding dimension: 64

## Nearest Samples

- `rec_0002620021`: rec_0002619468 (0.9853), rec_0002620026 (0.9849), rec_0002620117 (0.9834), rec_0002611440 (0.9800), rec_0002621001 (0.9790)
- `rec_0001465371`: rec_0001465365 (0.9877), rec_0001521140 (0.9873), rec_0001519664 (0.9860), rec_0001465481 (0.9859), rec_0001518795 (0.9856)
- `rec_0002936165`: rec_0002935909 (0.9978), rec_0002935690 (0.9974), rec_0002936213 (0.9974), rec_0002936282 (0.9963), rec_0002935688 (0.9960)
- `rec_0002935686`: rec_0002936221 (0.9979), rec_0002936284 (0.9976), rec_0002936254 (0.9976), rec_0002936132 (0.9953), rec_0002936109 (0.9945)
- `rec_0002021386`: rec_0001967296 (0.9984), rec_0001968060 (0.9973), rec_0002021301 (0.9971), rec_0001967295 (0.9969), rec_0002020489 (0.9967)
- `rec_0002936132`: rec_0002936213 (0.9979), rec_0002935909 (0.9975), rec_0002935686 (0.9953), rec_0002936165 (0.9943), rec_0002936282 (0.9937)
- `rec_0001762444`: rec_0001891519 (0.9905), rec_0001815003 (0.9900), rec_0001892103 (0.9892), rec_0001814674 (0.9892), rec_0001814675 (0.9872)
- `rec_0001958691`: rec_0001956428 (0.9894), rec_0001956430 (0.9826), rec_0001956429 (0.9807), rec_0001958897 (0.9805), rec_0001959393 (0.9798)
- `rec_0001962657`: rec_0001960762 (0.9964), rec_0001963212 (0.9951), rec_0001963694 (0.9948), rec_0001963407 (0.9943), rec_0001963301 (0.9932)
- `rec_0001971067`: rec_0001968060 (0.9985), rec_0002020489 (0.9982), rec_0001970794 (0.9967), rec_0002021386 (0.9965), rec_0001967296 (0.9935)
