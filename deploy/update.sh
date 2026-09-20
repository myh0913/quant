#!/bin/bash
# 更新部署：拉代码 → 重建镜像 → 滚动重启。
# 数据全在宿主机 quant-system/data/（共享卷），重建容器不影响任何数据。
set -e
cd "$(dirname "$0")"

if git -C .. rev-parse --git-dir >/dev/null 2>&1; then
  echo "📥 拉取最新代码…"
  git -C .. pull --ff-only
fi

echo "🔨 重建镜像…"
docker compose build

echo "🔄 重启容器…"
docker compose up -d

docker compose ps
echo "✅ 更新完成（配置参数类改动无需重启，调度器下一 tick 自动热生效）"
