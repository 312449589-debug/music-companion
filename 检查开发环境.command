#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
backend/.venv/bin/python backend/scripts/check_environment.py --sound-check --play
RESULT=$?
echo
if [ "$RESULT" -eq 0 ]; then
  echo '工具与音色检查通过；AI 配置在接入模型时继续确认。'
else
  echo '部分检查未通过，请把本窗口的检查结果提供给 Codex。'
fi
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
