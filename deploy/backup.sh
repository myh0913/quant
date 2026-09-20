#!/bin/bash
# 备份共享数据目录（策略配置/建议报告/复盘/数据库/状态）。
# 用法：./backup.sh [--all]   --all 连 raw 原始行情缓存一起备（体积大，慎用）
set -e
cd "$(dirname "$0")"

TS=$(date +%Y%m%d-%H%M%S)
OUT="../backups/data-$TS.tar.gz"
EXTRA=(--exclude "quant-system/data/raw")
[ "${1:-}" = "--all" ] && EXTRA=()

mkdir -p ../backups
tar czf "$OUT" -C .. "${EXTRA[@]}" quant-system/data
echo "✅ 备份完成: $OUT（$(du -h "$OUT" | cut -f1)）"
echo "   恢复：tar xzf $OUT -C <项目根>"
