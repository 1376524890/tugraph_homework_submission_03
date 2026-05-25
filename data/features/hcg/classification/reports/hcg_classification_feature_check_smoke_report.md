# HCG Classification Feature Check Report

Overall status: **PASS**

## Inputs

| Dataset | Path |
| --- | --- |
| A | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets_smoke/A_raw_flow_features.parquet` |
| B | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets_smoke/B_hcg_flow_emb_256.parquet` |
| C | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets_smoke/C_raw_plus_hcg_flow_emb.parquet` |

## Metrics

| Metric | Value |
| --- | ---: |
| `row_count_A` | `100000` |
| `row_count_B` | `100000` |
| `row_count_C` | `100000` |
| `raw_feature_count_A` | `91` |
| `raw_feature_count_C` | `91` |
| `hcg_feature_count_B` | `258` |
| `hcg_feature_count_C` | `258` |
| `hcg_embedding_feature_count_B` | `256` |
| `hcg_embedding_feature_count_C` | `256` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `target_class_count` | `40` |
| `train_ratio` | `0.698760` |
| `valid_ratio` | `0.101170` |
| `test_ratio` | `0.200070` |
| `check_elapsed_seconds` | `1.170213` |

## Split Counts

| Split | Count | Ratio |
| --- | ---: | ---: |
| `train` | `69876` | `0.698760` |
| `valid` | `10117` | `0.101170` |
| `test` | `20007` | `0.200070` |

## Target Top 20

| Target | Count |
| --- | ---: |
| `HTTP` | `33885` |
| `GOOGLE` | `21310` |
| `HTTP_PROXY` | `13822` |
| `SSL` | `10172` |
| `HTTP_CONNECT` | `7744` |
| `YOUTUBE` | `3929` |
| `AMAZON` | `1509` |
| `MICROSOFT` | `1241` |
| `WINDOWS_UPDATE` | `1081` |
| `GMAIL` | `822` |
| `SKYPE` | `639` |
| `FACEBOOK` | `628` |
| `YAHOO` | `565` |
| `DROPBOX` | `439` |
| `CONTENT_FLASH` | `418` |
| `TWITTER` | `405` |
| `MSN` | `345` |
| `CLOUDFLARE` | `312` |
| `WIKIPEDIA` | `271` |
| `WHATSAPP` | `89` |

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
