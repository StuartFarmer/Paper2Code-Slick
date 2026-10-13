#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

exec "${PYTHON:-python}" -m codes.workflow \
    "${PAPER_PATH:-examples/Transformer_cleaned.tex}" \
    --model "${MODEL_NAME:-deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct}" \
    --api-base "${API_BASE:-http://localhost:8000/v1}" \
    --output-dir "${OUTPUT_DIR:-outputs/Transformer_dscoder}" \
    --output-repo-dir "${OUTPUT_REPO_DIR:-outputs/Transformer_dscoder_repo}" \
    "$@"
