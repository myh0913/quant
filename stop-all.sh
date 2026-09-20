#!/bin/bash
# 一键停止全套：调度器 + 前端(:5273) + 后端(:8000)
# -sTCP:LISTEN 只杀监听进程；否则会误杀浏览器到这些端口的连接持有者（如 Chrome）
echo "停止调度器…"; pkill -f "quant_system.scheduler" 2>/dev/null
echo "停止前端…";   lsof -ti :5273 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null
echo "停止后端…";   lsof -ti :8000 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null
sleep 1
if lsof -i :5273 -i :8000 -P -n -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; then
  echo "⚠️ 仍有端口占用，请手动检查：lsof -i :5273 -i :8000 -sTCP:LISTEN"
  exit 1
else
  echo "✅ 全部已停"
fi
