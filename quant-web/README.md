# 选股通看板 (Quant Web)

基于**选股通 (xuangutong.com.cn)** 数据的实时 A 股量化选股面板。前端 + 后端 + 量化系统实时对接。

## 跑起来（开发）

```bash
# 1. 后端（终端 1）：REST + WS + advice 目录监听
cd backend
export XUANGUTONG_IVANKA_TOKEN='<token>'                    # 选股通新闻 token
export QUANT_ADVICE_DIR='../quant-system/data/advice'       # 量化系统落盘目录
./run.sh

# 2. 前端（终端 2）：Vite dev，/api 与 /ws 自动代理到 8000
npm run dev
```

打开 http://localhost:5273 即为实时模式。

## 鉴权与角色

三角色体系，后端（REST 守卫 + WS 频道过滤）与前端（路由/导航）双重控制：

| 页面 | 普通用户 user | 高级用户 advanced | 超管 admin |
|---|---|---|---|
| 总览 / 涨停池 / 快讯 / 主题 / 监管名单 | ✅（总览隐藏最新建议卡） | ✅ | ✅ |
| 今日建议 | ⚠️ 仅历史（看不到当日/实时） | ✅ 实时 | ✅ 实时 |
| 设置 · 用户管理 | ❌ | ❌ | ✅ |

- **登录/注册**：`/login`、`/register`；注册的新账号一律普通用户；会话 cookie 30 天有效
- **引导超管**：`users.json` 为空时自动创建，密码取 `ADMIN_PASSWORD` 环境变量（未设则生成随机密码打印到后端日志）
- **防爆破**：登录连续失败 5 次锁 IP 5 分钟
- **用户管理**（设置页）：改角色 / 启停 / 重置密码 / 删除；保护规则：不能对自己降级/停用/删除，不能动最后一个启用的超管
- **强制服务端校验**：普通用户的实时建议在 REST（当日 403）和 WS（advice 频道不推送、订阅被忽略）两层都拿不到
- 存储：`backend/users.json`（PBKDF2 哈希）+ `backend/.secret_key`（会话签名，`SECRET_KEY` 环境变量可覆盖）

### 公网访问

后端 `0.0.0.0:8000` 已可公网直连，但生产必须套 HTTPS（会话 cookie 明文传输会被劫持）。最简方案是 Caddy 反代（单二进制，自动签发续期证书）：

```bash
# Caddyfile
quant.example.com {
    reverse_proxy localhost:8000
}
```

## 数据通道（纯 WS 长连接）

```
浏览器 ──WS /ws──► Flask 后端 ──监听落盘目录──► quant-system 调度器产出
   ▲                    │
   └── REST 初始补数据 ──┘（连接建立时自动拉一轮，断线重连同样如此）
```

- **实时推送**：量化系统建议（落盘即推）+ 行情快照定时广播（情绪/池子/快讯/主题/监管名单，约 30s）
- **初始补数据**：连接建立后 REST 全量拉一轮，断线重连自动补，不丢数据
- **保活**：客户端 30s ping / 服务端 25s heartbeat；60s 无消息主动重连
- 切换连接地址在设置页，业务代码零感知

## 7 个中文页面

| 路径 | 名称 | 数据源 |
|---|---|---|
| `/` | 总览 | 情绪周期状态卡 / 情绪 / 最新建议摘要 / 涨停池摘要 / 快讯 |
| `/advice` | 今日建议 | 量化系统全部报告（竞价/盘中/盘后，实时推送 + 闪光提示 + 盘中触发时间线） |
| `/pools` | 涨停池 | 7 池切换（涨停/炸板/昨涨停/强势/跌停/新股/次新）+ 连板筛选 + 详情展开（封板时间线） |
| `/newsflash` | 7×24 快讯 | 分类过滤 + 关键词搜索 |
| `/themes` | 主题机会 | 左侧排名 / 右侧详情（含题材内个股 + 连续上榜天数徽标） |
| `/monitor` | 监管名单 | 东财重点监控证券 + 严重异常波动（后端直接拉取，5 分钟缓存） |
| `/settings` | 设置 | 连接地址 / 状态 / 协议文档 |

## REST 接口（连接建立时的初始数据加载）

```
GET /api/sentiment
GET /api/sentiment/history?days=10
GET /api/pool/:name                       # 7 个池子名见下
GET /api/pool/:name?date=YYYY-MM-DD       # 支持历史回测
GET /api/newsflash?limit=50
GET /api/themes
GET /api/monitor                          # 东财监管名单（重点监控 + 严重异动）
GET /api/advice?date=YYYY-MM-DD           # 量化系统当日全部报告（ran_at 升序）
GET /api/advice/latest
```

**池子名**（`pool_name`）：`limit_up` / `limit_up_broken` / `yesterday_limit_up` / `super_stock` / `limit_down` / `new_stock` / `nearly_new`

字段定义见 `src/types/index.ts`（与选股通 flash-api 完全对齐）。

## WebSocket 推送协议

```jsonc
// 后端 → 前端
{ "type": "sentiment",        "data": Sentiment }
{ "type": "sentiment_history","data": DailySnapshot[] }
{ "type": "pool",             "pool_name": "limit_up", "data": PoolResponse }
{ "type": "newsflash",        "data": NewsflashItem[] }
{ "type": "theme",            "data": Theme[] }
{ "type": "monitor",          "data": MonitorData }    // 东财监管名单定时广播
{ "type": "advice",           "data": DailyReport }    // 量化系统报告实时推送（5 种）
{ "type": "heartbeat",        "ts": <unix_ms> }        // 服务端 25s 一跳

// 前端 → 后端
{ "type": "subscribe",   "channels": ["sentiment","pool","newsflash","themes","monitor","advice"] }
{ "type": "ping" }                                        // 客户端 30s 一跳；60s 无消息主动重连
```

保活机制：客户端每 30s 发 `ping`（服务端回 `heartbeat`），超过 60s 未收到任何消息视为半开连接主动断开重连；重连成功后自动重新 `subscribe` 并 REST 补数据。

`advice` 推送覆盖调度器全部产出（按文件名前缀判别）：

| 文件前缀 | 类型 | 触发时机 |
|---|---|---|
| `auction_grab_*` | 竞价抢筹报告 | 交易日 09:25-09:40 |
| `intraday_*` | 盘中即时建议 / 触发事件 | 09:26-10:00 轮询，触发即推 |
| `lianban_pool_*` / `dragon_pool_*` | 盘后建池（明日候选） | 17:00-18:00 |
| `cycle_*` | 情绪周期判定 | 17:00-18:00 |

## 对接量化系统（实时推送）

数据流（**零侵入 quant-system**，调度器保持纯 Python + 落盘）：

```
quant-system scheduler（常驻，交易日时间轴）
    │ 09:25 竞价 / 09:26-10:00 盘中轮询 / 17:00 盘后
    ▼
persist_report → data/advice/YYYY-MM-DD/<name>_<HHMMSS>.json
    │ backend watch（mtime 轮询 2s）
    ▼
Flask backend：新文件 → WS 广播 {type:"advice"} + REST 可查
    │
    ▼
浏览器：今日建议页闪光提示 + 新报告置顶，总览摘要卡实时更新
```

启动 quant-system 调度器：

```bash
cd quant-system
./.venv/bin/python -m quant_system.scheduler            # 常驻（交易日自动调度）
./.venv/bin/python -m quant_system.scheduler --once auction     # 手动单跑竞价
./.venv/bin/python -m quant_system.scheduler --once postmarket  # 手动单跑盘后
```

备用手机推送：`.env` 设置 `NTFY_TOPIC=<主题>` 后，触发事件自动推 ntfy.sh（见 `notify.py`）。

## 部署（量化 + 前端一体交付）

前端 build 产物由后端静态托管，同源部署（无 CORS，WS 走同域），不用 Docker：

```bash
# 1. 量化系统（Python ≥3.11）
cd quant-system
python3 -m venv .venv
./.venv/bin/pip install -e . eltdx

# 2. 前端构建（Node ≥18），产物 dist/ 由后端托管
cd ../quant-web
npm install && npm run build

# 3. 一键启动（自动读 quant-system/.env 的 token）
cd .. && ./start-all.sh        # 后端 :8000 + 前端 dev :5273 + 调度器
./stop-all.sh                  # 一键停止
```

打开 `http://localhost:8000` 即为实时连接（生产同源模式）；`http://localhost:5273` 为 Vite dev 模式。

### 迁移到另一台电脑

```bash
# 旧机器：打包传输（排除可再生物；data/advice 很小，随包带走保留历史）
rsync -a --exclude '.venv' --exclude node_modules --exclude 'quant-web/dist' \
      --exclude 'quant-system/data/raw' --exclude logs --exclude '.DS_Store' \
      project/ 新机器:~/project/

# 密钥单独传，不走 git
scp quant-system/.env 新机器:~/project/quant-system/.env

# 新机器：按上面「部署」三步装依赖后 ./start-all.sh
```

注意：`data/raw/`（上游原始响应缓存）可不迁移，新机器首次运行自动重建。

## 项目结构

```
quant-web/
├── src/
│   ├── App.tsx                  # 路由 + 长连接初始化
│   ├── main.tsx, index.css
│   ├── types/index.ts           # 业务类型 + WS 协议 + 调度器报告类型
│   ├── lib/
│   │   ├── ws.ts                # WebSocket 客户端（重连 + 心跳保活）
│   │   ├── api.ts               # HTTP fetch 封装（仅初始补数据用）
│   │   ├── dataSource.ts        # 数据源层：WS 实时 + REST 补数据
│   │   └── format.ts            # 数字/时间格式化
│   ├── store/index.ts           # Zustand 全局状态（含报告去重合并）
│   ├── components/
│   │   ├── AppLayout.tsx        # 中文侧边栏
│   │   ├── ConnectionStatus.tsx
│   │   ├── SentimentGauge.tsx   # 情绪温度计
│   │   ├── StatRow.tsx          # 关键指标行
│   │   ├── PoolTabs.tsx         # 7 池切换
│   │   ├── PoolTable.tsx        # 涨停池表格（含展开）
│   │   ├── PoolTimeline.tsx     # 封板时间线可视化
│   │   ├── NewsflashItem.tsx    # 快讯条
│   │   ├── ThemeCard.tsx        # 主题卡片（含连续上榜徽标）
│   │   ├── ThemeDetail.tsx      # 主题详情
│   │   ├── CycleStatusCard.tsx  # 情绪周期状态卡（总览顶部）
│   │   ├── IntradayTimeline.tsx # 盘中触发时间线（今日建议页）
│   │   └── EmptyState.tsx
│   └── pages/                   # 7 个中文页面
│       ├── 总览.tsx
│       ├── 今日建议.tsx          # 调度器 5 种报告渲染
│       ├── 涨停池.tsx
│       ├── 快讯.tsx
│       ├── 主题.tsx
│       ├── 监管名单.tsx
│       └── 设置.tsx
├── backend/
│   ├── main.py                  # Flask：REST + /ws + advice 目录监听 + 快照广播 + 静态托管
│   ├── requirements.txt
│   └── run.sh
└── vite.config.ts               # 含 /api + /ws proxy（dev 用）
```

## 设计原则

- **字段对齐**：TypeScript 类型与选股通 flash-api 及 quant-system 落盘 JSON 完全一致
- **长连接优先**：WS 实时推送为主，REST 只做初始补数据；断线重连自动重订阅 + 补数据
- **零侵入对接**：量化系统保持纯 Python 落盘，后端监听目录即完成对接
- **闪光提示**：新数据进入触发 1.2s 高亮动画，不打扰但有反馈
- **A股配色**：红涨绿跌，深色主题夜间友好
- **可展开详情**：涨停池行可展开看封板时间线 + 关键指标

> 建议数据目录 `quant-system/data/advice/` 由 quant-system 落盘、后端监听，两个项目通过它解耦。