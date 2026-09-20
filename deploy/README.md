# 服务器部署方案（Docker Compose）

## 架构

```
                      Tailscale Funnel（HTTPS，边缘节点终结）
                              │
                     宿主机 localhost:8000
                              │  ports: 127.0.0.1:8000:8000
┌─────────────────────────────┴──────────────────────────────┐
│  ┌────────────────────┐        ┌────────────────────────┐  │
│  │ quant-scheduler    │        │ quant-web              │  │
│  │ 调度器（无对外端口）│        │ Flask :8000            │  │
│  │ 竞价/盘中/盘后/复盘 │        │ + 前端 dist 托管        │  │
│  │                    │        │ + 沙箱/回放子进程       │  │
│  └────────┬───────────┘        └───────────┬────────────┘  │
│           └─────── 共享挂载 quant-system/data ───┘          │
│         （advice / config / std 快照 / replay / web DB）    │
└─────────────────────────────────────────────────────────────┘
```

两容器挂**同一宿主目录** `quant-system/data`，与本地裸跑行为一致：

- scheduler 把建议落盘 `data/advice/` → web 的 WS 监听目录实时推送
- 配置页保存写 `data/config/active.json` → 调度器下一 tick 热生效（无需重启）
- 回放测试读 `data/std/` 快照、结果落 `data/replay/`
- backend SQLite（用户/角色）与 `.secret_key` 在 `data/web/`

## 前置条件（服务器）

```bash
# 1. Docker + Compose v2
sudo apt update && sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER   # 重新登录生效

# 2. Tailscale（内网机器走 Funnel 暴露，沿用现有配置）
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale funnel 443 on     # 已配置过则跳过；Funnel 转发目标 localhost:8000

# 3. 代码 + 密钥
git clone <仓库地址> && cd project
cp quant-system/.env.example quant-system/.env
vim quant-system/.env            # 填 HITHINK_FINANCE_API_KEY / XUANGUTONG_IVANKA_TOKEN
```

## 一键部署

```bash
cd deploy && ./deploy.sh
```

脚本依次做：前置检查 → 构建双镜像 → 启动 → `http://127.0.0.1:8000/api/health` 健康检查。

## 日常运维

| 操作 | 命令 |
|---|---|
| 更新（拉代码+重建+重启） | `./update.sh` |
| 备份数据（默认排除 raw） | `./backup.sh`（全量 `--all`） |
| 调度器日志 | `docker logs -f quant-scheduler` |
| Web 日志 | `docker logs -f quant-web` |
| 状态 | `docker compose ps` |
| 停止 / 启动 | `docker compose down` / `docker compose up -d` |

## 从本地迁移历史数据

数据全部在 `quant-system/data/`，直接 rsync 即可（含账号 DB、参数版本、历史建议/复盘）：

```bash
rsync -av --exclude raw/ quant-system/data/ user@server:<项目根>/quant-system/data/
```

## 关键设计说明

- **quant-system 不 pip install 进 site-packages**：`config.py` 的 `PROJECT_ROOT` 按 `__file__` 定位数据目录，装进 site-packages 会让 data 目录漂移；两镜像都用 `PYTHONPATH=/app/quant-system/src` 挂源码运行。
- **web 镜像内嵌 quant-system 源码**：量化配置页的「沙箱测试 / 快照回放」由 backend 以子进程调 `quant_system.sandbox / replay`，同一解释器必须能 import。
- **端口只绑 127.0.0.1**：容器不直接暴露公网，HTTPS 由宿主机 Funnel 终结后转发，与现有部署的访问链路完全一致。
- **密钥不进镜像**：`.dockerignore` 排除 `.env`，密钥经 compose `env_file` 注入进程环境。
- **时区**：镜像装 tzdata 且 `TZ=Asia/Shanghai`，调度时间与本地一致。

## 常见问题

- **健康检查超时**：`docker logs quant-web`；多半是 `.env` 缺 token 或端口被占用（`ss -ltnp | grep 8000`）。
- **改了策略参数要重启吗**：不用，保存即版本化热生效。
- **换了机器 Funnel 变了**：`tailscale funnel 443 on` 重新指向，容器侧无需任何改动。
