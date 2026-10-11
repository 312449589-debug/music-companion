#!/bin/bash
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
echo '任务04：验证预算、无效密钥和两次真实千问音乐候选。'
echo '真实调用会产生少量费用；仅受本项目200元总预算约束。'
RESULT=0
for mode in --budget-check --invalid-key-check live; do
  if [ "$mode" = live ]; then
    backend/.venv/bin/python backend/scripts/check_qwen.py || RESULT=$?
  else
    backend/.venv/bin/python backend/scripts/check_qwen.py "$mode" || RESULT=$?
  fi
  if [ "$RESULT" -ne 0 ]; then break; fi
done
if [ "$RESULT" -eq 0 ]; then
  echo '任务04调用与结构检查通过；听感和可演奏性仍需后续任务验证。'
else
  echo '任务04验证未通过，请查看错误代码；不会用模板冒充AI结果。'
fi
read -r -p '按回车关闭窗口…' _
exit "$RESULT"
