#!/usr/bin/env bash
# 本地起前后端，演示模式接真实大模型（OpenAI 兼容接口）。密钥只放环境变量，不写进文件。
#   export LLM_API_KEY=...  LLM_BASE_URL=https://router.example/api/v1  BUTLER_LLM_MODEL=gpt-5.4-mini
#   scripts/dev-live.sh
# 不设这三个变量就退回离线规则演示（攻防演示台右上角会标出“离线规则”）。
set -euo pipefail
cd "$(dirname "$0")/.."
: "${LLM_API_KEY:?请先 export LLM_API_KEY}" "${LLM_BASE_URL:?请先 export LLM_BASE_URL（https）}" "${BUTLER_LLM_MODEL:?请先 export BUTLER_LLM_MODEL}"
trap 'kill 0' EXIT
(cd services/api && python -m uvicorn butler.main:app --port 8000) &
(cd apps/web && npm run dev) &
wait
