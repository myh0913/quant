#!/usr/bin/env bash
# =============================================================================
# quant 服务器日常部署（非 Docker + systemd 版）
# 在服务器上执行：bash scripts/deploy-remote.sh
# 本机一键：     ssh server 'bash /home/ubuntu/apps/quant/scripts/deploy-remote.sh'
# 流程：git pull → 两套 Python 依赖(变化才装) → 前端构建(无变化跳过)
#       → 重启 backend + scheduler 调度器 → 健康检查
# 注：deploy/update.sh 是 Docker 版更新脚本，与本脚本（裸机 systemd）无关；
#     配置参数类改动调度器下一 tick 自动热生效，重启只为加载代码级改动
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="$HOME/.cache/deploy-state"; mkdir -p "$STATE_DIR"
QS="$ROOT/quant-system"          # 调度器 + 数据采集（pyproject）
QW="$ROOT/quant-web"             # web 前端(vite) + Flask 后端(requirements.txt)
BACKEND_PORT=8002
step() { echo; echo "==> $*"; }

step "1/6 git pull"
git -C "$ROOT" pull --ff-only
echo "部署提交: $(git -C "$ROOT" log --oneline -1)"

step "2/6 quant-system 依赖（调度器，pyproject 有变化才安装）"
DEP="$(git -C "$ROOT" rev-parse HEAD:quant-system/pyproject.toml)"
DEP_STATE="$STATE_DIR/quant-system-pydep.hash"
if [ "$DEP" = "$(cat "$DEP_STATE" 2>/dev/null)" ]; then
  echo "依赖无变化，跳过"
else
  "$QS/.venv/bin/pip" install -q -e "$QS"
  echo "$DEP" > "$DEP_STATE"
  echo "依赖已更新"
fi

step "3/6 quant-web 后端依赖（requirements.txt 有变化才安装）"
DEP="$(git -C "$ROOT" rev-parse HEAD:quant-web/backend/requirements.txt)"
DEP_STATE="$STATE_DIR/quant-web-pydep.hash"
if [ "$DEP" = "$(cat "$DEP_STATE" 2>/dev/null)" ]; then
  echo "依赖无变化，跳过"
else
  "$QW/backend/.venv/bin/pip" install -q -r "$QW/backend/requirements.txt"
  echo "$DEP" > "$DEP_STATE"
  echo "依赖已更新"
fi

step "4/6 quant-web 前端构建（lockfile 或 src 无变化自动跳过）"
TREE="$(git -C "$ROOT" rev-parse HEAD:quant-web/package-lock.json):$(git -C "$ROOT" rev-parse HEAD:quant-web/src)"
TREE_STATE="$STATE_DIR/quant-web-frontend.tree"
if [ "$TREE" = "$(cat "$TREE_STATE" 2>/dev/null)" ] && [ -f "$QW/dist/index.html" ]; then
  echo "前端无变化，跳过构建"
else
  cd "$QW"
  npm ci --no-audit --no-fund
  npm run build
  echo "$TREE" > "$TREE_STATE"
fi

step "5/6 重启服务（backend + scheduler 调度器）"
sudo systemctl restart quant-backend quant-scheduler

step "6/6 健康检查"
sleep 3
systemctl is-active --quiet quant-backend   || { echo "❌ quant-backend 未运行";   exit 1; }
systemctl is-active --quiet quant-scheduler || { echo "❌ quant-scheduler 未运行"; exit 1; }
curl -fsS "http://127.0.0.1:${BACKEND_PORT}/api/health" >/dev/null \
  || { echo "❌ /api/health 未就绪"; exit 1; }

echo
echo "✅ 部署完成：$(git -C "$ROOT" log --oneline -1)"
echo "   backend 运行中(/api/health 就绪) + scheduler 调度器运行中"
