#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务11：保持网页服务运行，将真实调用AI生成两首作品，需要网络，会使用已配置预算。'
backend/.venv/bin/python backend/scripts/check_pipeline.py
RESULT=$?
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
