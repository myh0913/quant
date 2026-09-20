import { useCallback, useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { RefreshCw, TrendingUp, Target, Loader2 } from 'lucide-react';
import { api } from '../lib/api';
import { EmptyState } from '../components/EmptyState';
import type { ReviewItem, ReviewReport } from '../types';

function pct(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;
}

function pctCls(v: number | null | undefined): string {
  if (v == null) return 'text-slate-500';
  return v > 0 ? 'text-red-400' : 'text-emerald-400';
}

function ItemTable({ items }: { items: ReviewItem[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-500 border-b border-slate-800">
            <th className="text-left py-1.5 pr-3 font-medium">股票</th>
            <th className="text-left py-1.5 pr-3 font-medium">策略</th>
            <th className="text-left py-1.5 pr-3 font-medium">场景</th>
            <th className="text-right py-1.5 pr-3 font-medium">入场价</th>
            <th className="text-right py-1.5 pr-3 font-medium" title="建议当日收盘 vs 入场">当日收盘</th>
            <th className="text-right py-1.5 pr-3 font-medium" title="次日收盘 vs 入场">次日收盘</th>
            <th className="text-right py-1.5 pr-3 font-medium" title="次日最高 vs 入场（主指标：冲高可卖出的盈亏）">次日最高</th>
            <th className="text-right py-1.5 pr-3 font-medium">次日最低</th>
            <th className="text-center py-1.5 pr-3 font-medium">结果</th>
            <th className="text-right py-1.5 font-medium">参数版本</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={`${it.thscode}-${i}`} className="border-b border-slate-800/50">
              <td className="py-1.5 pr-3">
                <span className="text-slate-300">{it.name}</span>
                <span className="text-slate-600 font-mono ml-1.5">{it.thscode}</span>
              </td>
              <td className="py-1.5 pr-3 text-slate-400">{it.strategy}</td>
              <td className="py-1.5 pr-3 text-slate-500">{it.scene ?? '—'}</td>
              <td className="py-1.5 pr-3 text-right text-slate-300 font-mono">
                {it.entry != null ? it.entry.toFixed(2) : '—'}
                {it.entry_note && (
                  <span className="text-slate-600 ml-1" title={it.entry_note}>*</span>
                )}
              </td>
              <td className={clsx('py-1.5 pr-3 text-right font-mono', pctCls(it.day0_close_pct))}>
                {pct(it.day0_close_pct)}
              </td>
              <td className={clsx('py-1.5 pr-3 text-right font-mono', pctCls(it.next_close_pct))}>
                {pct(it.next_close_pct)}
              </td>
              <td className={clsx('py-1.5 pr-3 text-right font-mono font-medium', pctCls(it.next_high_pct))}>
                {pct(it.next_high_pct)}
              </td>
              <td className={clsx('py-1.5 pr-3 text-right font-mono', pctCls(it.next_low_pct))}>
                {pct(it.next_low_pct)}
              </td>
              <td className="py-1.5 pr-3 text-center">
                {it.unfillable ? (
                  <span className="text-amber-300/80" title="竞价已涨停，实际可能无法成交（不计胜负）">
                    买不进
                  </span>
                ) : it.win == null ? (
                  <span className="text-slate-600">无数据</span>
                ) : it.win ? (
                  <span className="text-red-300">赢</span>
                ) : (
                  <span className="text-emerald-300">亏</span>
                )}
              </td>
              <td className="py-1.5 text-right text-slate-500 font-mono">
                {it.config_version ? `v${it.config_version}` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DayBlock({ r }: { r: ReviewReport }) {
  const [open, setOpen] = useState(false);
  const wins = Object.values(r.by_strategy).reduce((a, b) => a + b.wins, 0);
  const count = Object.values(r.by_strategy).reduce((a, b) => a + b.count, 0);
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 px-4 py-3 text-left">
        <span className="text-xs text-slate-500 font-mono w-24 shrink-0">{r.advice_date}</span>
        <span className="text-sm text-slate-200">
          {r.total} 条建议 · 胜率{' '}
          <span className={count > 0 && wins / count >= 0.5 ? 'text-red-300' : 'text-emerald-300'}>
            {count > 0 ? `${((wins / count) * 100).toFixed(0)}%` : '—'}
          </span>
        </span>
        <span className="flex gap-2 flex-wrap ml-2">
          {Object.entries(r.by_strategy).map(([strat, agg]) => (
            <span key={strat} className="text-[11px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
              {strat} {agg.count}条
              {agg.win_rate != null && ` · ${(agg.win_rate * 100).toFixed(0)}%`}
            </span>
          ))}
        </span>
        <span className="ml-auto text-slate-600 text-xs">{open ? '收起' : '展开明细'}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-slate-800 pt-3">
          {r.items.length > 0 ? (
            <ItemTable items={r.items} />
          ) : (
            <div className="text-xs text-slate-500">该日无可操作建议（无建议或全部被门控/风控拦截）</div>
          )}
        </div>
      )}
    </div>
  );
}

export function ReviewPage() {
  const [items, setItems] = useState<ReviewReport[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');
  const [days, setDays] = useState(14);

  const reload = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const r = await api.reviewHistory('/api', days);
      setItems(r.items);
      if (r.warning) setErr(r.warning);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    reload();
  }, [reload]);

  // 区间分策略累计胜率（核心问题：哪个策略靠谱）
  const strategyAgg = useMemo(() => {
    const m = new Map<string, { count: number; fillable: number; wins: number; pcts: number[] }>();
    for (const rep of items ?? []) {
      for (const it of rep.items) {
        const key = it.strategy || '未知';
        const agg = m.get(key) ?? { count: 0, fillable: 0, wins: 0, pcts: [] };
        agg.count += 1;
        m.set(key, agg);
        if (it.unfillable || it.next_high_pct == null) continue;
        agg.fillable += 1;
        if (it.win) agg.wins += 1;
        agg.pcts.push(it.next_high_pct);
      }
    }
    return [...m.entries()]
      .sort((a, b) => b[1].count - a[1].count)
      .map(([name, agg]) => ({
        name,
        count: agg.count,
        fillable: agg.fillable,
        winRate: agg.fillable ? agg.wins / agg.fillable : null,
        avg: agg.pcts.length ? agg.pcts.reduce((a, b) => a + b, 0) / agg.pcts.length : null,
      }));
  }, [items]);

  // 参数版本 × 绩效聚合（回答"我调的参数到底变好没有"）
  const versionAgg = useMemo(() => {
    const m = new Map<number, { count: number; wins: number; pcts: number[] }>();
    for (const rep of items ?? []) {
      for (const it of rep.items) {
        if (it.unfillable || it.next_high_pct == null) continue;
        const v = it.config_version || 0;
        const agg = m.get(v) ?? { count: 0, wins: 0, pcts: [] };
        agg.count += 1;
        if (it.win) agg.wins += 1;
        agg.pcts.push(it.next_high_pct);
        m.set(v, agg);
      }
    }
    return [...m.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([v, agg]) => ({
        v,
        count: agg.count,
        winRate: agg.count ? agg.wins / agg.count : null,
        avg: agg.pcts.length ? agg.pcts.reduce((a, b) => a + b, 0) / agg.pcts.length : null,
      }));
  }, [items]);

  return (
    <div className="p-6 space-y-6 flex-1 min-h-0 overflow-y-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">复盘</h1>
          <div className="text-xs text-slate-500 mt-1">
            每日盘后自动核算上一交易日建议的次日表现 · 主指标=次日最高 vs 入场价（冲高可卖出的盈亏） · 入场价优先用建议参考价/触发价
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-slate-900 border border-slate-800 rounded-md px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-slate-600"
          >
            {[7, 14, 30, 60].map((d) => (
              <option key={d} value={d}>最近 {d} 天</option>
            ))}
          </select>
          <button
            onClick={reload}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} 刷新
          </button>
        </div>
      </div>

      {err && (
        <div className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-md px-3 py-2">
          {err}
        </div>
      )}

      {strategyAgg.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <Target size={15} className="text-emerald-300" />
            <span className="text-sm font-medium text-slate-200">分策略胜率</span>
            <span className="text-xs text-slate-500">最近 {days} 天累计 · 胜率分母=可成交条数（买不进不计）</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-1.5 pr-3 font-medium">策略</th>
                  <th className="text-right py-1.5 pr-3 font-medium">建议数</th>
                  <th className="text-right py-1.5 pr-3 font-medium">可成交</th>
                  <th className="text-right py-1.5 pr-3 font-medium">胜率</th>
                  <th className="text-right py-1.5 font-medium">均冲高</th>
                </tr>
              </thead>
              <tbody>
                {strategyAgg.map((a) => (
                  <tr key={a.name} className="border-b border-slate-800/50 last:border-0">
                    <td className="py-1.5 pr-3 text-slate-300">{a.name}</td>
                    <td className="py-1.5 pr-3 text-right font-mono text-slate-400">{a.count}</td>
                    <td className="py-1.5 pr-3 text-right font-mono text-slate-400">{a.fillable}</td>
                    <td className={clsx('py-1.5 pr-3 text-right font-mono font-medium',
                      a.winRate != null && a.winRate >= 0.5 ? 'text-red-300' : 'text-emerald-300')}>
                      {a.winRate != null ? `${(a.winRate * 100).toFixed(0)}%` : '—'}
                    </td>
                    <td className={clsx('py-1.5 text-right font-mono font-medium', pctCls(a.avg))}>
                      {pct(a.avg)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {versionAgg.length > 1 && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp size={15} className="text-emerald-300" />
            <span className="text-sm font-medium text-slate-200">参数版本绩效对比</span>
            <span className="text-xs text-slate-500">按建议产生时的配置版本聚合（v—=历史无版本记录）</span>
          </div>
          <div className="flex flex-wrap gap-3">
            {versionAgg.map((a) => (
              <span key={a.v} className="text-xs px-2.5 py-1.5 rounded bg-slate-950/60 border border-slate-800 text-slate-300">
                <span className="font-mono text-slate-400 mr-1.5">{a.v ? `v${a.v}` : 'v—'}</span>
                {a.count} 条 · 胜率 {a.winRate != null ? `${(a.winRate * 100).toFixed(0)}%` : '—'}
                {a.avg != null && (
                  <span className={a.avg > 0 ? 'text-red-300 ml-1' : 'text-emerald-300 ml-1'}>
                    均 {a.avg > 0 ? '+' : ''}{(a.avg * 100).toFixed(2)}%
                  </span>
                )}
              </span>
            ))}
          </div>
        </div>
      )}

      {items == null ? (
        <div className="text-sm text-slate-500">加载中…</div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<TrendingUp size={28} className="text-slate-600" />}
          title="暂无复盘报告"
          hint="调度器每日 17:00 盘后自动核算上一交易日的建议表现（需系统连续运行两日以上）"
        />
      ) : (
        <div className="space-y-2">
          {items.map((r) => (
            <DayBlock key={`${r.advice_date}-${r.file ?? r.ran_at}`} r={r} />
          ))}
        </div>
      )}

      <div className="text-[11px] text-slate-600">
        口径：竞价涨停无法成交的条目标记「买不进」不计胜负；盘中触发条目入场价优先用触发/确认价，缺省用当日开盘价近似（标 *）
      </div>
    </div>
  );
}
