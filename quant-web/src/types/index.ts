// =========================================================
// 业务类型（选股通风格）
// =========================================================
import { APP_BASE } from '../lib/appBase';

/** 市场情绪 */
export interface Sentiment {
  /** 0-100 */
  temperature: number;
  /** 涨跌家数 */
  rise_count: number;
  fall_count: number;
  stay_count: number;
  /** 涨停 / 跌停 / 炸板 */
  limit_up_count: number;
  limit_down_count: number;
  limit_up_broken_count: number;
  /** 自然涨停 */
  natural_limit_up_count: number;
  /** 炸板率（小数 0.55 = 55%） */
  limit_up_broken_ratio: number;
  /** 昨日涨停今日平均溢价（小数 -0.0058 = -0.58%） */
  yesterday_limit_up_avg_pcp: number;
  /** 连板高度 */
  lianbangaodu: number | null;
  /** 非 ST 同口径 */
  nst: {
    limit_up_count: number;
    limit_down_count: number;
    limit_up_broken_count: number;
    limit_up_broken_ratio: number;
    natural_limit_up_count: number;
    yesterday_limit_up_avg_pcp: number;
  };
  /** 快照时间 ISO */
  ts: string;
}

/** 池子名（7 个） */
export type PoolName =
  | 'limit_up'           // 涨停池
  | 'limit_up_broken'    // 炸板池
  | 'yesterday_limit_up' // 昨日涨停
  | 'super_stock'        // 强势股
  | 'limit_down'         // 跌停池
  | 'new_stock'          // 新股
  | 'nearly_new';        // 次新

export const POOL_LABELS: Record<PoolName, string> = {
  limit_up: '涨停池',
  limit_up_broken: '炸板池',
  yesterday_limit_up: '昨涨停',
  super_stock: '强势股',
  limit_down: '跌停池',
  new_stock: '新股',
  nearly_new: '次新',
};

/** 涨停状态时间线 (status: 1封涨停 2炸板 3封跌停 4开跌停) */
export interface LimitTimelineItem {
  timestamp: number;
  status: 1 | 2 | 3 | 4;
}

/** 关联板块 */
export interface RelatedPlate {
  plate_id: number;
  plate_name: string;
}

/** 涨停原因 */
export interface SurgeReason {
  stock_reason: string;
  related_plates: RelatedPlate[];
}

/** 池内单只股票（涨停池/炸板池等通用结构） */
export interface PoolStock {
  symbol: string;
  stock_chi_name: string;
  price: number;
  /** 涨幅小数（0.0998 = +9.98%） */
  change_percent: number;
  turnover_ratio: number;
  /** 量比 */
  volume_bias_ratio: number;
  /** 总市值 / 流通市值（元） */
  total_capital: number;
  non_restricted_capital: number;
  /** 连板天数 */
  limit_up_days: number;
  /** 连跌天数 */
  limit_down_days: number;
  /** 今日炸板次数 */
  break_limit_up_times: number;
  /** 封单比 / 卖盘封单比 */
  buy_lock_volume_ratio: number;
  sell_lock_volume_ratio: number;
  /** 封板时间戳 */
  first_limit_up?: number;
  last_limit_up?: number;
  first_break_limit_up?: number;
  last_break_limit_up?: number;
  /** 涨停原因 */
  surge_reason?: SurgeReason;
  /** 封板时间线 */
  limit_timeline?: { items: LimitTimelineItem[] };
  /** 上市日期（次新判断） */
  listed_date?: number;
  is_new_stock: boolean;
  issue_price?: number;
  /** N天M板描述 */
  m_days_n_boards_days?: number;
  m_days_n_boards_boards?: number;
}

export interface PoolResponse {
  pool_name: PoolName;
  /** YYYY-MM-DD */
  date: string;
  items: PoolStock[];
  ts: string;
}

/** 7x24 快讯 */
export interface NewsflashItem {
  id: number;
  title: string;
  summary: string | null;
  /** 关联股票 */
  stocks: Array<{ name: string; symbol: string; market?: string }>;
  /** 关联板块 */
  plates: Array<{ id: number; name: string }>;
  /** 解读/正文（HTML 摘要片段） */
  content?: string;
  /** 分类：盘中异动/全球要闻 */
  category?: string;
  /** 时间戳（Unix 秒） */
  created_at: number;
  /** 是否会员 */
  is_premium: boolean;
  /** 影响级别（0-3） */
  impact: number;
}

/** 主题排名 */
export interface Theme {
  id: number;
  name: string;
  description: string | null;
  rank: number;
  /** 核心平均涨幅（来自 plate/data） */
  core_avg_pcp?: number;
  /** 入选快照时间 Unix 秒 */
  manual_updated_at: number;
  timestamp: number;
  /** 题材内涨停/强势个股（来自 surge_stock/stocks） */
  stocks?: ThemeStock[];
}

export interface ThemeStock {
  code: string;
  prod_name: string;
  cur_price: number;
  px_change_rate: number;
  circulation_value: number;
  description: string;
  enter_time: number;
  up_limit: boolean;
  plates: Array<{ id: number; name: string; hot_spot?: boolean }>;
  turnover_ratio: number;
  m_days_n_boards: string;
}

/** 东财监管名单条目（重点监控 / 严重异常波动通用） */
export interface MonitorStock {
  thscode: string;
  /** 6 位代码 */
  code: string;
  name: string;
  /** 市场号（仅重点监控：1=沪 0=深 B=北） */
  market?: string;
  start_date?: string;
  end_date?: string;
  /** 公告日（仅严重异动） */
  notice_date?: string;
  /** 异动原因（仅严重异动） */
  reason?: string;
}

/** 监管名单数据（后端每 5min 缓存刷新） */
export interface MonitorData {
  restricted: MonitorStock[];
  severe: MonitorStock[];
  errors?: string[];
  ts: string;
}

export interface DailySnapshot {
  date: string;          // YYYY-MM-DD
  temperature: number;
  limit_up_count: number;
  limit_down_count: number;
  limit_up_broken_count: number;
  limit_up_broken_ratio: number;
  natural_limit_up_count: number;
  rise_count: number;
  fall_count: number;
  stay_count: number;
  yesterday_limit_up_avg_pcp: number;
  lianbangaodu: number;
  lianban_distribution?: Record<string, number>;
  ts?: number;
}

// =========================================================
// 量化系统选股建议（对齐 quant-system 落盘 JSON 结构）
// =========================================================

/** 候选因子（竞价阶段快照） */
export interface AdviceFactor {
  thscode: string;
  name: string;
  rank: number;
  auction_amount_yuan: number;
  pre_close: number | null;
  p920: number | null;
  p925: number | null;
  rise_920_925: number | null;
  chg_925: number | null;
  below_zero_920: number | null;
  data_date: string;
  errors: string[];
}

/** 单只候选的信号判定结果 */
export interface AdviceResultEntry {
  signal: boolean;
  passed: string[];
  rejected: string[];
}

/** 一条操作建议（quant-system advice.py Advice 模型） */
export interface AdviceItem {
  thscode: string;
  name: string;
  strategy: string;
  /** 买入建议 / 不参与 */
  action: string;
  generated_at: string;
  data_date: string;
  reference_price: number | null;
  trigger_condition: string;
  position: string | null;
  /** 建议仓位比例（基准×周期系数，M3；0=组合风控降级为观察） */
  position_pct?: number | null;
  demoted?: boolean | null;
  portfolio_note?: string;
  stop_loss: string | null;
  valid_until: string;
  factor_summary: Record<string, unknown>;
  reasons: string[];
  risk_notes: string[];
  pending_confirmations: string[];
}

/** 一次策略运行的完整建议报告（advice 目录下的单个 JSON） */
export interface AdviceReport {
  strategy: string;
  data_date: string;
  /** ISO 时间 */
  ran_at: string;
  candidates: number;
  factors: AdviceFactor[];
  /** thscode → 判定结果 */
  results: Record<string, AdviceResultEntry>;
  advices: AdviceItem[];
  blocked: AdviceItem[];
  risk_source_note: string;
  /** 情绪周期六态：冰点/转折/修复/加速/分歧/退潮 */
  cycle_state: string;
  cycle_reasons: string[];
  cycle_position_factor: number;
  /** backend 补充：来源文件名 */
  file?: string;
}

// =========================================================
// 调度器（scheduler.py）产出的其余报告类型
// =========================================================

/** 盘中候选（连板/龙回头候选池条目） */
export interface PoolCandidate {
  thscode: string;
  name: string;
  boards: number;
  /** 连板：首板量/波前一日量；龙回头：首阴量/前日量 */
  volume_ratio?: number | null;
  pb_volume_ratio?: number | null;
  /** 龙回头首阴形态：大阴线/长上引线/普通阴线 */
  shape?: string;
  structure_notes?: string[];
  notes?: string[];
  rejected?: boolean;
  reject_reason?: string;
}

/** 盘后建池报告（策略二/三明日候选） */
export interface PoolReport {
  type: 'lianban_pool' | 'dragon_pool';
  date: string;
  for_next_trading_day: boolean;
  candidates: PoolCandidate[];
  rejected: PoolCandidate[];
  file?: string;
  ran_at?: string;
}

/** 尾盘选股候选（龙回头·尾盘 14:45 当日候选） */
export interface TailpanCandidate {
  thscode: string;
  name: string;
  boards: number;
  /** A=高开回踩 / B=低开收敛 / C=平开低走 */
  scene?: string | null;
  /** 今开/昨收-1 */
  open_pct?: number | null;
  /** 场景A：截至 9:33 最低点/昨收-1 */
  morning_low_pct?: number | null;
  /** 9:33 时点价格涨幅（场景C判定用） */
  pct_933?: number | null;
  /** 判定区间振幅（A/C=9:33 后区间 / B=全天） */
  range_pct?: number | null;
  /** 今日量/连板日最大量 */
  volume_ratio?: number | null;
  /** 现价/昨收-1 */
  last_pct?: number | null;
  last_price?: number | null;
  notes?: string[];
  rejected?: boolean;
  reject_reason?: string;
}

/** 尾盘选股报告（14:45 产出，服务当日尾盘） */
export interface TailpanPoolReport {
  type: 'tailpan_pool';
  date: string;
  /** 连板波基准日（T-1） */
  prev: string;
  candidates: TailpanCandidate[];
  rejected: TailpanCandidate[];
  /** 情绪周期门控（否决时 candidates 为空） */
  gate_state?: string;
  gate_note?: string;
  file?: string;
  ran_at?: string;
}

/** 盘后情绪周期判定报告 */
export interface CycleReport {
  type: 'cycle';
  date: string;
  state: string;
  reasons: string[];
  overheated: boolean;
  /** 关键指标缺失 → 判定可信度降级 */
  data_degraded?: boolean;
  indicators: {
    temperature: number;
    limit_up: number;
    limit_down: number;
    break_ratio: number;
    promotion: number;
    height: number;
    leader: string;
  };
  file?: string;
  ran_at?: string;
}

/** 盘中即时建议 / 触发事件（场景 A/D 即时落盘，B/C/E/F 触发落盘） */
export interface IntradayPlanReport {
  type: 'intraday_plan';
  date: string;
  /** 待盘中确认候选（场景已建立、等待触发） */
  pending: { thscode: string; name: string; scene: string; detail: string }[];
  /** 即时建议（场景 A/D，9:25 已定论） */
  immediate: { strategy: string; thscode: string; name: string; scene: string; detail: string; triggered_at?: string }[];
  /** 构建计划时的当日周期复核（2026-09-17） */
  cycle_check?: { state?: string; degraded?: boolean; vetoed?: string[] };
  file?: string;
  ran_at?: string;
}

export interface IntradayEntry {
  /** 旧版落盘数据可能缺失，展示时用 entryStrategy() 按场景推断兜底 */
  strategy?: string;
  thscode: string;
  name: string;
  scene: string;
  detail: string;
  /** 触发事件附带的判定结果（即时建议无此字段） */
  result?: {
    scene?: string;
    triggered?: boolean;
    confirmed?: boolean;
    /** 观察窗口已过未触发（归因记录，非建议） */
    window_expired?: boolean;
    trigger_time?: string | null;
    trigger_price?: number | null;
    confirm_time?: string | null;
    confirm_price?: number | null;
    minute_pct?: number | null;
    volume_ratio?: number | null;
    detail?: string;
  };
  triggered_at?: string;
  /** 建议仓位比例（基准×周期系数，M3；0=组合风控降级） */
  position_pct?: number | null;
  position?: string | null;
  demoted?: boolean | null;
  portfolio_note?: string;
  file?: string;
  ran_at?: string;
}

/** 复盘单条：上一交易日建议的次日表现核算（review.py 产出） */
export interface ReviewItem {
  thscode: string;
  name: string;
  strategy: string;
  scene?: string | null;
  reference_price?: number | null;
  chg_925_pct?: number | null;
  config_version: number;
  entry: number | null;
  entry_note: string;
  day0_close_pct: number | null;
  /** 主指标：(T日收盘 - 入场价)/入场价，小数 */
  next_close_pct: number | null;
  next_high_pct: number | null;
  next_low_pct: number | null;
  win: boolean | null;
  /** 竞价已涨停，实际可能无法成交（不计胜负） */
  unfillable: boolean;
}

export interface ReviewReport {
  type: 'review';
  /** 核算日（T） */
  date: string;
  /** 建议日（T-1 交易日） */
  advice_date: string;
  ran_at: string;
  items: ReviewItem[];
  by_strategy: Record<
    string,
    {
      count: number; fillable: number; wins: number; win_rate: number | null; avg_next_high_pct: number | null;
      /** 收盘口径（保守）：win_close 统计（2026-09-17 双口径） */
      wins_close?: number; win_rate_close?: number | null; avg_next_close_pct?: number | null;
    }
  >;
  total: number;
  file?: string;
}

/** 今日全部报告的统一类型（按 file 前缀判别 kind） */
export type DailyReportKind =
  | 'auction'
  | 'intraday'
  | 'intraday_plan'
  | 'lianban_pool'
  | 'dragon_pool'
  | 'tailpan_pool'
  | 'cycle'
  | 'review';

export type DailyReport = AdviceReport | PoolReport | CycleReport | IntradayEntry | IntradayPlanReport | TailpanPoolReport | ReviewReport;

/** 按来源文件名判别报告种类（auction_grab 无 type 字段，其余靠 type / strategy 判别） */
export function reportKind(r: DailyReport): DailyReportKind {
  if ('file' in r && r.file) {
    if (r.file.startsWith('auction_grab')) return 'auction';
    if (r.file.startsWith('intraday_plan')) return 'intraday_plan'; // 必须在 intraday 之前（前缀包含）
    if (r.file.startsWith('intraday')) return 'intraday';
    if (r.file.startsWith('lianban_pool')) return 'lianban_pool';
    if (r.file.startsWith('dragon_pool')) return 'dragon_pool';
    if (r.file.startsWith('tailpan_pool')) return 'tailpan_pool';
    if (r.file.startsWith('cycle')) return 'cycle';
    if (r.file.startsWith('review')) return 'review';
  }
  if ('type' in r && r.type) return r.type as DailyReportKind;
  if ('factors' in r) return 'auction';
  return 'intraday';
}

/** 盘中条目策略名：落盘数据缺 strategy 时按场景推断（A/B/C=连板捉妖，D/E/F=龙回头） */
export function entryStrategy(e: IntradayEntry): string {
  if (e.strategy) return e.strategy;
  return ['A', 'B', 'C'].includes(e.scene) ? '连板捉妖' : '龙回头';
}

// =========================================================
// 数据源（纯 WS 长连接；REST 仅用于连接建立后的初始补数据）
// =========================================================

export interface DataSourceConfig {
  /** WebSocket URL（默认同源相对路径：dev 走 vite proxy，生产同域直连） */
  wsUrl: string;
}

export const DEFAULT_DS_CONFIG: DataSourceConfig = {
  wsUrl: `${
    typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss' : 'ws'
  }://${typeof location !== 'undefined' ? location.host : 'localhost:5273'}${APP_BASE}/ws`,
};

// =========================================================
// 连板天梯（涨停池历史聚合）
// =========================================================

/** 天梯单元格：某日某票的连板数与首封时间 */
export interface LadderCell {
  /** 当天连板数（>=2 才会出现） */
  boards: number;
  /** 首封时间 Unix 秒 */
  first_limit_up?: number | null;
}

/** 天梯一行：一只票在各个日期的连板格（缺日期 = 当日未连板/未涨停） */
export interface LadderRow {
  symbol: string;
  name: string;
  /** date -> cell */
  cells: Record<string, LadderCell>;
  /** 历史最高连板数 */
  max_boards: number;
  /** 最新一次上榜的连板数（排序主键） */
  last_boards: number;
  last_date: string;
  /** 最新一次上榜的首封时间（同板数排序次键） */
  last_first_limit_up: number;
}

/** 连板天梯整体数据（行序已按 最新连板数降序 → 首封时间升序 排好） */
export interface LadderData {
  /** 列（日期，升序，只含有数据的交易日） */
  days: string[];
  rows: LadderRow[];
  ts: string;
}

// =========================================================
// WebSocket 协议
// =========================================================

export type WsInbound =
  | { type: 'sentiment'; data: Sentiment }
  | { type: 'sentiment_history'; data: DailySnapshot[] }
  | { type: 'pool'; pool_name: PoolName; data: PoolResponse }
  | { type: 'newsflash'; data: NewsflashItem[] }
  | { type: 'theme'; data: Theme[] }
  | { type: 'monitor'; data: MonitorData }
  | { type: 'advice'; data: DailyReport }
  | { type: 'ladder'; data: LadderData }
  | { type: 'alert'; source: string; message: string; ts: number }
  | { type: 'hello'; message: string }
  | { type: 'heartbeat'; ts: number };

/** 服务端告警：上游接口故障 / 量化引擎任务失败 */
export interface AlertMessage {
  /** 故障来源：sentiment / pool:limit_up / themes / engine:<task> 等 */
  source: string;
  /** 人话描述（已截断） */
  message: string;
  /** 广播时间 Unix 毫秒 */
  ts: number;
}

export type WsOutbound =
  | { type: 'subscribe'; channels: string[] }
  | { type: 'unsubscribe'; channels: string[] }
  | { type: 'ping' };

export type WsStatus = 'connecting' | 'open' | 'closed';

// =========================================================
// 鉴权
// =========================================================

/** user=普通用户（仅历史建议） / advanced=高级用户（除设置外全部） / admin=超管（全部） */
export type Role = 'user' | 'advanced' | 'admin';

export interface Me {
  username: string;
  role: Role;
  /** 当前角色可见页面 key（AppLayout 据此过滤菜单） */
  pages?: string[];
}

export interface ManagedUser extends Me {
  enabled: boolean;
  created_at?: string;
}

export interface RoleInfo {
  /** 角色标识；自定义角色不在内置 Role union 内 */
  name: string;
  label: string;
  is_system: number;
  seq: number;
  /** 该角色页面权限是否已自定义（0=默认矩阵） */
  pages_configured: number;
  /** 已配置的页面 key 列表（pages_configured=0 时忽略） */
  pages: string[];
}

export type InvitationStatus = 'active' | 'expired' | 'revoked';

export interface Invitation {
  code: string;
  role: Role;
  role_label?: string;
  created_by: string;
  created_at: string;
  expires_at: string;
  revoked: number;
  use_count: number;
  status: InvitationStatus;
}

// =========================================================
// 量化配置（策略参数，admin）
// =========================================================

/** 参数类型：percent 存小数（0.02=2%），前端编辑时换算为百分数展示 */
export type ParamType = 'percent' | 'float' | 'int' | 'bool';

export interface StrategyParam {
  key: string;
  label: string;
  type: ParamType;
  default: number | boolean;
  min?: number;
  max?: number;
  step?: number;
  /** 输入框旁单位标签（percent 固定 %；float/int 用此字段，如 倍/分钟/只/天） */
  unit?: string;
  desc?: string;
}

export interface StrategyConfig {
  id: string;
  label: string;
  params: StrategyParam[];
  /** 当前生效值（无覆盖时 = default） */
  values: Record<string, number | boolean>;
}

export interface ConfigStrategiesResp {
  strategies: StrategyConfig[];
  version: number;
  saved_at: string;
  actor: string;
}

export interface ConfigVersion {
  version: number;
  saved_at: string;
  actor: string;
  strategies: Record<string, Record<string, number | boolean>>;
}

// =========================================================
// 量化配置 P2：数据源管理 + 在线测试沙箱（admin）
// =========================================================

export interface DataSourceHealth {
  ok: boolean;
  latency_ms: number;
  detail: string;
  checked_at: string;
}

export interface DataSourceInfo {
  id: string;
  label: string;
  /** tcp | http */
  kind: string;
  capabilities: string[];
  desc?: string;
  health?: DataSourceHealth | null;
}

/** 源偏好：某能力当前使用的主/备数据源 */
export interface CapabilityPref {
  primary: string;
  fallback?: string | null;
}

export interface DataSourcesResp {
  datasources: DataSourceInfo[];
  /** 能力 → 可提供该能力的源（有序=默认优先级） */
  capability_providers: Record<string, string[]>;
  /** 能力 → 当前主/备源（未配置的能力用 providers 首个） */
  prefs: Record<string, CapabilityPref>;
}

/** 沙箱策略测试响应：result 为策略特定报告（与生产落盘同构），前端做宽松解析 */
export interface SandboxTestResp {
  sandbox: boolean;
  strategy: string;
  date: string;
  params_overrides: Record<string, number | boolean> | null;
  ran_at: string;
  duration_ms: number;
  warnings: string[];
  result: Record<string, unknown>;
  error?: string;
  failed?: boolean;
}

/** 回放测试响应（quant_system.replay CLI 同构） */
export interface ReplayResp {
  type: 'replay';
  date: string;
  strategies: string[];
  params_overrides: Record<string, Record<string, number | boolean>>;
  ran_at: string;
  duration_ms: number;
  warnings: string[];
  /** 每策略摘要：建议数/候选数/场景数/触发数/快照缺失数 */
  summary: Record<
    string,
    Partial<{
      advices: number;
      blocked: number;
      candidates: number;
      pool_passed: number;
      scenes: number;
      triggered: number;
      snapshot_missing: number;
    }>
  >;
  results: Record<string, { label: string; phases: Record<string, Record<string, unknown>> }>;
  saved_to?: string;
  error?: string;
  failed?: boolean;
}

/** 复盘历史响应（/api/review） */
export interface ReviewHistoryResp {
  items: ReviewReport[];
  warning?: string;
}

// =========================================================
// M1 版本绩效闭环 / M2 批量回测（admin）
// =========================================================

/** 单版本绩效（review 双口径聚合） */
export interface VersionPerf {
  count: number;
  fillable: number;
  win_rate: number | null;
  win_rate_close: number | null;
  /** 样本 ≥10 才可信（false 显示"样本不足"） */
  sample_enough: boolean;
}

export interface ConfigPerfResp {
  generated_at: string;
  window_days: number;
  min_sample: number;
  /** {策略: {版本(str): VersionPerf}} */
  strategies: Record<string, Record<string, VersionPerf>>;
}

/** 回测聚合桶（整体/分策略/cycle:状态） */
export interface BacktestAgg {
  count: number;
  fillable: number;
  win_rate: number | null;
  win_rate_close: number | null;
  avg_next_high_pct: number | null;
}

export interface BacktestRunResp {
  run_id: string;
  trading_days: number;
  aggregate: Record<string, BacktestAgg>;
  entries: number;
  error?: string;
  failed?: boolean;
}

export interface BacktestListItem {
  run_id: string;
  start: string;
  end: string;
  strategies: string[];
  trading_days: number;
  aggregate: Record<string, BacktestAgg>;
  ran_at: string;
}

/** 回测单条建议（核算后） */
export interface BacktestEntry {
  strategy: string;
  thscode: string;
  name: string;
  scene: string;
  kind: string;
  date: string;
  next_date: string;
  entry_price: number | null;
  entry_note?: string;
  position_pct: number | null;
  demoted?: boolean;
  gate_state: string;
  day0_close_pct: number | null;
  next_close_pct: number | null;
  next_high_pct: number | null;
  win: boolean | null;
  win_close: boolean | null;
  unfillable: boolean;
  detail?: string;
}

export interface BacktestReport {
  type: 'backtest';
  run_id: string;
  start: string;
  end: string;
  strategies: string[];
  ran_at: string;
  trading_days: number;
  aggregate: Record<string, BacktestAgg>;
  entries: BacktestEntry[];
  entries_truncated?: boolean;
  days: { date: string; strategy: string; gate?: string; entries?: number; error?: string }[];
  limitations: string[];
}