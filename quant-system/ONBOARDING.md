# ONBOARDING — 新人 Agent 入场引导

> 本文件给**任何新加入本项目工作的 agent** 读。请按顺序读完并完成文末的"入场自检"，再开始干活。
> 保持此文件更新：如果项目状态或约定变化，同步修改它。

---

## 1. 这个项目是什么

**A 股短线量化选股 + 股票操作建议系统**（个人使用）。

- ✅ 只生成**操作建议**（如"打板1-2成，涨停价排单，炸板即撤"），**不自动下单、不碰券商**。
- ✅ 用户（Gold）自行决定和执行买卖。
- ✅ 可迁移：拷贝项目 + 配 `.env` 即可在另一台电脑运行。
- ❌ 不是筛选股票的工具，是"数据流水线 → 建议 → 记录归因"的完整系统。

## 2. 必读文件（顺序执行）

| # | 文件 | 目的 |
|---|---|---|
| 1 | `PROJECT_RULES.md` | **最高优先级规范**：定位、原则、数据源硬标准、接口文档标准 §6.1、密钥管理 |
| 2 | `PROJECT_STATUS.md` | 当前进度、已完成、待完成、下一步 |
| 3 | `docs/PRODUCT_TECH_SPEC.md` | 产品与技术规格 v0.3：市场/标的/策略/边界/技术选型 |
| 4 | `docs/USER_KNOWLEDGE.md` | **用户交易知识**：3 个策略原文 + 情绪周期框架 + 术语量化定义（必读，策略实现依据） |
| 5 | `docs/DATA_CONTRACT.md` | 字段级数据契约：竞价前10/9:20过程/涨停池/题材/监管/新闻 |
| 6 | `docs/DATA_SOURCE_RESEARCH.md` | 数据源实测记录与能力矩阵（字段语义、单位陷阱、已排除项） |
| 7 | `docs/DATA_SOURCE_TEST_PLAN.md` | 数据源测试标准（只在新增数据源时需要） |
| 8 | `skills/xuangutong-data/SKILL.md`（工作区） | 选股通接口字段级文档（情绪/涨停池/题材/新闻/东财监管） |
| 9 | `docs/` 之外：`src/` 代码 + `tests/` | 现有实现（适配器层） |

## 3. 当前代码结构

```text
src/quant_system/
├── config.py             .env 加载 + 配置校验
├── models.py             Pydantic 统一模型（字段名/单位固定不动）
├── pool.py               股票池过滤（60/00、非ST）
└── datasource/
    ├── base.py           统一接口：重试/落盘/错误/耗时/SHA256
    ├── eltdx_source.py   主源：竞价排名/竞价过程/09:25撮合/分钟K
    ├── hithink.py        Financial API：竞价快照/日K/涨停池/连板天梯/财务/估值
    ├── xuangutong.py     选股通：情绪/涨停池/题材/新闻
    └── eastmoney.py      东财：重点监控/异常波动
tests/                    每源冒烟测试 + 纯逻辑测试（当前 25 个）
```

## 4. 铁律（违反会被打回）

1. **不自动交易、不模拟下单**——只生成建议。
2. **程序决定因子/信号/仓位/风控**；LLM 只写解释文案，不得改数值结论。
3. **股票池固定**：只做 60/00 开头、非 ST/*ST 的普通主板股票；排除 300/301/688/8xx/9xx。
4. **密钥只在 `.env`**：不得写入代码、日志、命令参数、文档、聊天。
5. **回测暂缓**：历史 9:20 竞价过程约从 2025-10 起，不覆盖 2024-10-20；当前目标=交易日当天数据链路。
6. **字段语义以实测为准**：不确定的字段写"待验证"，不得编造单位/阈值。
7. **接口文档必须字段级清晰**（PROJECT_RULES.md §6.1）：新会话不依赖当前上下文也能复现。
8. **策略术语已量化**（见 USER_KNOWLEDGE.md §7）：快速=1分钟>1%；稍微低开=≥-3%；承接=3分钟±2%；横盘=10分钟±2%；三板组/首次调整有明确定义。不得自行改写。
9. **龙头暂定** = 当前市场连板数最多股票；并列处理规则未定。
10. **题材持续性规则**（用户定义）：题材连续 3 个交易日进入 `surge_stock/plates` 排名 = 有持续性；按题材 ID 匹配，不只按名称。

## 5. 环境与运行

```bash
cd /Users/gold/.openclaw/workspace/project/quant-system
./.venv/bin/python -m pytest tests/ -q     # 跑全部测试（含真实网络请求）
./.venv/bin/python -m pytest tests/test_eltdx_source.py -q   # 单源
```

- 虚拟环境已建好：`.venv/`（Python 3.14，已装 pydantic/dotenv/requests/eltdx/pytest）
- 依赖声明：`pyproject.toml`（迁移时 `pip install -e ".[eltdx,dev]"`）
- 密钥：`.env`（已配置 HITHINK_FINANCE_API_KEY、XUANGUTONG_IVANKA_TOKEN；不入库）
- 原始响应落盘：`data/raw/{source}/{date}/`（自动）
- 测试会真实联网；非交易日返回最近交易日快照属正常，不是 bug

## 6. 入场自检（读完必须能回答）

1. 三个策略分别需要哪些数据？（对照 USER_KNOWLEDGE + DATA_CONTRACT）
2. 竞价成交额前 10 怎么拿？主源/备用/降级是什么？为什么不拉全市场？
3. `eltdx` 的 `raw.open_amount` 和 `amount` 有什么区别？为什么不能用后者？
4. `core_avg_pcp`、`px_change_rate`、`change_percent` 是小数还是百分数？
5. 当前缺口有哪些（DATA_CONTRACT §8）？
6. 下一步任务是什么（PROJECT_STATUS"下一步"）？

答不上 → 重读对应文件；不要凭感觉猜。

## 7. 下一步任务（最新）

见 `PROJECT_STATUS.md`"下一步"。当前阶段：适配器层已完成，待做：
1. 当天完整链路模拟（竞价→盘中→盘后）+ 端到端样例
2. 因子层 + 策略层（竞价抢筹/连板捉妖/龙回头）
3. 风控层（环境过滤/监管/仓位）+ 建议输出
4. 记录/归因 + Telegram 推送