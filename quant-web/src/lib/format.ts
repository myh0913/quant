/** 涨幅小数 → 百分比字符串 */
export function pct(p: number, digits = 2): string {
  return `${(p * 100).toFixed(digits)}%`;
}

/** 数字中文格式化 */
export function num(n: number): string {
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(2)}万`;
  return n.toString();
}

/** 当前价 */
export function price(n: number): string {
  return n.toFixed(2);
}

/**
 * Unix **秒** → HH:MM:SS（选股通 / 多数行情 API 都是秒）
 */
export function timeSec(ts: number): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toTimeString().slice(0, 8);
}

/**
 * Unix **秒** → HH:MM（短格式）
 */
export function timeSecShort(ts: number): string {
  if (!ts) return '—';
  return new Date(ts * 1000).toTimeString().slice(0, 5);
}

/** 相对时间（输入秒） */
export function relativeTime(ts: number): string {
  const diff = Math.floor(Date.now() / 1000 - ts);
  if (diff < 60) return `${diff} 秒前`;
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return `${Math.floor(diff / 86400)} 天前`;
}

/** 板数展示 */
export function boardsText(days: number, boards: number | undefined): string {
  if (!boards || boards <= 0) return days > 0 ? `${days}天0板` : '—';
  if (days > 0) return `${days}天${boards}板`;
  return `${boards}板`;
}

/** A股配色 className */
export function toneClass(p: number): string {
  if (p > 0) return 'up';
  if (p < 0) return 'down';
  return 'text-slate-400';
}

/** 转换选股通代码 600519.SS → sh600519 / sz000001 */
export function symbolToDisplay(s: string): { exchange: string; code: string } {
  const m = s.match(/^(\d+)\.(SS|SZ|SH)$/);
  if (!m) return { exchange: '', code: s };
  const ex = m[2] === 'SS' ? 'sh' : m[2] === 'SZ' ? 'sz' : m[2] === 'SH' ? 'sh' : 'bj';
  return { exchange: ex, code: m[1] };
}