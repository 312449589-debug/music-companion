#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务06：只检查诊断样例指型，不请求AI、不生成音频。'
backend/.venv/bin/python backend/scripts/check_fingering.py
RESULT=$?
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
