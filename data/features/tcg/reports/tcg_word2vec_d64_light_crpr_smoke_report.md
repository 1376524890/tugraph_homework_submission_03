# TCG Word2Vec Flow Embedding Report

Overall status: **PASS**

## Inputs and Outputs

| Item | Path |
| --- | --- |
| walks | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/tcg_walks_d64_light_crpr_smoke.txt` |
| id map | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/tcg_node_id_map_d64_light_crpr_smoke.csv` |
| parquet | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/node2vec/tcg_flow_node2vec_d64_light_crpr_smoke.parquet` |
| gensim model | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/node2vec/tcg_flow_node2vec_d64_light_crpr_smoke.model` |
| log file | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/reports/tcg_word2vec_d64_light_crpr_smoke_report.log` |

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
| `workers` | `4` |
| `seed` | `20260528` |
| `max_lines` | `0` |

## Metrics

| Metric | Value |
| --- | ---: |
| `walk_line_count` | `4000` |
| `sentence_count` | `4000` |
| `empty_line_count` | `0` |
| `average_walk_length` | `9.893500` |
| `min_walk_length` | `2` |
| `max_walk_length` | `10` |
| `walk_unique_token_count` | `6788` |
| `id_map_token_count` | `6788` |
| `word2vec_vocab_token_count` | `6788` |
| `parquet_row_count` | `6788` |
| `missing_id_map_token_count` | `0` |
| `id_map_coverage` | `1.000000` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `vector_size` | `64` |
| `training_elapsed_seconds` | `0.283314` |
| `training_elapsed_minutes` | `0.004722` |
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

- `rec_0000026676`: rec_0000004869 (0.4486), rec_0000003334 (0.4450), rec_0000098224 (0.4141), rec_0000002383 (0.3932), rec_0000028014 (0.3931)
- `rec_0000027517`: rec_0000003569 (0.4613), rec_0000001379 (0.4403), rec_0000002275 (0.4369), rec_0000002397 (0.4324), rec_0000100647 (0.4248)
- `rec_0000026547`: rec_0000002320 (0.4273), rec_0000000864 (0.4271), rec_0000001227 (0.4027), rec_0000000666 (0.3913), rec_0000037688 (0.3736)
- `rec_0000001654`: rec_0000006587 (0.4768), rec_0000002582 (0.4206), rec_0000080911 (0.4140), rec_0000000169 (0.3950), rec_0000027186 (0.3910)
- `rec_0000101714`: rec_0000000216 (0.4875), rec_0000097796 (0.4450), rec_0000002875 (0.4392), rec_0000005366 (0.4090), rec_0000000987 (0.3776)
- `rec_0000026675`: rec_0000027625 (0.4569), rec_0000001884 (0.4338), rec_0000002613 (0.4083), rec_0000025081 (0.3870), rec_0000075852 (0.3852)
- `rec_0000026383`: rec_0000057532 (0.4569), rec_0000001935 (0.4135), rec_0000003401 (0.3819), rec_0000001258 (0.3744), rec_0000017566 (0.3721)
- `rec_0000086952`: rec_0000003275 (0.4483), rec_0000027775 (0.4463), rec_0000018146 (0.4242), rec_0000000173 (0.4233), rec_0000002743 (0.4175)
- `rec_0000025779`: rec_0000000112 (0.4417), rec_0000012926 (0.4327), rec_0000030298 (0.4182), rec_0000087654 (0.4135), rec_0000016090 (0.3999)
- `rec_0000081404`: rec_0000000953 (0.4990), rec_0000000341 (0.4598), rec_0000001403 (0.4473), rec_0000001830 (0.4096), rec_0000000477 (0.3877)
