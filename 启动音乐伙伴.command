#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLED_NODE_DIR="/Users/ming/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin"
fail() { echo "$1"; read -r -p '按回车关闭…' _; exit 1; }
if ! command -v node >/dev/null 2>&1; then export PATH="$BUNDLED_NODE_DIR:$PATH"; fi
command -v node >/dev/null 2>&1 || fail '缺少 Node.js，请按 README 安装。'
[ -x "$PROJECT_DIR/backend/.venv/bin/python" ] || fail '缺少 Python 环境，请按 README 安装。'
[ -d "$PROJECT_DIR/frontend/node_modules" ] || fail '缺少网页依赖，请按 README 安装。'
[ -f "$PROJECT_DIR/.env" ] || fail '缺少 .env，请按 README 填写本机模型配置。'
cd "$PROJECT_DIR"
echo '正在构建网页，不会调用 AI。'
if command -v npm >/dev/null 2>&1; then
  npm --prefix frontend run build || fail '网页构建失败，请检查上方提示。'
elif [ -f .tools/npm/bin/npm-cli.js ]; then
  node .tools/npm/bin/npm-cli.js --prefix frontend run build --cache .tools/npm-cache || fail '网页构建失败，请检查上方提示。'
else
  fail '缺少 npm，请按 README 安装。'
fi
# Do not silently reuse an older server or terminate someone else’s process.
backend/.venv/bin/python - <<'PYPORT' || fail '8000端口已被占用，请关闭原来的音乐伙伴服务窗口后重新启动。'
import socket
with socket.socket() as probe:
    try: probe.bind(('127.0.0.1', 8000))
    except OSError: raise SystemExit(1)
PYPORT
BACKEND_PID=''
cleanup() {
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM
# The production launcher always uses its own standard root and print address.
export MUSIC_JOBS_ROOT="$PROJECT_DIR/runtime/jobs"
export MUSIC_PRINT_BASE_URL='http://127.0.0.1:8000'
cd "$PROJECT_DIR/backend"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log &
BACKEND_PID=$!
BACKEND_READY=false
for attempt in {1..50}; do
  kill -0 "$BACKEND_PID" 2>/dev/null || fail '服务启动失败，请检查上方提示。'
  HEALTH="$(curl --silent --max-time 1 http://127.0.0.1:8000/api/health || true)"
  if [[ "$HEALTH" == *'"service":"music-companion-api"'* ]]; then BACKEND_READY=true; break; fi
  sleep 0.2
done
[ "$BACKEND_READY" = true ] || fail '服务未能就绪，请检查配置。'
echo '音乐伙伴已启动：http://127.0.0.1:8000/'
echo '请保留本窗口；按 Control+C 停止。生成中的任务会等待结束后退出。'
open http://127.0.0.1:8000/
wait "$BACKEND_PID"
