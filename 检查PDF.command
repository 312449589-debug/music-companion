#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务10：请保持本机网页服务运行，将导出短谱与跨页PDF，不调用AI。'
backend/.venv/bin/python backend/scripts/check_pdf.py
RESULT=$?
if [ "$RESULT" -eq 0 ]; then
  backend/.venv/bin/python backend/scripts/check_pdf.py --failed-render
  RESULT=$?
fi
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
