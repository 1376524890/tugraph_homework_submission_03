# HCG Classification Feature Build Report

Overall status: **PASS**

## Inputs

| Item | Path |
| --- | --- |
| raw_csv | `/home/marktom/tugraph/tugraph_homework_submission_03/data/raw/Dataset-Unicauca-Version2-87Atts.csv` |
| embedding | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/node2vec/hcg_endpoint_node2vec_d64.parquet` |

## Outputs

| Dataset | Path |
| --- | --- |
| A | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets_smoke_multichunk/A_raw_flow_features.parquet` |
| B | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets_smoke_multichunk/B_hcg_flow_emb_256.parquet` |
| C | `/home/marktom/tugraph/tugraph_homework_submission_03/data/features/hcg/classification/datasets_smoke_multichunk/C_raw_plus_hcg_flow_emb.parquet` |

## Metrics

| Metric | Value |
| --- | ---: |
| `raw_read_rows` | `100000` |
| `output_rows` | `100000` |
| `max_rows` | `100000` |
| `target` | `protocol_name` |
| `target_class_count` | `40` |
| `embedding_endpoint_count` | `933050` |
| `src_embedding_missing_count` | `0` |
| `src_embedding_missing_ratio` | `0.000000` |
| `dst_embedding_missing_count` | `137` |
| `dst_embedding_missing_ratio` | `0.001370` |
| `any_embedding_missing_count` | `137` |
| `any_embedding_missing_ratio` | `0.001370` |
| `A_raw_feature_count` | `91` |
| `B_hcg_feature_count` | `258` |
| `C_feature_count` | `349` |
| `timestamp_parse_failed_count` | `0` |
| `nan_count` | `0` |
| `inf_count` | `0` |
| `build_elapsed_seconds` | `23.504836` |
| `split_method` | `deterministic_target_record_hash` |

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

## Split Distribution

| Split | Count |
| --- | ---: |
| `train` | `69876` |
| `valid` | `10117` |
| `test` | `20007` |

## Checks

| Check | Result |
| --- | --- |
| `A_file_exists` | PASS |
| `B_file_exists` | PASS |
| `C_file_exists` | PASS |
| `rows_non_empty` | PASS |
| `raw_features_non_empty` | PASS |
| `hcg_feature_count_is_258` | PASS |
| `hcg_embedding_feature_count_is_256` | PASS |
| `C_feature_count_matches` | PASS |
| `no_nan` | PASS |
| `no_inf` | PASS |
| `target_non_empty` | PASS |
| `split_non_empty` | PASS |

## Raw Features

`raw_source_port`, `raw_destination_port`, `raw_protocol`, `raw_flow_duration`, `raw_total_fwd_packets`, `raw_total_backward_packets`, `raw_total_length_of_fwd_packets`, `raw_total_length_of_bwd_packets`, `raw_fwd_packet_length_max`, `raw_fwd_packet_length_min`, `raw_fwd_packet_length_mean`, `raw_fwd_packet_length_std`, `raw_bwd_packet_length_max`, `raw_bwd_packet_length_min`, `raw_bwd_packet_length_mean`, `raw_bwd_packet_length_std`, `raw_flow_bytes_s`, `raw_flow_packets_s`, `raw_flow_iat_mean`, `raw_flow_iat_std`, `raw_flow_iat_max`, `raw_flow_iat_min`, `raw_fwd_iat_total`, `raw_fwd_iat_mean`, `raw_fwd_iat_std`, `raw_fwd_iat_max`, `raw_fwd_iat_min`, `raw_bwd_iat_total`, `raw_bwd_iat_mean`, `raw_bwd_iat_std`, `raw_bwd_iat_max`, `raw_bwd_iat_min`, `raw_fwd_psh_flags`, `raw_bwd_psh_flags`, `raw_fwd_urg_flags`, `raw_bwd_urg_flags`, `raw_fwd_header_length`, `raw_bwd_header_length`, `raw_fwd_packets_s`, `raw_bwd_packets_s`, `raw_min_packet_length`, `raw_max_packet_length`, `raw_packet_length_mean`, `raw_packet_length_std`, `raw_packet_length_variance`, `raw_fin_flag_count`, `raw_syn_flag_count`, `raw_rst_flag_count`, `raw_psh_flag_count`, `raw_ack_flag_count`, `raw_urg_flag_count`, `raw_cwe_flag_count`, `raw_ece_flag_count`, `raw_down_up_ratio`, `raw_average_packet_size`, `raw_avg_fwd_segment_size`, `raw_avg_bwd_segment_size`, `raw_fwd_header_length_1`, `raw_fwd_avg_bytes_bulk`, `raw_fwd_avg_packets_bulk`, `raw_fwd_avg_bulk_rate`, `raw_bwd_avg_bytes_bulk`, `raw_bwd_avg_packets_bulk`, `raw_bwd_avg_bulk_rate`, `raw_subflow_fwd_packets`, `raw_subflow_fwd_bytes`, `raw_subflow_bwd_packets`, `raw_subflow_bwd_bytes`, `raw_init_win_bytes_forward`, `raw_init_win_bytes_backward`, `raw_act_data_pkt_fwd`, `raw_min_seg_size_forward`, `raw_active_mean`, `raw_active_std`, `raw_active_max`, `raw_active_min`, `raw_idle_mean`, `raw_idle_std`, `raw_idle_max`, `raw_idle_min`, `raw_timestamp_epoch`, `raw_hour`, `raw_dayofweek`, `raw_src_port`, `raw_dst_port`, `raw_src_is_common_service_port`, `raw_dst_is_common_service_port`, `raw_src_is_proxy_port`, `raw_dst_is_proxy_port`, `raw_src_port_bucket_code`, `raw_dst_port_bucket_code`

## HCG Features

258 columns: `hcg_src_emb_*`, `hcg_dst_emb_*`, `hcg_absdiff_emb_*`, `hcg_prod_emb_*`, and missing flags.

## Removed Columns

None
