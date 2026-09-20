# Quant System

可迁移的 A 股短线量化选股与股票操作建议系统。

> 本项目只生成建议，不自动下单。用户自行决定和执行买卖。
> 首期：A 股 60/00 开头普通股票；短线、只做多；竞价主力抢筹 / 连板捉妖 / 龙回头。

## 项目文档（开始任何工作前先读）

| 文档 | 内容 |
|---|---|
| `PROJECT_RULES.md` | 必须长期遵守的规范：定位、原则、数据源硬标准、**接口文档标准 §6.1**、密钥管理 |
| `PROJECT_STATUS.md` | 当前进度、已完成、待完成、下一步 |
| `docs/PRODUCT_TECH_SPEC.md` | 产品与技术规格书（市场/标的/策略/回测边界/技术选型） |
| `docs/USER_KNOWLEDGE.md` | 用户交易知识：3 个策略原文 + 情绪周期框架 + 术语量化定义 |
| `docs/DATA_SOURCE_RESEARCH.md` | 数据源能力矩阵与实测记录（选股通/TDX/eltdx/Financial API/东财） |
| `docs/DATA_SOURCE_TEST_PLAN.md` | 数据源测试计划与硬标准 |
| `docs/DATA_CONTRACT.md` | 字段级数据契约（竞价前10/9:20过程/涨停池/连板/题材/监管等） |
| `ONBOARDING.md` | 新人 Agent 入场引导（新 agent 必读） |

## 当前状态

Phase 0：产品规格 + 数据源勘察（接近完成）。

- 产品决策已确定：只做 A 股 60/00 主板、只做多、只给建议、分钟级、3 个策略、Telegram 推送。
- 数据源已实测：eltdx、TDX TQLEX、Financial API、选股通、东财监管。
- 竞价成交额前 10 服务端排序方案已验证（主 eltdx / 备 TDX）。
- 历史 9:20 竞价回测暂缓（历史覆盖不足），优先交易日当天数据链路。
- 下一步：数据适配器层 + 规则设计 + 最小端到端样例。

## 环境与运行

```bash
cp .env.example .env   # 填入 API Key（Financial API / 选股通 token），勿提交
./.venv/bin/python -m pytest tests/ -q   # 全量测试
```

### 独立运行（与 OpenClaw 无关，任何机器可用）

```bash
# 常驻调度器（推荐，开机自启可用 launchd/cron/systemd 拉起）
./.venv/bin/python -m quant_system.scheduler

# 或手动单跑一个任务
./.venv/bin/python -m quant_system.scheduler --once auction      # 策略一
./.venv/bin/python -m quant_system.scheduler --once intraday    # 盘中触发检查
./.venv/bin/python -m quant_system.scheduler --once postmarket  # 盘后建池+周期
```

交易日时间轴：09:25 竞价策略 / 09:26-10:00 盘中轮询（到点自停）/ 17:00 盘后。

### 实时推送（quant-web）

量化系统只需把建议落盘 `data/advice/<日期>/`；quant-web 后端监听该目录
（QUANT_ADVICE_DIR），新文件 → WebSocket 实时推到浏览器，零侵入。

### 可选手机推送（ntfy）

`.env` 加 `NTFY_TOPIC=<自定义主题>`，手机装 ntfy App 订阅同名主题。

密钥只存 `.env`（已 gitignore），不写入代码、日志、命令或仓库。
