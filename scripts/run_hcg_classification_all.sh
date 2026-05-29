#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────
# Graph Feature Classification — 全量训练交互式脚本
# ──────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# ─────────────────── Hub 配置 ─────────────────────────────
DEFAULT_HCG_HF_REPO="MarkTom/IP-Network-Flow-HCG"
DEFAULT_HCG_MS_REPO="MarkTom/IP-Network-Flow-HCG"
DEFAULT_TCG_HF_REPO="MarkTom/IP-Network-Flow-Graph"
DEFAULT_TCG_MS_REPO="MarkTom/IP-Network-Flow-Graph"

# ─────────────────────── 颜色定义 ─────────────────────────
BOLD="\033[1m"
RED="\033[31m"; GREEN="\033[32m"; YELLOW="\033[33m"
BLUE="\033[34m"; CYAN="\033[36m"; MAGENTA="\033[35m"
RESET="\033[0m"

info()    { echo -e "${BLUE}[INFO]${RESET}    $*"; }
ok()      { echo -e "${GREEN}[OK]${RESET}      $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}    $*"; }
err()     { echo -e "${RED}[ERROR]${RESET}   $*"; }
header()  { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${RESET}\n"; }
prompt()  { echo -e "${MAGENTA}[?]${RESET} $*"; }

check_cmd() { command -v "$1" &>/dev/null; }

# ─────────────────────── 常量 ─────────────────────────────
HCG_DATASET_DIR="data/features/hcg/classification/datasets"
TCG_DATASET_DIR="data/features/tcg/classification/datasets"
HCG_OUTPUT_DIR="data/features/hcg/classification/results"
TCG_OUTPUT_DIR="data/features/tcg/classification/results"
HCG_RUNS_DIR="runs/hcg_classification"
TCG_RUNS_DIR="runs/tcg_classification"
HCG_REPORT_DIR="data/features/hcg/classification/reports"
TCG_REPORT_DIR="data/features/tcg/reports"
SEED=20260525

ALL_FEATURE_GROUPS=("A" "B" "C" "D" "E" "F")

declare -A DATASET_FILES=(
    ["A"]="A_raw_flow_features.parquet"
    ["B"]="B_hcg_flow_emb_256.parquet"
    ["C"]="C_raw_plus_hcg_flow_emb.parquet"
    ["D"]="D_tcg_flow_node2vec_d64_light_crpr.parquet"
    ["E"]="E_raw_plus_tcg_d64_light_crpr.parquet"
    ["F"]="F_raw_plus_hcg_plus_tcg_d64_light_crpr.parquet"
)

declare -A MODEL_DESC=(
    ["dummy"]="Dummy baselines (most_frequent + stratified)"
    ["logistic_sgd"]="Logistic Regression (SGD)"
    ["decision_tree"]="Decision Tree"
    ["lightgbm"]="LightGBM (GPU/CPU)"
    ["knn_sample"]="K-Nearest Neighbors"
)

# ───────────────────── 工具函数 ───────────────────────────
ask_yesno() {
    local msg="$1" default="${2:-y}"
    local hint="[Y/n]"
    if [ "$default" = "n" ]; then hint="[y/N]"; fi
    while true; do
        read -r -p "$(echo -e "${MAGENTA}[?]${RESET} $msg $hint: ")" answer
        answer="${answer:-$default}"
        case "${answer,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *)     echo "  请输入 y 或 n" ;;
        esac
    done
}

ask_selection() {
    local msg="$1"; shift
    local -n options_ref=$1; shift
    local -n selected_ref=$1; shift
    local max_choice="${#options_ref[@]}"

    echo -e "${MAGENTA}[?]${RESET} $msg"
    for i in "${!options_ref[@]}"; do
        local idx=$((i + 1))
        local desc="${options_ref[$i]}"
        echo -e "   ${BOLD}${idx}${RESET}) ${desc}"
    done
    while true; do
        read -r -p "$(echo -e "${MAGENTA}[?]${RESET} 输入数字选择 (1-${max_choice}): ")" choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$max_choice" ]; then
            selected_ref="${options_ref[$((choice - 1))]}"
            return 0
        fi
        echo "  无效选择，请输入 1-${max_choice}"
    done
}

ask_multiselect() {
    local msg="$1"; shift
    local -n opts_ref=$1; shift
    local -n result_ref=$1; shift
    local max_choice="${#opts_ref[@]}"

    echo -e "${MAGENTA}[?]${RESET} $msg"
    for i in "${!opts_ref[@]}"; do
        local idx=$((i + 1))
        local desc="${opts_ref[$i]}"
        echo -e "   ${BOLD}${idx}${RESET}) ${desc}"
    done
    echo -e "   ${BOLD}a${RESET}) 全选"
    while true; do
        read -r -p "$(echo -e "${MAGENTA}[?]${RESET} 输入数字，逗号分隔 (如 1,3,5 或 a): ")" raw
        if [ "$raw" = "a" ] || [ "$raw" = "A" ]; then
            result_ref=("${opts_ref[@]}")
            return 0
        fi
        local valid=true
        IFS=',' read -ra parts <<< "$raw"
        local selected=()
        for part in "${parts[@]}"; do
            part="$(echo "$part" | xargs)"
            if [[ "$part" =~ ^[0-9]+$ ]] && [ "$part" -ge 1 ] && [ "$part" -le "$max_choice" ]; then
                selected+=("${opts_ref[$((part - 1))]}")
            else
                echo "  无效选项: '$part'，请重新输入"
                valid=false
                break
            fi
        done
        if $valid && [ ${#selected[@]} -gt 0 ]; then
            result_ref=("${selected[@]}")
            return 0
        fi
    done
}

dataset_dir_for_group() {
    case "$1" in
        A|B|C) echo "$HCG_DATASET_DIR" ;;
        D|E|F) echo "$TCG_DATASET_DIR" ;;
        *) return 1 ;;
    esac
}

dataset_path_for_group() {
    local grp="$1"
    local dir
    dir="$(dataset_dir_for_group "$grp")"
    echo "${dir}/${DATASET_FILES[$grp]}"
}

# ──────────────────── 环境检查 ────────────────────────────
check_environment() {
    header "环境检查"

    # Python
    if ! check_cmd python3; then
        err "未找到 python3"
        return 1
    fi
    ok "python3: $(python3 --version 2>&1)"

    # Essential packages
    local missing_pkgs=()
    for pkg in numpy pandas pyarrow sklearn joblib; do
        if ! python3 -c "import ${pkg}" 2>/dev/null; then
            missing_pkgs+=("$pkg")
        fi
    done
    if [ ${#missing_pkgs[@]} -gt 0 ]; then
        warn "缺少 Python 包: ${missing_pkgs[*]}"
        if ask_yesno "是否安装缺失的依赖?" "y"; then
            pip install "${missing_pkgs[@]}"
        else
            err "请先安装依赖: pip install ${missing_pkgs[*]}"
            return 1
        fi
    fi
    ok "核心 Python 依赖已就绪"

    # LightGBM (optional)
    if python3 -c "import lightgbm" 2>/dev/null; then
        ok "lightgbm: $(python3 -c 'import lightgbm; print(lightgbm.__version__)' 2>/dev/null || echo 'ok')"
    else
        warn "lightgbm 未安装 — LightGBM 模型将被跳过"
    fi

    # GPU checks
    if check_cmd nvidia-smi 2>/dev/null; then
        local gpu_info
        gpu_info="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1 || echo 'unknown')"
        ok "GPU: $gpu_info"
    else
        warn "未检测到 nvidia-smi，GPU 后端不可用"
    fi

    # cuML (optional)
    if python3 -c "import cuml" 2>/dev/null; then
        ok "cuML (GPU KNN) 可用"
    fi

    # Dataset files
    echo ""
    info "扫描数据集文件..."
    local all_exist=true
    for grp in "${ALL_FEATURE_GROUPS[@]}"; do
        local fpath
        fpath="$(dataset_path_for_group "$grp")"
        if [ -f "$fpath" ]; then
            local size
            size="$(du -h "$fpath" 2>/dev/null | cut -f1)"
            ok "特征组 ${grp}: ${size} — ${fpath}"
        else
            warn "特征组 ${grp}: 缺失 — ${fpath}"
            all_exist=false
        fi
    done

    if ! $all_exist; then
        warn "某些特征数据集缺失"
        echo ""
        info "将自动准备 A/B/C 和 D/E/F；D 从 ModelScope/HuggingFace 获取后合成 E/F"
        if ! download_datasets; then
            err "数据集准备失败"
            return 1
        fi
    fi

    # Memory info
    if [ -f /proc/meminfo ]; then
        local mem_total mem_avail
        mem_total="$(grep MemTotal /proc/meminfo | awk '{printf "%.1fG", $2/1024/1024}')"
        mem_avail="$(grep MemAvailable /proc/meminfo | awk '{printf "%.1fG", $2/1024/1024}')"
        info "系统内存: 总计 ${mem_total}, 可用 ${mem_avail}"
    fi

    echo ""
    return 0
}

# ─────────────────── 数据下载 ─────────────────────────────
download_datasets() {
    header "数据集下载"

    local selected_hub="${DATA_HUB:-modelscope}"
    local hcg_repo_id tcg_repo_id
    if [ "$selected_hub" = "huggingface" ]; then
        hcg_repo_id="${HCG_REPO_ID:-$DEFAULT_HCG_HF_REPO}"
        tcg_repo_id="${TCG_REPO_ID:-$DEFAULT_TCG_HF_REPO}"
    else
        selected_hub="modelscope"
        hcg_repo_id="${HCG_REPO_ID:-$DEFAULT_HCG_MS_REPO}"
        tcg_repo_id="${TCG_REPO_ID:-$DEFAULT_TCG_MS_REPO}"
    fi

    ok "数据源: ${selected_hub}"
    info "HCG 仓库: ${hcg_repo_id}"
    info "TCG 仓库: ${tcg_repo_id}"

    # Check dependencies
    case "$selected_hub" in
        huggingface)
            if ! python3 -c "import huggingface_hub" 2>/dev/null; then
                warn "huggingface_hub 未安装"
                if ask_yesno "是否安装 huggingface_hub?" "y"; then
                    pip install huggingface_hub
                else
                    err "请先安装: pip install huggingface_hub"
                    return 1
                fi
            fi
            ;;
        modelscope)
            if ! python3 -c "import modelscope" 2>/dev/null; then
                warn "modelscope 未安装"
                if ask_yesno "是否安装 modelscope?" "y"; then
                    pip install modelscope
                else
                    err "请先安装: pip install modelscope"
                    return 1
                fi
            fi
            # 检查 ModelScope 登录状态
            if [ -z "${MODELSCOPE_API_TOKEN:-}" ] && ! python3 -c "
from modelscope.hub.api import HubApi
api = HubApi()
api.repo_exists('${hcg_repo_id}', repo_type='dataset')
api.repo_exists('${tcg_repo_id}', repo_type='dataset')
" 2>/dev/null; then
                warn "ModelScope 未登录（私有仓库需要认证）"
                if ask_yesno "是否现在登录 ModelScope?" "y"; then
                    info "获取地址: https://modelscope.cn/my/myaccesstoken"
                    read -r -p "$(echo -e "${MAGENTA}[?]${RESET} 请输入 ModelScope API Token: ")" ms_token
                    if [ -z "$ms_token" ]; then
                        err "Token 不能为空"
                        return 1
                    fi
                    modelscope login --token "$ms_token"
                    if [ $? -ne 0 ]; then
                        err "ModelScope 登录失败"
                        return 1
                    fi
                    ok "ModelScope 登录成功"
                else
                    err "私有仓库需要登录，请先运行: modelscope login --token <YOUR_TOKEN>"
                    return 1
                fi
            fi
            ;;
    esac

    if [ ! -f "${HCG_DATASET_DIR}/A_raw_flow_features.parquet" ] \
        || [ ! -f "${HCG_DATASET_DIR}/B_hcg_flow_emb_256.parquet" ] \
        || [ ! -f "${HCG_DATASET_DIR}/C_raw_plus_hcg_flow_emb.parquet" ]; then
        info "准备 A/B/C..."
        PYTHONPATH=src python3 scripts/download_datasets_from_hub.py \
            --hub "$selected_hub" \
            --repo-id "$hcg_repo_id" \
            --dataset-dir "$HCG_DATASET_DIR"
    else
        ok "A/B/C 已存在"
    fi

    info "准备 D/E/F..."
    PYTHONPATH=src python3 scripts/download_datasets_from_hub.py \
        --hub "$selected_hub" \
        --repo-id "$tcg_repo_id" \
        --dataset-dir "$TCG_DATASET_DIR"

    local rc=$?
    if [ $rc -eq 0 ]; then
        ok "数据集下载完成"
    else
        err "数据集下载失败 (exit code: $rc)"
        return 1
    fi

    echo ""
    return 0
}

# ─────────────────── 数据完整性检查 ───────────────────────
run_data_integrity_check() {
    header "数据完整性检查"

    local rc=0
    local hcg_json="${HCG_REPORT_DIR}/hcg_classification_feature_check_report.json"
    local tcg_json="${TCG_REPORT_DIR}/tcg_classification_feature_check_report.json"

    info "检查 A/B/C..."
    if ! env PYTHONPATH=src python3 scripts/check_hcg_classification_features.py \
        --dataset-dir "$HCG_DATASET_DIR" \
        --report "${HCG_REPORT_DIR}/hcg_classification_feature_check_report.md" \
        --json-report "$hcg_json"; then
        rc=1
    fi

    info "检查 D/E/F 及与 A/C 的 flow 对齐..."
    if ! env PYTHONPATH=src python3 scripts/check_tcg_classification_features.py \
        --a-path "${HCG_DATASET_DIR}/A_raw_flow_features.parquet" \
        --c-path "${HCG_DATASET_DIR}/C_raw_plus_hcg_flow_emb.parquet" \
        --dataset-dir "$TCG_DATASET_DIR" \
        --report "${TCG_REPORT_DIR}/tcg_classification_feature_check_report.md" \
        --json-report "$tcg_json"; then
        rc=1
    fi

    if [ $rc -eq 0 ]; then
        ok "数据完整性检查通过"
    else
        warn "数据完整性检查发现问题 (exit code: $rc)，详见报告"
        echo ""
        info "快速摘要:"
        HCG_JSON="$hcg_json" TCG_JSON="$tcg_json" python3 -c "
import json
import os
for label, path in [('HCG', os.environ['HCG_JSON']), ('TCG', os.environ['TCG_JSON'])]:
    if not os.path.exists(path):
        print(f'  {label}: report missing')
        continue
    with open(path) as f:
        r = json.load(f)
    print(f\"  {label}: {r.get('overall_status', 'N/A')}\")
    if label == 'TCG':
        for name, item in r.get('datasets', {}).items():
            print(f\"    {name}: {item.get('status', 'N/A')} rows={item.get('rows', 'N/A')} columns={item.get('columns', 'N/A')}\")
    else:
        print(f\"    row_count_A: {r.get('metrics', {}).get('row_count_A', 'N/A')}\")
        print(f\"    target_class_count: {r.get('metrics', {}).get('target_class_count', 'N/A')}\")
"
        if ! ask_yesno "数据检查未全部通过，是否继续训练?" "n"; then
            return 1
        fi
    fi

    echo ""
    return 0
}

# ──────────────────── 交互式配置 ──────────────────────────
interactive_config() {
    header "训练配置"

    # 1. 选择特征组
    local available_groups=()
    for grp in "${ALL_FEATURE_GROUPS[@]}"; do
        [ -f "$(dataset_path_for_group "$grp")" ] && available_groups+=("$grp")
    done
    if [ ${#available_groups[@]} -eq 0 ]; then
        err "无可用数据集"
        return 1
    fi

    local group_descriptions=()
    for grp in "${available_groups[@]}"; do
        case "$grp" in
            A) group_descriptions+=("A — 原始流特征 (raw features only)") ;;
            B) group_descriptions+=("B — HCG 图嵌入 256 维 (embedding only)") ;;
            C) group_descriptions+=("C — 原始特征 + HCG 嵌入拼接 (raw + embedding)") ;;
            D) group_descriptions+=("D — TCG Flow 图嵌入 64 维 (embedding only)") ;;
            E) group_descriptions+=("E — 原始特征 + TCG 嵌入拼接 (raw + TCG)") ;;
            F) group_descriptions+=("F — 原始特征 + HCG 嵌入 + TCG 嵌入拼接") ;;
        esac
    done

    local selected_descs=()
    ask_multiselect "选择特征组:" group_descriptions selected_descs

    FEATURE_GROUPS=()
    for desc in "${selected_descs[@]}"; do
        FEATURE_GROUPS+=("${desc:0:1}")
    done
    ok "特征组: ${FEATURE_GROUPS[*]}"

    # 2. 选择模型
    echo ""
    local model_options=()
    for m in dummy logistic_sgd decision_tree lightgbm knn_sample; do
        # Skip lightgbm if not installed
        if [ "$m" = "lightgbm" ] && ! python3 -c "import lightgbm" 2>/dev/null; then
            continue
        fi
        model_options+=("$m — ${MODEL_DESC[$m]}")
    done

    local selected_models=()
    ask_multiselect "选择模型:" model_options selected_models

    MODELS=()
    for desc in "${selected_models[@]}"; do
        MODELS+=("${desc%% *}")
    done
    ok "模型: ${MODELS[*]}"

    # 3. Logistic 后端 (如果选了 logistic_sgd)
    LOGISTIC_BACKEND="sklearn"
    if [[ " ${MODELS[*]} " =~ " logistic_sgd " ]]; then
        echo ""
        local lr_options=("sklearn — SGDClassifier (CPU, 单机多核)")
        if python3 -c "import torch" 2>/dev/null; then
            if python3 -c "import torch; print(torch.cuda.is_available())" 2>/dev/null | grep -q "True"; then
                lr_options+=("pytorch — PyTorch (GPU 加速)")
            else
                lr_options+=("pytorch — PyTorch (CPU fallback)")
            fi
        fi
        if [ ${#lr_options[@]} -gt 1 ]; then
            ask_selection "选择 Logistic Regression 后端:" lr_options LOGISTIC_BACKEND
            LOGISTIC_BACKEND="${LOGISTIC_BACKEND%% *}"
        fi
        ok "Logistic 后端: ${LOGISTIC_BACKEND}"
    fi

    # 4. LightGBM 设备 (如果选了 lightgbm)
    LIGHTGBM_DEVICE="cpu"
    if [[ " ${MODELS[*]} " =~ " lightgbm " ]]; then
        echo ""
        local lgb_options=("cpu — CPU 多线程训练")
        local has_cuda_lgb=false
        if check_cmd nvidia-smi 2>/dev/null; then
            # 检查 LightGBM 是否有 CUDA 支持
            if python3 -c "
import lightgbm, numpy as np
ds = lightgbm.Dataset(np.random.rand(10, 2), label=[0, 1]*5)
lightgbm.train({'device': 'cuda', 'verbose': -1, 'num_leaves': 2}, ds, num_boost_round=1)
" 2>/dev/null; then
                has_cuda_lgb=true
            else
                warn "当前 LightGBM 不支持 CUDA，需要安装 CUDA 版本"
                if ask_yesno "是否安装 CUDA 版 LightGBM? (conda install lightgbm=4.5.0=*cuda*)" "y"; then
                    info "正在安装 CUDA 版 LightGBM..."
                    conda install -y -c conda-forge "lightgbm=4.5.0=*cuda*" 2>&1 | tail -5
                    if python3 -c "
import lightgbm, numpy as np
ds = lightgbm.Dataset(np.random.rand(10, 2), label=[0, 1]*5)
lightgbm.train({'device': 'cuda', 'verbose': -1, 'num_leaves': 2}, ds, num_boost_round=1)
" 2>/dev/null; then
                        has_cuda_lgb=true
                        ok "CUDA 版 LightGBM 安装成功"
                    else
                        err "CUDA 版 LightGBM 安装后仍不可用，回退到 CPU"
                    fi
                fi
            fi
        fi
        if [ "$has_cuda_lgb" = true ]; then
            lgb_options+=("cuda — GPU 加速 (CUDA 版 LightGBM)")
        fi
        if [ ${#lgb_options[@]} -gt 1 ]; then
            ask_selection "选择 LightGBM 设备:" lgb_options LIGHTGBM_DEVICE
            LIGHTGBM_DEVICE="${LIGHTGBM_DEVICE%% *}"
        fi
        ok "LightGBM 设备: ${LIGHTGBM_DEVICE}"
    fi

    # 5. KNN 配置 (如果选了 knn_sample)
    KNN_BACKEND="sklearn"
    KNN_MODE="sample"
    KNN_TRAIN_SAMPLE=200000
    KNN_TEST_SAMPLE=100000
    if [[ " ${MODELS[*]} " =~ " knn_sample " ]]; then
        echo ""
        header "KNN 配置"

        # Backend selection
        local knn_backend_options=("sklearn — CPU (sklearn KNeighborsClassifier)")
        if python3 -c "import cuml" 2>/dev/null; then
            knn_backend_options+=("cuml — GPU 全量 (cuML, 无需采样)")
        fi
        ask_selection "选择 KNN 后端:" knn_backend_options KNN_BACKEND
        KNN_BACKEND="${KNN_BACKEND%% *}"
        ok "KNN 后端: ${KNN_BACKEND}"

        # If sklearn, ask about full vs sample
        if [ "$KNN_BACKEND" = "sklearn" ]; then
            echo ""
            local knn_mode_options=(
                "sample — 采样模式 (快速，默认训练 20w / 测试 10w)"
                "full — 全量模式 (完整数据集，需要大量内存和时间)"
            )
            ask_selection "选择 KNN 模式:" knn_mode_options KNN_MODE
            KNN_MODE="${KNN_MODE%% *}"
            ok "KNN 模式: ${KNN_MODE}"

            if [ "$KNN_MODE" = "sample" ]; then
                echo ""
                while true; do
                    read -r -p "$(echo -e "${MAGENTA}[?]${RESET} 训练集采样数 [默认 200000]: ")" val
                    val="${val:-200000}"
                    if [[ "$val" =~ ^[0-9]+$ ]] && [ "$val" -gt 0 ]; then
                        KNN_TRAIN_SAMPLE="$val"
                        break
                    fi
                    echo "  请输入正整数"
                done
                while true; do
                    read -r -p "$(echo -e "${MAGENTA}[?]${RESET} 验证/测试集采样数 [默认 100000]: ")" val
                    val="${val:-100000}"
                    if [[ "$val" =~ ^[0-9]+$ ]] && [ "$val" -gt 0 ]; then
                        KNN_TEST_SAMPLE="$val"
                        break
                    fi
                    echo "  请输入正整数"
                done
                ok "KNN 采样: 训练=${KNN_TRAIN_SAMPLE}, 测试=${KNN_TEST_SAMPLE}"
            else
                KNN_TRAIN_SAMPLE=0
                KNN_TEST_SAMPLE=0
                warn "全量 KNN — sklearn 的 KNeighborsClassifier 是 brute-force 方式"
                warn "将加载全部训练数据到内存，预测时逐个计算距离，需要充足的内存和时间"
                if ! ask_yesno "确认使用全量 KNN?" "n"; then
                    KNN_MODE="sample"
                    KNN_TRAIN_SAMPLE=200000
                    KNN_TEST_SAMPLE=100000
                    ok "已切换为采样模式: 训练=${KNN_TRAIN_SAMPLE}, 测试=${KNN_TEST_SAMPLE}"
                fi
            fi
        else
            # cuML always full
            KNN_MODE="full"
            KNN_TRAIN_SAMPLE=0
            KNN_TEST_SAMPLE=0
            ok "cuML 后端始终使用全量数据"
        fi
    fi

    # 6. 采样控制 (全局)
    echo ""
    header "全局采样控制"
    info "以下采样控制对除 KNN 外的所有模型生效"
    SAMPLE_TRAIN=0
    SAMPLE_VALID=0
    SAMPLE_TEST=0
    if ask_yesno "是否对非 KNN 模型启用全局采样?" "n"; then
        while true; do
            read -r -p "$(echo -e "${MAGENTA}[?]${RESET} 训练集采样数: ")" val
            if [[ "$val" =~ ^[0-9]+$ ]] && [ "$val" -gt 0 ]; then
                SAMPLE_TRAIN="$val"
                break
            fi
            echo "  请输入正整数"
        done
        while true; do
            read -r -p "$(echo -e "${MAGENTA}[?]${RESET} 验证集采样数: ")" val
            if [[ "$val" =~ ^[0-9]+$ ]] && [ "$val" -gt 0 ]; then
                SAMPLE_VALID="$val"
                break
            fi
            echo "  请输入正整数"
        done
        while true; do
            read -r -p "$(echo -e "${MAGENTA}[?]${RESET} 测试集采样数: ")" val
            if [[ "$val" =~ ^[0-9]+$ ]] && [ "$val" -gt 0 ]; then
                SAMPLE_TEST="$val"
                break
            fi
            echo "  请输入正整数"
        done
        ok "全局采样: 训练=${SAMPLE_TRAIN}, 验证=${SAMPLE_VALID}, 测试=${SAMPLE_TEST}"
    else
        ok "全局采样: 关闭 (使用全量数据)"
    fi

    # 7. 其他选项
    echo ""
    header "其他选项"

    TENSORBOARD=false
    if ask_yesno "启用 TensorBoard 日志?" "y"; then
        TENSORBOARD=true
    fi

    RENDER_FIGURES=false
    if ask_yesno "训练完毕后自动渲染图表?" "y"; then
        RENDER_FIGURES=true
    fi

    ISOLATE_TASKS=true
    if ask_yesno "隔离运行每个任务 (推荐，避免内存累积)?" "y"; then
        ISOLATE_TASKS=true
    else
        ISOLATE_TASKS=false
    fi

    FORCE=false
    RESUME=false
    echo ""
    if ask_yesno "强制重新运行 (覆盖已有结果)?" "n"; then
        FORCE=true
        ok "将强制覆盖已有结果"
    else
        RESUME=true
        ok "将跳过已完成的任务 (resume 模式)"
    fi
}

# ─────────────────── 显示配置摘要 ─────────────────────────
show_config_summary() {
    header "配置摘要"

    echo -e "  ${BOLD}特征组${RESET}        ${FEATURE_GROUPS[*]}"
    echo -e "  ${BOLD}模型${RESET}          ${MODELS[*]}"
    echo -e "  ${BOLD}Logistic 后端${RESET}  ${LOGISTIC_BACKEND}"
    echo -e "  ${BOLD}LightGBM 设备${RESET}  ${LIGHTGBM_DEVICE}"
    echo -e "  ${BOLD}KNN 后端${RESET}       ${KNN_BACKEND}"
    echo -e "  ${BOLD}KNN 模式${RESET}       ${KNN_MODE}"
    if [ "$KNN_MODE" = "sample" ]; then
        echo -e "  ${BOLD}KNN 采样${RESET}       训练=${KNN_TRAIN_SAMPLE}, 测试=${KNN_TEST_SAMPLE}"
    fi
    echo -e "  ${BOLD}全局采样${RESET}       ${SAMPLE_TRAIN}/${SAMPLE_VALID}/${SAMPLE_TEST} (train/valid/test)"
    echo -e "  ${BOLD}TensorBoard${RESET}    ${TENSORBOARD}"
    echo -e "  ${BOLD}渲染图表${RESET}      ${RENDER_FIGURES}"
    echo -e "  ${BOLD}任务隔离${RESET}      ${ISOLATE_TASKS}"
    echo -e "  ${BOLD}模式${RESET}          $([ "$FORCE" = true ] && echo 'force (覆盖)' || echo 'resume (跳过已完成)')"
    echo -e "  ${BOLD}Seed${RESET}          ${SEED}"
    echo -e "  ${BOLD}A/B/C 数据集目录${RESET} ${HCG_DATASET_DIR}"
    echo -e "  ${BOLD}D/E/F 数据集目录${RESET} ${TCG_DATASET_DIR}"
    echo -e "  ${BOLD}A/B/C 输出目录${RESET}   ${HCG_OUTPUT_DIR}"
    echo -e "  ${BOLD}D/E/F 输出目录${RESET}   ${TCG_OUTPUT_DIR}"
    echo ""
}

# ─────────────────── 构建命令并运行 ───────────────────────
run_training() {
    header "开始训练"

    local hcg_groups=()
    local tcg_groups=()
    for grp in "${FEATURE_GROUPS[@]}"; do
        case "$grp" in
            A|B|C) hcg_groups+=("$grp") ;;
            D|E|F) tcg_groups+=("$grp") ;;
        esac
    done

    echo -e "${CYAN}${BOLD}将执行:${RESET}"
    if [ ${#hcg_groups[@]} -gt 0 ]; then
        echo "  A/B/C: $(IFS=,; echo "${hcg_groups[*]}") -> ${HCG_OUTPUT_DIR}"
    fi
    if [ ${#tcg_groups[@]} -gt 0 ]; then
        echo "  D/E/F: $(IFS=,; echo "${tcg_groups[*]}") -> ${TCG_OUTPUT_DIR}"
    fi
    echo ""

    if ! ask_yesno "确认开始训练?" "y"; then
        info "已取消"
        return 0
    fi

    run_training_batch() {
        local label="$1"; shift
        local dataset_dir="$1"; shift
        local output_dir="$1"; shift
        local runs_dir="$1"; shift
        local groups=("$@")
        if [ ${#groups[@]} -eq 0 ]; then
            return 0
        fi

        local full_cmd=()
        full_cmd+=(env CUDA_VISIBLE_DEVICES=4,5,6,7 PYTHONPATH=src)
        full_cmd+=(python3 scripts/train_hcg_classifiers.py)
        full_cmd+=(--dataset-dir "$dataset_dir")
        full_cmd+=(--output-dir "$output_dir")
        full_cmd+=(--runs-dir "$runs_dir")
        full_cmd+=(--feature-groups "$(IFS=,; echo "${groups[*]}")")
        full_cmd+=(--models "$(IFS=,; echo "${MODELS[*]}")")
        full_cmd+=(--seed "$SEED")
        full_cmd+=(--sample-train "$SAMPLE_TRAIN")
        full_cmd+=(--sample-valid "$SAMPLE_VALID")
        full_cmd+=(--sample-test "$SAMPLE_TEST")
        full_cmd+=(--knn-train-sample "$KNN_TRAIN_SAMPLE")
        full_cmd+=(--knn-test-sample "$KNN_TEST_SAMPLE")
        full_cmd+=(--knn-backend "$KNN_BACKEND")
        full_cmd+=(--logistic-backend "$LOGISTIC_BACKEND")
        full_cmd+=(--lightgbm-device "$LIGHTGBM_DEVICE")

        if [ "$KNN_MODE" = "full" ] && [ "$KNN_BACKEND" = "sklearn" ]; then
            full_cmd+=(--allow-full-knn)
        fi
        if [ "$TENSORBOARD" = true ]; then
            full_cmd+=(--tensorboard)
        else
            full_cmd+=(--no-tensorboard)
        fi
        if [ "$RENDER_FIGURES" = true ]; then
            full_cmd+=(--render-figures)
        fi
        if [ "$ISOLATE_TASKS" = true ]; then
            full_cmd+=(--isolate-tasks)
        else
            full_cmd+=(--no-isolate-tasks)
        fi
        if [ "$FORCE" = true ]; then
            full_cmd+=(--force)
        fi
        full_cmd+=(--progress)

        echo -e "${CYAN}${BOLD}执行 ${label}:${RESET}"
        echo "  ${full_cmd[*]}"
        echo ""
        "${full_cmd[@]}"
    }


    echo ""
    info "训练开始: $(date '+%Y-%m-%d %H:%M:%S')"
    local start_ts=$SECONDS

    local rc=0
    run_training_batch "A/B/C" "$HCG_DATASET_DIR" "$HCG_OUTPUT_DIR" "$HCG_RUNS_DIR" "${hcg_groups[@]}" || rc=$?
    if [ $rc -eq 0 ]; then
        run_training_batch "D/E/F" "$TCG_DATASET_DIR" "$TCG_OUTPUT_DIR" "$TCG_RUNS_DIR" "${tcg_groups[@]}" || rc=$?
    fi

    local elapsed=$((SECONDS - start_ts))
    local elapsed_fmt
    elapsed_fmt="$(printf '%02d:%02d:%02d' $((elapsed/3600)) $(((elapsed%3600)/60)) $((elapsed%60)))"

    echo ""
    if [ $rc -eq 0 ]; then
        ok "训练完成! 耗时: ${elapsed_fmt}"
        info "A/B/C 结果目录: ${HCG_OUTPUT_DIR}"
        info "D/E/F 结果目录: ${TCG_OUTPUT_DIR}"
        if [ -f "${HCG_OUTPUT_DIR}/classifier_summary.md" ]; then
            echo ""
            info "A/B/C 快速结果预览:"
            head -20 "${HCG_OUTPUT_DIR}/classifier_summary.md"
        fi
        if [ -f "${TCG_OUTPUT_DIR}/classifier_summary.md" ]; then
            echo ""
            info "D/E/F 快速结果预览:"
            head -20 "${TCG_OUTPUT_DIR}/classifier_summary.md"
        fi
    else
        err "训练过程出错 (exit code: $rc)，耗时: ${elapsed_fmt}"
        info "检查各个任务目录下的 error_traceback.txt 获取详细错误信息"
    fi

    return $rc
}

# ─────────────────────── 主流程 ───────────────────────────
main() {
    echo -e "${BOLD}${CYAN}"
    echo "╔══════════════════════════════════════════════════╗"
    echo "║   图特征分类模型训练 — 交互式全量运行脚本       ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo -e "${RESET}"

    # Step 1: Environment check
    if ! check_environment; then
        err "环境检查失败，请修复后重试"
        exit 1
    fi

    # Step 2: Data integrity check (optional)
    if ask_yesno "是否在训练前运行数据完整性检查?" "y"; then
        if ! run_data_integrity_check; then
            err "数据完整性检查失败或用户取消"
            exit 1
        fi
    else
        info "跳过数据完整性检查"
    fi

    # Step 3: Interactive config
    if ! interactive_config; then
        err "配置过程出错"
        exit 1
    fi

    # Step 4: Show summary and confirm
    show_config_summary

    # Step 5: Run
    run_training
}

main "$@"
