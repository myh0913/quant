import type { Theme } from '../types';
import { pct, toneClass, timeSec } from '../lib/format';
import clsx from 'clsx';

export function ThemeDetail({ theme }: { theme: Theme | null }) {
  if (!theme) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-12 text-center text-slate-500 text-sm">
        从左侧选择一个主题查看详情
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
        <div className="flex items-baseline justify-between mb-2">
          <div>
            <div className="text-xs text-slate-500 mb-1">主题排名 #{theme.rank}</div>
            <h2 className="text-2xl font-bold flex items-center gap-2">
              {theme.name}
            </h2>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500 mb-1">核心平均涨幅</div>
            <div
              className={clsx(
                'text-3xl font-bold tabular-nums',
                toneClass(theme.core_avg_pcp ?? 0)
              )}
            >
              {((theme.core_avg_pcp ?? 0) > 0 ? '+' : '') +
                pct(theme.core_avg_pcp ?? 0)}
            </div>
          </div>
        </div>
        <p className="text-sm text-slate-400 leading-relaxed mt-3">
          {theme.description ?? '—'}
        </p>
      </div>

      {theme.stocks && theme.stocks.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="px-4 py-2 border-b border-slate-800 text-xs text-slate-500">
            题材内个股 · {theme.stocks.length} 只
          </div>
          <table className="w-full text-sm">
            <thead className="bg-slate-800/40 text-xs uppercase text-slate-400">
              <tr>
                <th className="text-left px-3 py-2">股票</th>
                <th className="text-right px-3 py-2">现价</th>
                <th className="text-right px-3 py-2">涨幅</th>
                <th className="text-right px-3 py-2">换手</th>
                <th className="text-right px-3 py-2">连板</th>
                <th className="text-left px-3 py-2">入选时间</th>
              </tr>
            </thead>
            <tbody>
              {theme.stocks.map((s) => (
                <tr key={s.code} className="border-t border-slate-800">
                  <td className="px-3 py-2">
                    <div className="font-semibold">{s.prod_name}</div>
                    <div className="text-xs text-slate-500 font-mono">{s.code}</div>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {s.cur_price.toFixed(2)}
                  </td>
                  <td
                    className={clsx(
                      'px-3 py-2 text-right tabular-nums',
                      toneClass(s.px_change_rate)
                    )}
                  >
                    {s.px_change_rate > 0 ? '+' : ''}
                    {pct(s.px_change_rate)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-400">
                    {pct(s.turnover_ratio)}
                  </td>
                  <td className="px-3 py-2 text-right text-xs text-slate-400">
                    {s.m_days_n_boards}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-400 font-mono">
                    {timeSec(s.enter_time)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}