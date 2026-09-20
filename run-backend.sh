#!/bin/bash
# quant-web/backend 启动包装：source quant-system/.env 注 token，再 exec
set -e
ROOT=/home/ubuntu/apps/quant
QS=$ROOT/quant-system
QW=$ROOT/quant-web

# 从 quant-system/.env 读取（同一份密钥唯一事实来源）
set +e
TOKEN=$(grep '^XUANGUTONG_IVANKA_TOKEN=' "$QS/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r')
set -e

export XUANGUTONG_IVANKA_TOKEN="$TOKEN"
export QUANT_SYSTEM_DIR="$QS"
export QUANT_ADVICE_DIR="$QS/data/advice"
export QUANT_WEB_DIST="$QW/dist"
export QUANT_CONFIG_DIR="$QS/data/config"
# backend/main.py 只认 PORT（不是 QUANT_WEB_PORT）
export PORT=8002
export HOST=127.0.0.1
export ENABLE_CORS=1
export DISABLE_CAPTCHA=1

exec "$QW/backend/.venv/bin/python" "$QW/backend/main.py"