import type { Sentiment } from '../types';
import { pct } from '../lib/format';
import clsx from 'clsx';

function tempPhase(v: number): {
  label: string;
  color: string;
  bg: string;
  text: string;
} {
  if (v < 20) return { label: '冰点期', color: 'from-blue-500 to-blue-700', bg: 'bg-blue-500/10', text: 'text-blue-400' };
  if (v < 35) return { label: '修复期', color: 'from-cyan-500 to-cyan-700', bg: 'bg-cyan-500/10', text: 'text-cyan-400' };
  if (v < 50) return { label: '启动期', color: 'from-emerald-500 to-emerald-700', bg: 'bg-emerald-500/10', text: 'text-emerald-400' };
  if (v < 70) return { label: '加速期', color: 'from-amber-500 to-orange-600', bg: 'bg-amber-500/10', text: 'text-amber-400' };
  if (v < 85) return { label: '高潮期', color: 'from-orange-500 to-rose-600', bg: 'bg-orange-500/10', text: 'text-orange-400' };
  return { label: '退潮期', color: 'from-rose-600 to-red-700', bg: 'bg-rose-500/10', text: 'text-rose-400' };
}

interface Props {
  sentiment: Sentiment | null;
  flash?: boolean;
}

export function SentimentGauge({ sentiment, flash }: Props) {
  if (!sentiment) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 flex items-center justify-center text-slate-500 text-sm h-48">
        等待情绪数据…
      </div>
    );
  }
  const v = Math.max(0, Math.min(100, sentiment.temperature));
  const phase = tempPhase(v);
  return (
    <div className={clsx('bg-slate-900 border border-slate-800 rounded-lg p-5', flash && 'flash')}>
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-xs text-slate-400 uppercase tracking-wider">
          市场情绪温度
        </span>
        <span
          className={clsx(
            'text-xs px-2 py-0.5 rounded border',
            phase.bg,
            phase.text,
            'border-current/20'
          )}
        >
          {phase.label}
        </span>
      </div>
      <div className="flex items-end gap-3 mb-3">
        <span className="text-5xl font-bold tabular-nums">{v.toFixed(1)}</span>
        <span className="text-sm text-slate-500 mb-1">/ 100</span>
      </div>
      <div className="h-2 bg-slate-800 rounded-full overflow-hidden mb-3">
        <div
          className={clsx('h-full bg-gradient-to-r transition-all duration-700', phase.color)}
          style={{ width: `${v}%` }}
        />
      </div>
      <div className="text-xs text-slate-500">
        连板高度{' '}
        <span className="text-slate-300 font-mono">
          {sentiment.lianbangaodu ?? '—'}
        </span>{' '}
        板 · 昨日涨停今日溢价{' '}
        <span
          className={clsx(
            'font-mono',
            sentiment.yesterday_limit_up_avg_pcp > 0
              ? 'up'
              : sentiment.yesterday_limit_up_avg_pcp < 0
                ? 'down'
                : 'text-slate-400'
          )}
        >
          {pct(sentiment.yesterday_limit_up_avg_pcp)}
        </span>
      </div>
    </div>
  );
}