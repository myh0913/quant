import type { ReactNode } from 'react';
import type { Theme } from '../types';
import { pct, toneClass } from '../lib/format';
import clsx from 'clsx';

export function ThemeCard({
  theme,
  active,
  onClick,
  badge,
}: {
  theme: Theme;
  active?: boolean;
  onClick?: () => void;
  /** 右上角内联徽标（如历史视图的"今日仍在榜"），与涨幅同行渲染，不会重叠 */
  badge?: ReactNode;
}) {
  const pcp = theme.core_avg_pcp ?? 0;
  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full text-left p-3 rounded-lg border transition-colors',
        active
          ? 'bg-blue-600/15 border-blue-500/40'
          : 'bg-slate-900 border-slate-800 hover:border-slate-700'
      )}
    >
      <div className="flex items-baseline justify-between mb-1 gap-2 min-w-0">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-xs text-slate-500 font-mono shrink-0">#{theme.rank}</span>
          <span className="font-semibold truncate">{theme.name}</span>
        </div>
        <div className="flex items-baseline gap-1.5 shrink-0">
          {badge}
          <span
            className={clsx(
              'text-sm font-mono tabular-nums',
              toneClass(pcp)
            )}
          >
            {pcp > 0 ? '+' : ''}
            {pct(pcp)}
          </span>
        </div>
      </div>
      <div className="text-xs text-slate-400 line-clamp-2 leading-relaxed">
        {theme.description ?? '—'}
      </div>
      {theme.stocks && theme.stocks.length > 0 && (
        <div className="mt-2 text-[10px] text-slate-500">
          {theme.stocks.length} 只核心股
        </div>
      )}
    </button>
  );
}