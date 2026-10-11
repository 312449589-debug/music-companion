#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR/backend"
echo '任务15：原作品保留、失败重试及真实整段重新生成验证。'
.venv/bin/python scripts/check_regeneration_page.py
RESULT=$?
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
