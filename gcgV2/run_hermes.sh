#!/usr/bin/env bash
set -euo pipefail

# GCG V2 — Hermes Player Simulator Runner
# Usage: bash run_hermes.sh [--seed 42] [--interpreter reference|llm]

cd "$(dirname "$0")"

# 1. gcg-player profile 已有 API key（設在 config.yaml）
# 2. 確保 gcg-player 在 PATH
export PATH="$HOME/.local/bin:$PATH"

# 3. 執行（--interpreter reference 不須 DeepSeek，只用於 effect 測試）
python3 run_simulator.py --players hermes --interpreter reference "$@"
