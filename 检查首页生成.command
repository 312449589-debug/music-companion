#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR/backend"
export PYTHONPATH="$PROJECT_DIR/backend"
echo '任务14：首页失败及真实生成验证。请保持此窗口打开。'
.venv/bin/python scripts/check_creation_page.py
RESULT=$?
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
