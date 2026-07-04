# TCG Word2Vec Flow Embedding Report

Overall status: **PASS**

## Inputs and Outputs

| Item | Path |
| --- | --- |
| walks | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/tcg_walks_d128_light_shrcr.txt` |
| id map | `/home/marktom/tugraph/tugraph_homework_submission_03/docker/tugraph-tmp/tcg_node_id_map_d128_light_shrcr.csv` |
| parquet | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/node2vec/tcg_flow_node2vec_d128_light_shrcr.parquet` |
| gensim model | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/node2vec/tcg_flow_node2vec_d128_light_shrcr.model` |
| log file | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/tcg/reports/tcg_word2vec_d128_light_shrcr_report.log` |

## Training Parameters

| Parameter | Value |
| --- | ---: |
| `vector_size` | `128` |
| `window` | `5` |
| `min_count` | `1` |
| `sg` | `1` |
| `negative` | `5` |
| `sample` | `0.0001` |
| `epochs` | `5` |
| `workers` | `4` |
| `seed` | `20260528` |
| `max_lines` | `0` |

## Metrics

| Metric | Value |
| --- | ---: |
| `walk_line_count` | `7224400` |
| `sentence_count` | `7224400` |
| `empty_line_count` | `0` |
| `average_walk_length` | `6.912853` |
| `min_walk_length` | `2` |
| `max_walk_length` | `20` |
| `walk_unique_token_count` | `2185404` |
| `id_map_token_count` | `2185404` |
| `word2vec_vocab_token_count` | `2185404` |
| `parquet_row_count` | `2185404` |
| `missing_id_map_token_count` | `0` |
| `id_map_coverage` | `1.000000` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `vector_size` | `128` |
| `training_elapsed_seconds` | `1415.907366` |
| `training_elapsed_minutes` | `23.598456` |
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
Embedding dimension: 128

## Nearest Samples

- `rec_0000594837`: rec_0000594835 (0.9898), rec_0000593076 (0.9864), rec_0000593148 (0.9859), rec_0000593420 (0.9855), rec_0000593011 (0.9853)
- `rec_0000594826`: rec_0000594822 (0.9940), rec_0000594809 (0.9888), rec_0000591833 (0.9864), rec_0000592601 (0.9856), rec_0000591898 (0.9847)
- `rec_0000101882`: rec_0000101643 (0.9974), rec_0000101712 (0.9970), rec_0000101682 (0.9963), rec_0000101722 (0.9962), rec_0000101638 (0.9959)
- `rec_0000101884`: rec_0000101845 (0.9968), rec_0000004379 (0.9968), rec_0000101868 (0.9964), rec_0000101618 (0.9961), rec_0000101215 (0.9960)
- `rec_0000101727`: rec_0000101704 (0.9962), rec_0000101166 (0.9962), rec_0000101156 (0.9960), rec_0000101025 (0.9960), rec_0000101310 (0.9958)
- `rec_0000594832`: rec_0000594830 (0.9939), rec_0000594821 (0.9911), rec_0000594813 (0.9893), rec_0000590628 (0.9848), rec_0000594794 (0.9841)
- `rec_0000101864`: rec_0000101459 (0.9974), rec_0000101792 (0.9973), rec_0000101713 (0.9972), rec_0000101777 (0.9971), rec_0000101259 (0.9965)
- `rec_0000101705`: rec_0000101656 (0.9914), rec_0000059017 (0.9913), rec_0000100860 (0.9909), rec_0000101322 (0.9889), rec_0000053936 (0.9881)
- `rec_0000101890`: rec_0000101604 (0.9913), rec_0000101714 (0.9898), rec_0000100928 (0.9890), rec_0000101737 (0.9882), rec_0000101833 (0.9879)
- `rec_0000128443`: rec_0000128351 (0.9950), rec_0000128378 (0.9949), rec_0000128218 (0.9949), rec_0000128423 (0.9948), rec_0000128364 (0.9947)
