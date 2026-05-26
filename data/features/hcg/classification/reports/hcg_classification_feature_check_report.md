# HCG Classification Feature Check Report

Overall status: **PASS**

## Inputs

| Dataset | Path |
| --- | --- |
| A | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets/A_raw_flow_features.parquet` |
| B | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets/B_hcg_flow_emb_256.parquet` |
| C | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets/C_raw_plus_hcg_flow_emb.parquet` |

## Metrics

| Metric | Value |
| --- | ---: |
| `row_count_A` | `3577296` |
| `row_count_B` | `3577296` |
| `row_count_C` | `3577296` |
| `raw_feature_count_A` | `91` |
| `raw_feature_count_C` | `91` |
| `hcg_feature_count_B` | `258` |
| `hcg_feature_count_C` | `258` |
| `hcg_embedding_feature_count_B` | `256` |
| `hcg_embedding_feature_count_C` | `256` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `target_class_count` | `78` |
| `train_ratio` | `0.699906` |
| `valid_ratio` | `0.100031` |
| `test_ratio` | `0.200063` |
| `check_elapsed_seconds` | `61.021059` |

## Split Counts

| Split | Count | Ratio |
| --- | ---: | ---: |
| `train` | `2503770` | `0.699906` |
| `valid` | `357840` | `0.100031` |
| `test` | `715686` | `0.200063` |

## Target Top 20

| Target | Count |
| --- | ---: |
| `GOOGLE` | `959110` |
| `HTTP` | `683734` |
| `HTTP_PROXY` | `623210` |
| `SSL` | `404883` |
| `HTTP_CONNECT` | `317526` |
| `YOUTUBE` | `170781` |
| `AMAZON` | `86875` |
| `MICROSOFT` | `54710` |
| `GMAIL` | `40260` |
| `WINDOWS_UPDATE` | `34471` |
| `SKYPE` | `30657` |
| `FACEBOOK` | `29033` |
| `DROPBOX` | `25102` |
| `YAHOO` | `21268` |
| `TWITTER` | `18259` |
| `CLOUDFLARE` | `14737` |
| `MSN` | `14478` |
| `CONTENT_FLASH` | `8589` |
| `APPLE` | `7615` |
| `OFFICE_365` | `5941` |

## Checks

| Check | Result |
| --- | --- |
| `A_file_exists` | PASS |
| `B_file_exists` | PASS |
| `C_file_exists` | PASS |
| `row_counts_match` | PASS |
| `record_id_unique_A` | PASS |
| `record_id_unique_B` | PASS |
| `record_id_unique_C` | PASS |
| `record_id_order_match` | PASS |
| `target_match` | PASS |
| `split_match` | PASS |
| `A_has_raw_features` | PASS |
| `B_has_expected_hcg_embedding_dim` | PASS |
| `B_has_missing_flags` | PASS |
| `C_has_raw_and_hcg` | PASS |
| `C_raw_feature_count_matches_A` | PASS |
| `C_hcg_feature_count_matches_B` | PASS |
| `no_nan` | PASS |
| `no_inf` | PASS |
| `target_non_empty` | PASS |
| `split_non_empty` | PASS |
| `split_contains_train_valid_test` | PASS |
| `split_ratio_close_to_expected` | PASS |
