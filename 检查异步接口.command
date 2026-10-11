#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务12：自动启动独立本机诊断服务，通过接口生成两首真实作品，需要网络和已配置预算。'
echo '本测试会自行停止它启动的诊断服务，无需操作主服务。'
backend/.venv/bin/python backend/scripts/check_jobs_api.py --start-local-server
RESULT=$?
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
