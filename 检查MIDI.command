#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务08：从固定样例导出MIDI并核对事件，不调用AI，不生成MP3。'
backend/.venv/bin/python backend/scripts/check_midi.py
RESULT=$?
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
