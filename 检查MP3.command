#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务09：从固定样例生成真正MP3，不请求AI。'
backend/.venv/bin/python backend/scripts/check_audio.py
RESULT=$?
if [ "$RESULT" -eq 0 ]; then
  echo '播放刚生成的吉他样例…'
  afplay runtime/diagnostics/composition-check.mp3 || RESULT=$?
fi
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
