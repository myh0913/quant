#!/bin/bash
# 一键启动量化全套：后端(:8000) + 前端(:5273) + 调度器
# 用法：./start-all.sh     （可重复执行；已在跑的不会重复拉起）
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
QS="$ROOT/quant-system"
QW="$ROOT/quant-web"
mkdir -p "$ROOT/logs"

# ---- token 从 quant-system/.env 读取（不复制密钥到别处） ----
TOKEN=$(grep '^XUANGUTONG_IVANKA_TOKEN=' "$QS/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r')
if [ -z "$TOKEN" ]; then
  echo "❌ quant-system/.env 缺 XUANGUTONG_IVANKA_TOKEN"; exit 1
fi

# ---- 0. 前端生产构建（外部访问走 :8000 托管的 dist；src 有更新才重建） ----
if [ ! -f "$QW/dist/index.html" ] || \
   [ -n "$(find "$QW/src" \( -name '*.ts' -o -name '*.tsx' -o -name '*.css' \) -newer "$QW/dist/index.html" 2>/dev/null | head -n 1)" ] || \
   [ "$QW/index.html" -nt "$QW/dist/index.html" ] || \
   [ "$QW/vite.config.ts" -nt "$QW/dist/index.html" ]; then
  echo "🔨 前端代码有更新，重建 dist …"
  (cd "$QW" && npm run build > "$ROOT/logs/build.log" 2>&1) \
    && echo "✅ dist 已更新（外部访问即时生效）" \
    || echo "⚠️ 构建失败，外部访问仍用旧 dist（详见 logs/build.log）"
fi

# ---- 1. 后端（Flask :8000） ----
# -sTCP:LISTEN 只匹配监听进程；否则浏览器到 8000 的连接残留会被误判为"已在运行"
if lsof -ti :8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⏭ 后端已在运行（:8000）"
else
  cd "$QW/backend"
  XUANGUTONG_IVANKA_TOKEN="$TOKEN" QUANT_ADVICE_DIR="$QS/data/advice" \
    QUANT_WEB_DIST="$QW/dist" \
    nohup python3 main.py > "$ROOT/logs/backend.log" 2>&1 &
  echo "🚀 后端 pid=$! → logs/backend.log"
fi

# ---- 2. 前端（Vite :5273） ----
if lsof -ti :5273 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⏭ 前端已在运行（:5273）"
else
  cd "$QW"
  nohup npm run dev -- --host 0.0.0.0 --port 5273 > "$ROOT/logs/frontend.log" 2>&1 &
  echo "🚀 前端 pid=$! → logs/frontend.log"
fi

# ---- 3. 调度器（quant-system，纯 Python） ----
if pgrep -f "quant_system.scheduler" >/dev/null 2>&1; then
  echo "⏭ 调度器已在运行"
else
  cd "$QS"
  nohup ./.venv/bin/python -m quant_system.scheduler > "$ROOT/logs/scheduler.log" 2>&1 &
  echo "🚀 调度器 pid=$! → logs/scheduler.log（9:25 竞价 / 9:26-10:00 盘中 / 15:05 盘后）"
fi

sleep 2
echo ""
echo "✅ 前端     http://localhost:5273"
echo "   后端健康 http://localhost:8000/health"
echo "   今日建议 http://localhost:8000/api/advice"
echo "   外部访问 https://goldmac-mini.tail81369e.ts.net（Funnel → :8000 生产构建）"
echo "   日志目录 $ROOT/logs/"
