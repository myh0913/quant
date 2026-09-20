#!/bin/bash
# 启动选股通看板后端
#
# 用法：
#   export XUANGUTONG_IVANKA_TOKEN='<token>'
#   export QUANT_ADVICE_DIR='../quant-system/data/advice'   # 可选：实时推送量化系统建议
#   ./run.sh
#
# 或在 backend/.env 写入以上变量后再启动
# 端口默认 8000（与前端 Vite proxy /api 匹配）

set -e
cd "$(dirname "$0")"

if [ -z "$XUANGUTONG_IVANKA_TOKEN" ]; then
  if [ -f .env ]; then
    set -a
    . ./.env
    set +a
  fi
fi

if [ -z "$XUANGUTONG_IVANKA_TOKEN" ]; then
  echo "❌ XUANGUTONG_IVANKA_TOKEN 未设置"
  echo "   export XUANGUTONG_IVANKA_TOKEN='<token>' 后再启动"
  exit 1
fi

# 依赖检查
python3 -c "import flask, flask_cors, flask_sock, simple_websocket, requests" 2>/dev/null || {
  echo "📦 安装依赖..."
  python3 -m pip install --break-system-packages -q -r requirements.txt
}

echo "🚀 启动后端（端口 ${PORT:-8000}）..."
echo "   advice 目录: ${QUANT_ADVICE_DIR:-未设置（WS 不推送建议）}"
exec python3 main.py
