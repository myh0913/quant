# 项目进度

更新时间：2026-09-15 22:40

## 当前阶段
Phase 1 完成 + 实盘运行中 + **架构重构 M1→M7 全部完成**（策略注册表 / 能力契约 / 快照回放 / 复盘打分 / 前端复盘 / Docker 部署）

## 架构重构（2026-09-15，用户痛点：换策略、换源麻烦，调参验证慢）

### M1 策略统一接口 + 注册表
- 新建 `strategy/` 包：`Strategy` ABC（params_schema/run_auction_pipeline/build_pool/classify_scenes/confirm_intraday）+ `@register` 装饰器；三策略（auction_grab / lianban / dragon）全量迁移注册。
- `config_registry.py` schema 收集委托注册表（导出格式与旧版完全一致，backend/前端零改动兼容）；`scheduler.py` 全部注册表驱动，无硬编码策略名（测试断言）。
- 场景分派常量 SCENE_IMMEDIATE/PENDING/SKIP 替代硬编码字母；`timeutil.py` 时区工具下沉；删除旧 strategies.py / strategy_*.py / pipeline.py。

### M2 取数收敛 resolve（能力契约层）
- `datasource/registry.py` CAPABILITY_PROVIDERS 扩到 12 项能力（涨停池/跌停池/分钟线/竞价撮合/竞价序列/昨收/日K/指数快照/交易日历/情绪/监管名单…），多源能力支持主备切换（datasource_prefs.json 热生效）。
- `datasource/resolve.py`：`standard_*` 12 个契约函数 + `_fetch` 主备切换 + `data_session` 连接复用（contextvars）；业务代码消灭 20+ 处直接实例化数据源类。
- 静态架构测试：正则扫描 datasource/ 包外禁止 import 具体源类，新增数据源只改注册表。

### M3 快照层 + 回放
- `snapshot.py`：live 取数自动落盘 `data/std/<date>/<capability>-<args哈希>.json`；`replay_scope` 内只读快照，缺失抛 SnapshotMissing 绝不现场拉数（防未来数据）。
- `replay.py` CLI：对历史快照重跑策略（参数经 temporary_overrides 进程内注入），分钟级验证参数改动；结果落 `data/replay/` + stdout 单行 JSON（backend 子进程契约）。
- 确定性测试：同快照同参数结果一致；换参数结果改变；dragon 建池循环显式上浮 SnapshotMissing（防静默 0 候选假成功）。

### M4 复盘打分
- `review.py`：盘后核算 T-1 建议的次日表现（入场价=参考价/触发价/开盘价近似，主指标 next_close_pct，竞价涨停标记 unfillable 不计胜负）；聚合 by_strategy 胜率/均收益；落盘 `review_*.json`。
- 建议落盘带 `config_version`（策略一 PipelineReport 字段 + 盘中即时/触发条目）→ 支持参数版本 × 绩效对比。
- `scheduler.py` task_postmarket 末尾追加复盘任务（失败不阻断）。

### M5 前端改造
- 新页面「复盘」`复盘.tsx`：天数筛选（7/14/30/60）、按日可展开明细表、参数版本绩效对比聚合；路由 /review + 导航（所有角色可见）。
- 量化配置 SandboxModal 增加「快照回放」模式（实时沙箱 ↔ 快照回放切换，调 /api/strategy/replay，渲染 summary + 各阶段建议 + 快照缺失数）。
- 总览页「昨日建议表现」摘要卡（胜率/平均次日收益，点击进复盘页）；今日建议盘后 Tab 含复盘报告。
- backend 新增 `/api/strategy/replay`、`/api/review` 端点；`_run_sandbox` 支持 module 参数；db.py ALL_PAGE_KEYS 加 review。

### M6 Docker Compose 部署
- `deploy/`：Dockerfile.scheduler + Dockerfile.web（多阶段：node build dist → python 运行）+ docker-compose.yml（双容器共享 quant-system/data 卷，web 端口只绑宿主机 127.0.0.1:8000）+ deploy.sh/update.sh/backup.sh 一键脚本 + README.md 部署方案。
- 关键设计：quant-system 不 pip install 进 site-packages（PROJECT_ROOT 按 __file__ 定位，装进去会漂移），PYTHONPATH 挂源码；web 镜像内嵌 quant-system 源码（沙箱/回放子进程用）；密钥经 env_file 注入不进镜像。
- backend 配套小改动：HOST 环境变量支持（默认 127.0.0.1 不变）、QUANT_BACKEND_DATA 持久化目录（DB/.secret_key 进共享卷）。

### 测试
- 从 33 项增长到 **61 项全过**（新增：策略注册表、静态架构、快照回放确定性、复盘口径）；前端 typecheck + build 通过；backend 导入验证通过。

## 已完成

### 产品与规范
- 确认项目是全新的量化系统，不继承 StockSystem 实现。
- 确认系统只生成股票操作建议，不自动交易；用户自行决定和执行。
- 确认系统必须支持整体迁移到另一台电脑。
- 确认程序负责数据、因子、信号、仓位和风控；LLM 只负责解释与报告。
- 建立 `PROJECT_RULES.md`（长期规范）+ §6.1 接口文档标准。
- 建立 `docs/PRODUCT_TECH_SPEC.md` v0.2（产品决策已确定）。
- 建立 `docs/USER_KNOWLEDGE.md`（3 个策略 + 情绪周期框架 + 术语量化定义）。
- 建立 `.env` / `.env.example` / `.gitignore`；Financial API Key 与选股通 token 由用户在本地填写，未进版本库。

### 策略术语定义（用户确认，已入库）
- 快速 = 一分钟内幅度 > 1%；稍微低开 = 不低于 -3%。
- 承接 = 3 分钟内分时波动 ±2% 内；横盘 = 连续 10 分钟 ±2% 内。
- 反复拉升/出货：拉高不创新高 + 缓慢回落，反复 3 次以上（公式待定义）。
- 三板组 = 连板 3 板：首板量 ≤ 前日 1.2 倍，后两板一字且量 ≤ 首板 1/10。
- 首次调整 = 连板后第一次收盘价 < 开盘价。
- 龙头暂定 = 当前市场连板数最多者；并列规则后续定。

### 数据源实测（均已做真实请求并记录）
- eltdx 3.1.3：9:20 竞价过程、09:25 撮合、1 分钟线、历史分时、开盘金额榜、涨停价、题材强度；独立 Python 脚本化。
- TDX TQLEX：`JNLPSE:wendaQuery` 独立 HTTP 脚本化，竞价成交额前 50（约 0.47s）、历史涨停池（2024-10 可查）、涨停/跌停/炸板/连板、1 分钟线历史深度。
- Financial API（同花顺 fuyao）：竞价快照 15 字段、历史日 K、涨停/跌停/炸板池、连板天梯、龙虎榜、热榜、利润表/资产负债表/现金流、估值、指数/成分、复权因子、交易日历；全部真实调用成功。
- 选股通：情绪温度、涨停池/炸板池/昨日涨停、题材排名 `surge_stock/plates`、题材核心 `plate/data`、题材个股 `surge_stock/stocks`；`xuangutong-data` skill 已补字段级文档。
- 选股通新闻：`baoer-api newsflash` 用 `.env` 中 `XUANGUTONG_IVANKA_TOKEN` 实测成功，返回 20 条；`stocks/bkj_infos/explain_infos` 嵌套结构已验证；skill §12。
- 东财监管：重点监控证券 `emcfg/stock_monitor.json`、严重异常波动/异常波动 `RPT_APP_UNUSUALBASIC`（001 约 9 万+ 条历史可回放）；skill §11。

### 竞价成交额前 10 结论
- 不做全市场逐股竞价快照（3196 只/32 批/3.4s，不合规）。
- 主源：eltdx `realtime_rank(sort_by="开盘金额", count=50)` 服务端排序 + 本地过滤（约 1.36s）。
- 备用：TDX TQLEX wendaQuery（约 0.47s）。
- 降级：Financial API 分批。
- 两条主路径过滤后前 10 名实测一致；已写入 `docs/DATA_CONTRACT.md`。

### 进度文档
- `docs/DATA_SOURCE_RESEARCH.md`：前 6 节已修复，补齐 13/14 节。
- 回顾并整理全套文档：重写 PROJECT_STATUS.md/README.md，DATA_CONTRACT.md 补选股通/新闻/东财契约，规格书升 v0.3，.env.example 补 token；一致性检查无过时残留。
- 开始 Phase 1 适配器层：项目骨架（pyproject.toml / config / models / pool / datasource/base）+ eltdx 适配器 + 测试；本地 venv 安装依赖；tests 全部通过。
- ⚠️ 实测修正：eltdx realtime_rank 的 `amount` 是当日总成交额，竞价成交额必须用 `raw.open_amount`（元）；适配器已按此实现，竞价前 10 与 TDX/Financial API 交叉一致。
- 完成 Financial API 适配器（hithink）：竞价快照/历史日K/涨停池/跌停池/炸板池/连板天梯/市场龙头/利润表/估值；7 测试过。
- 完成选股通适配器（xuangutong）：情绪/涨停池（含历史）/题材排名/题材核心涨幅/题材个股/新闻快讯；7 测试过。
- 完成东财适配器（eastmoney）：重点监控/严重异常/普通异常；3 测试过；修复继承签名导致的 raw_dir 落盘问题。
- 全套 25 测试通过（含真实网络请求），原始响应落盘正常。
- 建立新人引导 `ONBOARDING.md`（必读清单、10 铁律、入场自检、环境命令）。
- **策略一（竞价主力抢筹）端到端闭环完成**：factors/strategies/risk/advice/pipeline 五层 + 单测8项 + 真实数据 e2e 5项；2026-09-04 实数据：10 候选→3 信号→2 建议+1 拦截。
- ⚠️ 实测修正（跨源代码后缀 Bug）：eltdx 生成 `.SS` vs 东财 `.SH` 失配 → 监控黑名单漏拦一鸣食品（在监控期 09-02~09-15 内）。修复：内部统一 `.SH/.SZ` + `normalize_thscode()` 归一化（pool.py）+ 风控比对前归一；修复后正确拦截。全套 39 测试通过。
- **策略二（连板捉妖）端到端完成**：analyzer.py（日线分析器：连板波/一字板/三板组/量比，纯逻辑）+ strategy_lianban.py（候选池→环境→场景）；单测12项+e2e 3项。2026-09-03/04 实测：6只2/3连板→结构过滤通过2只（太阳电缆3.9x/光洋股份3.2x）→拒4只（一字板1/量能不足3）；竞价环境：9只昨日连板、成功率44%、跌峓0→通过；场景：均B（稍微低开待盘中确认）。全套 54 测试通过。
- **策略二盘中触发回放完成**：evaluate_intraday_scene（场景B放量上攻/C先跌后涨，分钟级，“快速”=1分钟>1%用户已定义，“放量”默认≥2x前均量待确认）+ fetch_minute_points（eltdx 历史分时 240 点/日）。真实回放：两候选（太阳/光洋）正确未触发（涨无量/缓涨）；阳性对照亚盛集团 09:37 准确触发（+3.07%/量比2.2x）。新增单测 9 项，全套 63 测试通过。
- **策略三（龙回头）端到端完成**：analyzer 扩展（last_wave/pullback_day/pullback_volume_ratio/pullback_shape）+ strategy_dragon.py（候选池→场景→承接横盘确认）。⚠️ 修正候选池数据源：候选首阴日不在涨停池，须扫 T-2~T-7 池。真实验证 09-04：通过 2 只（博云新材/光洋股份，长上引线量比1.0x）；拒 4 只（首阴量>2x，用户规则“可能连跌”）。承接/横盘确认（3分钟/10分钟±2%）单测验证。全套 74 测试通过。
- **情绪周期状态机上线（用户确认阈值 2026-09-07）**：cycle.py（六态：冰点/转折/修复/加速/分歧/退潮；判定优先级安全优先；收紧立即、放宽需2日确认标记；过热减半；黑天鹅近似）+ CycleThresholds 全部阈值集中一类可快速修改 + 三策略全局门控集成（退潮/冰点→零建议）。策略一 e2e 新增门控不变式测试；策略二/三注入宽松阈值验证完整路径。91 测试全过。
- **架构解耦 OpenClaw（用户要求 2026-09-08）**：① 数据位置确认——全部在项目 data/ 内，代码零引用 quant-research；② 内置调度器 scheduler.py——纯 Python 常驻（--once 单跑/常驻 loop），交易日历（hithink+缓存+周几兜底），09:25 竞价/09:26-10:00 盘中轮询到点自停/15:05 盘后，状态幂等重启安全；③ 推送：主通道 quant-web 已有零侵入对接（监听 data/advice 目录 → WS 推前端），策略二/三/周期/盘中触发全部补落盘；备用 ntfy.sh 手机推送（notify.py，NTFY_TOPIC 环境变量启用）。101 测试全过。
- **首个交易日实盘验证（2026-09-08）**：发现并修复 2 个实盘 Bug——① 日历格式：hithink 返回 YYYYMMDD 紧凑格式，与 YYYY-MM-DD 比对永远失配→调度器误判非交易日静默跳过全部任务（修复：归一化+回归测试）；② opening_match 当日日期误走 history 接口（当日应用 today 接口）→9:25 撮合数据全空。修复后补跑成功：09-08 周期=修复，10 候选→兴业科技 1 只买入信号（9:20 低于昨收+竞价尾段拉升 8.81%），已推送至 quant-web（后端 API 验证收到）。一鲜化脚本 project/start-all.sh / stop-all.sh。Vite pathRewrite Bug 修复（曾剥 /api 前缀致 HTTP 模式 404）。
- **系统已连续自动运行（09-08 至 09-14 每交易日）**：每日竞价/盘中触发/盘后建池均正常。
- **前端问题修复（用户报告 2026-09-14）**：周期/温度不一致——数据都对，规则组合过严（炸板 38.5%+晋级 27.5% 被判退潮），已改复合条件（炸板≥35% 需叠加晋级<25% 或 跌停≥30）；选股页双 Tab（盘中/盘后）、时间线操作徽章醒目、触发时间修复、建议历史改选股历史；连板天梯今天重复列修复+自动滚动最右；quant-web 后端 sentiment 改 line 接口当日点、newsflash has_explain=false、themes 全量、reports 改 /ts/home SSR、Vite /api 前缀修复。
- **测试文件曾被误删（只剩 __pycache__）**：已恢复 cycle/scheduler/pool 三个关键测试（33 项通过），其余测试从会话历史陆续恢复。
- `docs/DATA_CONTRACT.md`：数据契约草案（需按本轮更新，见下一步）。

## 当前待完成
- 更新 `docs/DATA_CONTRACT.md`：补充选股通题材、新闻、东财监管接口到契约；刷新“已知缺口”清单。
- 细化规格书 v0.3：更新已解决/待定项。
- 定义情绪周期、新闻/监管、连板梯队和主线跟踪的数据模型（数据原始字段已具备，进入规则设计）。
- 确定建议格式、回测标准、仓位/止损/止盈规则（需与用户确认）。

## 下一步
1. 数据源阶段收尾：更新契约文档（已完成），补 Financial API 并发/延迟边界测试。
2. 继续适配器层：Financial API（hithink）、选股通（xuangutong）、东财（eastmoney）三个源，每个带冒烟测试。
3. 以交易日当天为目标模拟一次完整链路：竞价 → 盘中 → 盘后。
4. 规则设计：情绪周期状态机、主题持续性判定、龙头定义落地、新闻/监管风险过滤。
5. 选择一个策略做端到端样例：数据 → 因子 → 信号 → 风控 → 建议 → 记录。
6. 之后再规划 Phase 1 正式代码骨架（配置、数据模型、CLI）。

## 重要约束
- 当前只记录设计和实测，尚未创建正式代码、数据库或调度任务（`/workspace/data/quant-research/` 中的测试脚本除外）。
- 用户明确要求重视记录和计划性；后续每次工作必须同步更新本文件。
- 不得把 StockSystem 的脚本、数据目录、cron 或实现直接复制进本项目。
- 接口文档必须字段级清晰，遵守 `PROJECT_RULES.md` §6.1。