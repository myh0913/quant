# 数据契约草案 v0.1（交易日当天可用链路）

> 2026-09-05 实测验证。契约以“交易日当天可脚本化获取”为第一优先；
> 历史回测（2024-10-20 起）暂缓，因历史 9:20 竞价过程可能无法完整获取。
> 测试摘要：`/workspace/data/quant-research/auction-rank-compare.json`。

## 1. 竞价成交额前 N

### 目标
返回竞价成交额（元）降序前 N 只，且只保留 60/00 开头、非 ST/*ST 的普通股票。

### 主路径（已验证）：eltdx 服务端排序
```python
with TdxClient(timeout=3) as client:
    table = client.helpers.realtime_rank(sort_by="开盘金额", count=50)
```
- 服务端按“开盘金额”排序，一次请求，不遍历全市场。
- 实测：请求 50 条，约 1.36s。
- 返回行字段含 `full_code` / `name` / `last_price` / `change_pct` / `amount` / `opening_rush`。
- 竞价金额字段 `open_amount_yuan` 通过 `quotes.get_snapshots(codes)` 补充（已与 TDX/Financial API 交叉验证一致）。
- ⚠️ 返回可能混入 300/688/8xx/9xx，必须本地过滤后再取前 N。

### 备用路径（已验证）：TDX TQLEX wendaQuery
```text
POST http://tdxhub.icfqs.com:7615/TQLEX?Entry=JNLPSE:wendaQuery
Content-Type: application/json
token: <tdx-token>
Body: [{"message":"竞价成交额排名前50","rang":"AG","pageNo":"1","pageSize":"50"}]
```
- 实测：约 0.47s，50 条。
- 返回数组：`[0]=meta`、`[1]=headers`、`[2]=format`、`[3..]=rows`。
- 竞价金额列名含日期：`开盘金额<br>YYYY.MM.DD0#`，需按日期解析，非当日数据必须告警。
- ⚠️ 依赖 TDX token 与自然语言接口；响应解析、股票池过滤、日期校验和重试必须在适配器中实现。

### 降级路径（不推荐常规使用）
Financial API 代码表 + 100 只/批竞价快照 + 本地排序；实测 3196 只约 3.4s/32 批。仅在两个服务端榜单都不可用时使用。

### 契约签名（草案）
```python
def auction_top_amount(limit: int = 10, pool_filter: Callable = default_pool) -> list[AuctionRankRow]:
    """返回竞价成交额降序前 limit 只（已按 pool_filter 过滤）。"""
```
字段：`thscode` / `ticker` / `name` / `auction_amount_yuan` / `auction_pct` / `auction_price` / `open_price` / `pre_close` / `ts` / `source` / `data_date`。

## 2. 9:20/9:25 竞价过程（当天）

### eltdx
```python
client.auctions.series("sz000001")          # 当日竞价过程，09:15 起逐点
client.trades.opening_match_today("sz000001")  # 当日 09:25 正式撮合
```
- 竞价过程点含 `time_label` / `price` / `matched_volume` / `unmatched_volume`。
- 9:25 以 opening_match 为准（series 不含 09:25 正式撮合）。
- 当天可用 ✅；历史最早约 2025-10 起（回测暂缓）。

### Financial API
```text
GET /api/a-share/auction/snapshot?thscodes=...&stage=live|final
```
- 含 `auction_price/auction_pct/auction_amount/auction_unmatched/auction_volume_ratio` 等 15 字段。
- 单批 1-100 只；无历史日期参数。
- 当天可用 ✅。

## 3. 涨停池 / 跌停池 / 炸板池 / 连板天梯

| 能力 | 主源 | 备源 | 实测 |
|---|---|---|---|
| 当日涨停池 | Financial API `limit-up-pool`（分页/size≤200，含涨停时间/原因/连板数/封单额） | TDX TQLEX wendaQuery | ✅ 92ms |
| 当日跌停池 | Financial API `limit-down-pool` | TDX TQLEX | ✅ 87ms |
| 当日炸板池 | Financial API `limit-break-pool`（含 open_times 开板次数） | TDX TQLEX | ✅ 94ms |
| 连板天梯 30 日 | Financial API `limit-up-ladder` | eltdx `limit_ladder()` | ✅ 66ms |

⚠️ Financial API 涨停池不含“涨停打开次数/分时”，TDX 字段更细（首次涨停时间秒级、板型、封单量、涨停成交额），短线实现可两者结合。

## 4. 市场总龙头（暂定定义）

定义：当前市场连板数最多的股票；并列时后续确定规则。

数据来源：
- Financial API `limit-up-pool` 按 `continue_day_cnt` 降序取 1；
- 或 TDX wendaQuery“连板天数排名”；
- 或 eltdx 短线指标/连板天梯。
跨源交叉校验，返回 `{thscode, name, continue_day_cnt, source, ts}`。

## 5. 分钟线 / 分时（当天 + 近期）

| 能力 | 主源 | 实测 |
|---|---|---|
| 1/5/15/30/60 分钟 K | eltdx `bars.get(period="1m"...)` / TDX kline | ✅ 18ms |
| 当日分时 | eltdx `minutes.today()` | ✅ |
| 历史分时（近期） | eltdx `minutes.history(code, date)` | ✅ 240 点/日 |
| 当日分笔 | eltdx `trades.all_today()` | ✅ |

## 6. 情绪 / 题材 / 异动

| 能力 | 主源 | 实测 |
|---|---|---|
| 市场温度/涨停/跌停/炸板率 | 选股通首页 SSR | ✅ |
| 题材强度排行 | eltdx `theme_strength_rank()`（全市场约 125s，需缓存） | ✅ |
| 当日异动原因 | Financial API `anomaly-analysis-list/stock` | ✅ |
| 飙升榜/热股榜 | Financial API `skyrocket-list` / `hot-stock-list` | ✅ |
| 龙虎榜 | Financial API `dragon-tiger-list`（含 stock_items/hot_money_items） | ✅ |

### 6.1 题材/主线（选股通，2026-09-06 实测）

- 题材排名：`GET https://flash-api.xuangubao.com.cn/api/surge_stock/plates`
  - 返回 `data.items[] = {id, name, description}` + `manual_updated_at` + `timestamp`（均 Unix 秒）；数组顺序=当日排名。
  - 无日期参数，当日快照；必须交易日主动采集落盘。
- 题材核心表现：`GET /api/plate/data?fields=core_avg_pcp,plate_name&plates=<ids>`
  - 返回 `data.<plate_id> = {core_avg_pcp, plate_name}`；`core_avg_pcp` 为小数（0.05539≈+5.539%），不是百分数。
- 题材内个股：`GET /api/surge_stock/stocks?normal=true&uplimit=true`
  - 返回 `data.fields`（动态列名）+ `data.items`（二维数组）；必须 `zip(fields,row)` 解码。
  - 字段含 code/prod_name/cur_price/px_change_rate（小数）/circulation_value/plates/enter_time/turnover_ratio/m_days_n_boards/report_* 等；服务端有未命名保留列，不得静默丢弃。
  - 传 `date` 返回 `items=null`，历史能力未确认。
- **题材持续性规则（用户定义）**：连续 3 个交易日出现在 plates 排名中 → 有持续性；周末/节假日不计；按题材 ID 匹配，不只按名称。

## 6.2 新闻/快讯（选股通 baoer-api，2026-09-06 token 实测）

```text
GET https://baoer-api.xuangubao.com.cn/api/v6/message/newsflash
Header: x-ivanka-token（来自 .env 的 XUANGUTONG_IVANKA_TOKEN）
Params: limit(20/100 有效) subj_ids(10=快讯流) has_explain(false/true) platform=pcweb
```

- 响应：`{code=20000, message, data: {messages[], next_cursor}}`；无 token 返回 `code=50008`。
- `messages[]` 27 字段：id/title/summary/impact/stocks/all_stocks/bkj_infos/explain_infos/created_at（Unix 秒）/manual_updated_at/subject_ids/route 等。
- 嵌套：`stocks[]={name,symbol,market}`；`bkj_infos[]={id,name}`；`explain_infos[]={explain_msg_id,explain_msg_title,explain_msg_summary,explain_msg_time,route}`。
- 翻页参数名、历史查询、`impact` 刻度未验证。字段详情见 `xuangutong-data` skill §12。

## 6.3 监管/异动（东财，2026-09-06 实测）

- 重点监控证券（最新）：`GET https://mobappconfig.securities.eastmoney.com/emcfg/stock_monitor.json`
  - 返回数组 `{MARKET, STKNAME, VALIDATESTARTDATE, VALIDATEENDDATE, STKCODE, LINK_URL?}`；MARKET 1=沪 0=深 B=北交所。
- 严重异常波动（002）：`GET https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_APP_UNUSUALBASIC&filter=(UNUSUAL_TYPE="002")...[&sortColumns=NOTICE_DATE,END_DATE&sortTypes=-1,-1&pageNumber=1&pageSize=50&source=SECURITIES&client=APP]`
- 异常波动（001）：同接口 `filter=(UNUSUAL_TYPE="001")`；实测约 9 万+ 条历史可分页回放。
- 关键字段：SECUCODE/SECURITY_NAME_ABBR/START_DATE/END_DATE/NOTICE_DATE/INFO_CODE/UNUSUAL_REASON/MRAKET_TYPE/PREDICT_START_DATE/PREDICT_END_DATE。
- 约束：未声明商业授权，仅低频研究用途；必须带移动端 UA/Referer。字段详情见 skill §11。

## 7. 日线 / 财务 / 估值 / 板块（回测与基本面）

| 能力 | 主源 | 实测 |
|---|---|---|
| 单股历史日 K（≤10 年） | Financial API `prices/historical`（仅 1d） | ✅ 75ms，218 条 |
| 全市场 10 年日 K 导出 | Financial API Market Dumps（Parquet；3 次请求全量） | 📝 待下载验证（回测暂缓后低优先） |
| 复权因子事件流 | Financial API `corporate-actions/adjustment-factors` | ✅ 74ms |
| 利润表/资产负债表/现金流 | Financial API `financials/income|balance|cash-flow` | ✅ 70-110ms |
| 财务指标 | Financial API `financials/indicators`（`report=yyyy-Q` 格式） | ✅ |
| 估值快照 | Financial API `valuations/snapshot`（pe_ttm/pe_mrq/pb_mrq/ps_ttm/pcf_ttm） | ✅ 85ms |
| 板块/指数目录/成分 | Financial API `a-share-index/*` | ✅ 71-85ms |
| 指数历史 K | Financial API `a-share-index/prices/historical` | ✅ 74ms |
| 交易日历 | Financial API `calendar/trading-days`（241 个交易日/年） | ✅ 90ms |

## 8. 已知缺口（交易日当天）

1. 新闻翻页参数名、历史新闻、按日期过滤：未验证（`next_cursor` 存在但翻页参数未知）。
2. `impact`（新闻影响级别）刻度、`subscribe_type` 语义：待与页面口径核对，不能编造阈值。
3. 题材“主线地位/持续性”判定规则：原始数据已有（plates 连续多日快照 + core_avg_pcp），规则待设计。
4. 反复拉升/出货程序化识别、放量/连续放量/封单大小阈值：待与用户确认定义。
5. 选股通/eltdx 并发与频率限制边界未完全测出（官方建议低频、合理节奏）。
6. Financial API 并发与限流边界：未做压力测试。
7. 历史 9:20 竞价过程约从 2025-10 起；2024-10-20 完整回测暂缓（用户已确认）。

## 9. 工程要求

- 所有适配器必须：保存原始响应、校验 `data_date`、显式过滤股票池、超时重试、不把密钥写进代码/日志/仓库。
- 每个数据源独立适配器文件；策略层不直接调用供应商接口。
- 交易日当天链路验证通过后，再进入代码骨架（Phase 1）。
