#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务03：固定诊断样例，不会调用模型或生成音乐。'
backend/.venv/bin/python backend/scripts/check_composition.py
RESULT=$?
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
