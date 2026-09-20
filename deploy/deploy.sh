#!/bin/bash
# 一键部署：前置检查 → 构建镜像 → 启动 → 健康检查。
# 首次部署前：先建好 quant-system/.env（参考 .env.example），再跑本脚本。
set -e
cd "$(dirname "$0")"

# ---- 1. 前置检查 ----
command -v docker >/dev/null 2>&1 || { echo "❌ 未安装 Docker（apt install docker.io 或装 Docker Desktop）"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "❌ 未安装 Docker Compose v2（apt install docker-compose-plugin）"; exit 1; }
[ -f ../quant-system/.env ] || { echo "❌ 缺少 quant-system/.env：cp quant-system/.env.example quant-system/.env 并填入密钥"; exit 1; }
grep -q '^XUANGUTONG_IVANKA_TOKEN=..' ../quant-system/.env || echo "⚠️ XUANGUTONG_IVANKA_TOKEN 未填写，行情接口将不可用"

# ---- 2. 构建并启动 ----
echo "🔨 构建镜像（首次约需几分钟）…"
docker compose build
docker compose up -d

# ---- 3. 健康检查 ----
echo "⏳ 等待 web 就绪…"
ok=0
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != 1 ]; then
  echo "❌ 健康检查超时，排查：docker logs quant-web"
  exit 1
fi

docker compose ps
echo ""
echo "✅ 部署成功"
echo "   本地访问  http://127.0.0.1:8000"
echo "   外部访问  宿主机 Tailscale Funnel → localhost:8000（沿用现有 Funnel 配置，无需改动）"
echo "   调度日志  docker logs -f quant-scheduler"
echo "   Web 日志  docker logs -f quant-web"
echo "   更新部署  ./update.sh    数据备份  ./backup.sh"
