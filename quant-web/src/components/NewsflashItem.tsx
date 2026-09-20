import type { NewsflashItem } from '../types';
import { relativeTime, timeSec } from '../lib/format';
import clsx from 'clsx';

const IMPACT_LABEL = ['常规', '关注', '重要', '重磅'];
const IMPACT_TONE = ['text-slate-400', 'text-blue-400', 'text-amber-400', 'text-rose-400'];

export function NewsflashItemRow({
  item,
  flash,
  compact,
}: {
  item: NewsflashItem;
  flash?: boolean;
  compact?: boolean;
}) {
  return (
    <div
      className={clsx(
        'bg-slate-900 border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors',
        flash && 'flash'
      )}
    >
      <div className="flex items-start gap-3">
        <div className="flex flex-col items-center shrink-0 w-14">
          <div
            className={clsx(
              'text-[10px] uppercase tracking-wider font-semibold',
              IMPACT_TONE[Math.min(item.impact, 3)] ?? 'text-slate-400'
            )}
          >
            {IMPACT_LABEL[Math.min(item.impact, 3)] ?? '常规'}
          </div>
          <div className="text-xs text-slate-500 font-mono mt-0.5">
            {relativeTime(item.created_at)}
          </div>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 mb-1.5 flex-wrap">
            <span className="font-semibold text-base">{item.title}</span>
            {item.is_premium && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/30">
                会员
              </span>
            )}
            {item.category && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-300">
                {item.category}
              </span>
            )}
          </div>
          {!compact && item.summary && (
            <p className="text-sm text-slate-400 leading-relaxed mb-2">
              {item.summary}
            </p>
          )}
          <div className="flex items-center gap-3 text-xs flex-wrap">
            {item.stocks.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {item.stocks.slice(0, 4).map((s) => (
                  <span
                    key={s.symbol}
                    className="px-2 py-0.5 rounded bg-rose-500/10 text-rose-300 border border-rose-500/20 font-mono"
                  >
                    {s.name}
                  </span>
                ))}
                {item.stocks.length > 4 && (
                  <span className="text-slate-500">
                    +{item.stocks.length - 4}
                  </span>
                )}
              </div>
            )}
            {item.plates.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {item.plates.slice(0, 3).map((p) => (
                  <span
                    key={p.id}
                    className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-300 border border-blue-500/20"
                  >
                    {p.name}
                  </span>
                ))}
              </div>
            )}
            <span className="ml-auto font-mono text-slate-500">
              {timeSec(item.created_at)}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}