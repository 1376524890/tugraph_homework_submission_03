# TCG Classification Dataset Check Report

Overall status: **PASS**

## D

- Path: `/home/u2023312303/裴的实验/tugraph_homework_submission_03/data/features/tcg/classification/datasets/D_tcg_flow_node2vec_d64_light_crpr.parquet`
- Status: **PASS**
- Rows: 3577296
- Columns: 70
- Feature columns: 65
- TCG emb columns: 64

| Check | Result |
| --- | --- |
| `exists` | PASS |
| `rows_equal_A` | PASS |
| `record_id_unique` | PASS |
| `record_id_order_matches_A` | PASS |
| `target_matches_A` | PASS |
| `split_matches_A` | PASS |
| `tcg_emb_col_count_64` | PASS |
| `has_tcg_emb_missing_flag` | PASS |
| `no_nan` | PASS |
| `no_inf` | PASS |

## E

- Path: `/home/u2023312303/裴的实验/tugraph_homework_submission_03/data/features/tcg/classification/datasets/E_raw_plus_tcg_d64_light_crpr.parquet`
- Status: **PASS**
- Rows: 3577296
- Columns: 161
- Feature columns: 156
- TCG emb columns: 64

| Check | Result |
| --- | --- |
| `exists` | PASS |
| `rows_equal_A` | PASS |
| `record_id_unique` | PASS |
| `record_id_order_matches_A` | PASS |
| `target_matches_A` | PASS |
| `split_matches_A` | PASS |
| `tcg_emb_col_count_64` | PASS |
| `has_tcg_emb_missing_flag` | PASS |
| `contains_all_A_feature_columns` | PASS |
| `no_nan` | PASS |
| `no_inf` | PASS |

## F

- Path: `/home/u2023312303/裴的实验/tugraph_homework_submission_03/data/features/tcg/classification/datasets/F_raw_plus_hcg_plus_tcg_d64_light_crpr.parquet`
- Status: **PASS**
- Rows: 3577296
- Columns: 419
- Feature columns: 414
- TCG emb columns: 64

| Check | Result |
| --- | --- |
| `exists` | PASS |
| `rows_equal_A` | PASS |
| `record_id_unique` | PASS |
| `record_id_order_matches_A` | PASS |
| `target_matches_A` | PASS |
| `split_matches_A` | PASS |
| `tcg_emb_col_count_64` | PASS |
| `has_tcg_emb_missing_flag` | PASS |
| `rows_equal_C` | PASS |
| `record_id_order_matches_C` | PASS |
| `target_matches_C` | PASS |
| `split_matches_C` | PASS |
| `contains_all_C_feature_columns` | PASS |
| `no_nan` | PASS |
| `no_inf` | PASS |

