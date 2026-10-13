#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

exec "${PYTHON:-python}" -m codes.workflow \
    "${PAPER_PATH:-examples/Transformer.json}" \
    --model "${MODEL_NAME:-o3-mini}" \
    --output-dir "${OUTPUT_DIR:-outputs/Transformer}" \
    --output-repo-dir "${OUTPUT_REPO_DIR:-outputs/Transformer_repo}" \
    "$@"
