# 量化系统演进设计：回测引擎 / 仓位组合层 / 参数绩效闭环

> 2026-09-17 用户确认的三项演进设计。落地顺序：闭环（复用现有数据，成本最低）
> → 回测（闭环的批量历史版）→ 仓位层（依赖前两者的产出做约束）。

## 设计一：参数↔绩效闭环（先做，1-2 天量级）

### 目标
调参不再拍脑袋：任何一次参数修改，都能看到"该版本参数在真实运行中的历史胜率"。

### 现状基础
- 每条建议落盘已带 `config_version`（active.json 版本号，改一次 +1）
- `review.py` 每日核算昨日建议，items 逐条带 config_version
- 配置历史 `data/config/history/v{n}.json` 已保留全量版本

### 设计
1. **聚合报表** `report.py` 新增 `aggregate_by_version(settings, days=N)`：
   扫描 `data/advice/*/review_*.json`，按 `config_version × strategy` 聚合：
   条数 / 双口径胜率 / 均冲高 / 均收盘，输出到 `data/advice/<today>/version_perf.json`。
2. **前端**：量化配置页每张策略卡片底部显示"本版本累计：N 条 · 胜率 X%/Y%(收)"，
   DiffModal 版本对比时并列两版实际绩效。
3. **约束**：版本运行 <10 条样本时标注"样本不足"，避免小样本误导。

### 数据流
```
改参数(active.json v+1) → 建议带新版本号 → 次日 review 核算
→ aggregate_by_version 聚合 → 配置页卡片 / 版本对比展示
```

## 设计二：回测引擎（核心，1-2 周量级）

### 目标
策略规则改动/参数调整前，先在过去 N 个交易日批量验证，产出胜率/盈亏比/回撤/分周期表现。

### 架构：事件回测（复用现有全部基础设施）
不引入新框架，把"生产调度"抽象成"历史日期驱动"：

```
for date in 回测区间(交易日):
    for strategy in 注册表(按阶段):
        T-1 建池(date-1)  → snapshot 快照读取，缺失即中止该日（防未来数据）
        T 竞价场景(date)   → opening_match/竞价快照
        T 盘中确认(date)   → minute_points 快照（9:31-10:00 完整分时）
        周期门控(date)     → market_sentiment/涨停池快照
    产出建议集 → 复用 review 核算口径（次日高低收）→ 累计进绩效桶
```

### 关键决策
1. **数据来源 = data/std 快照 + 按需回填**。快照只保留 7 天，回测更早日期需回填：
   新增 `backfill.py`（hithink 日线/涨停池/选股通情绪均支持历史日期查询，逐日拉取落快照）。
   回填有 API 成本，按需分批。
2. **回测运行器** `backtest.py`：CLI `python -m quant_system.backtest --strategies dragon,tailpan --start 2026-08-01 --end 2026-09-16`，
   子进程隔离（复用 sandbox 模式，防污染生产 advice 目录——落盘到 `data/backtest/<run_id>/`）。
3. **报告**：`backtest_report.json` + 前端"回测"页（新 tab）：总览（条数/双口径胜率/盈亏比/
   最大连亏）、分策略、分周期状态（退潮期表现 vs 加速期表现——验证门控是否有效）、
   分参数版本（与设计一打通）。
4. **防未来数据**：全部经 resolve 快照层（replay_scope 已实现），回填缺失即中止该日并记录。
5. **局限声明**（诚实呈现）：事件回测不含滑点/流动性/排队成交；竞价已涨停 unfillable
   沿用现有标记剔除。

### 验收
- 能对 2026-08-01 以来任意区间跑龙回头+连板+尾盘，输出报告
- 快照缺失日有明确清单，不静默跳过

## 设计三：仓位与组合层（依赖前两者，1 周量级）

### 目标
从"每条建议独立"升级为"账户视角约束"：周期仓位梯度传导 + 集中度控制。

### 1. 仓位梯度传导（补齐现状缺口）
`strategy_gate` 的 factor（0.3/0.5/1.0，过热减半）写入每条 Advice：
```
position = 基准单票仓位(策略配置, 如 20%) × cycle_factor × overheated减半
```
- Advice.position 从"待确认"字符串改为 `{percent, basis}` 结构（前端渲染百分比）
- 三个策略 + 尾盘统一接入（tailpan 已接 gate，补 position 字段）

### 2. 组合约束（建议生成后的第二道闸）
新模块 `portfolio.py`，建议落盘前过三道检查：
- **总仓位上限**：当日已触发建议的 position 合计 ≤ 100%（可配，默认 80% 留现金）
- **单票上限**：同一票当日只出一条建议（现已有去重，补显式检查）
- **同板块集中度**：当日建议按行业/概念分组（数据源：选股通板块接口），单板块 ≤ 40%
  超限时按触发时间先到先得，其余降级为"提示不下单"并记录原因

### 3. 建议输出增强
每条建议最终形态：
```
{thscode, scene, entry, position%, stop_loss(待定规则), gate: 周期+factor,
 portfolio_check: 通过/降级原因, config_version}
```

### 4. 持仓跟踪（可选三期）
若未来接交易/手动登记持仓：`positions.json` 记录在途持仓，与组合约束联动
（持仓 + 当日新建议 ≤ 上限），止损触发提醒。本期只做设计预留，不实现。

## 统一里程碑
| 阶段 | 内容 | 交付物 |
|---|---|---|
| M1 | 版本绩效聚合 + 配置页展示 | version_perf.json + 卡片绩效行 |
| M2 | 回填脚本 + 回测运行器 + 回测报告页 | backtest.py + 前端回测 tab |
| M3 | 仓位传导 + 组合约束 | portfolio.py + Advice.position 结构化 |
| M4 | 持仓跟踪（可选） | positions.json + 止损提醒 |
