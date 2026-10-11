#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务05：检查固定样例，不调用AI；不修改任何音乐文件。'
backend/.venv/bin/python backend/scripts/check_music.py
RESULT=$?
if [ "$RESULT" -eq 0 ]; then
  backend/.venv/bin/python backend/scripts/check_music.py --case four-seconds
  RESULT=$?
fi
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
