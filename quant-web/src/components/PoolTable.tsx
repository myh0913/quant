import type { PoolStock, PoolResponse } from '../types';
import {
  pct,
  num,
  toneClass,
  timeSecShort,
  symbolToDisplay,
  boardsText,
} from '../lib/format';
import { PoolTimeline } from './PoolTimeline';
import { useStore } from '../store';
import clsx from 'clsx';

interface Props {
  pool: PoolResponse;
  flash?: boolean;
}

export function PoolTable({ pool, flash }: Props) {
  // 展开状态移到 store，避免推送触发的 re-render 把 useState 重置
  const expanded = useStore((s) => s.expandedPool);
  const toggleExpandedPool = useStore((s) => s.toggleExpandedPool);
  const items = pool.items;

  return (
    <div
      className={clsx(
        'bg-slate-900 border border-slate-800 rounded-lg overflow-hidden',
        flash && 'flash'
      )}
    >
      <div className="px-4 py-2 border-b border-slate-800 flex items-baseline justify-between text-xs text-slate-500">
        <span>共 {items.length} 只 · 日期 {pool.date}</span>
        <span>
          更新于{' '}
          {new Date(pool.ts).toLocaleTimeString('zh-CN', { hour12: false })}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-800/40 text-xs uppercase text-slate-400">
            <tr>
              <th className="text-left px-3 py-2 w-24">股票</th>
              <th className="text-right px-3 py-2">现价</th>
              <th className="text-right px-3 py-2">涨幅</th>
              <th className="text-right px-3 py-2">连板</th>
              <th className="text-right px-3 py-2">换手</th>
              <th className="text-right px-3 py-2">市值</th>
              <th className="text-right px-3 py-2">封板时间</th>
              <th className="text-left px-3 py-2">涨停原因</th>
              <th className="text-center px-3 py-2 w-20">详情</th>
            </tr>
          </thead>
          <tbody>
            {items.map((s) => {
              const expandedKey = `${pool.pool_name}:${s.symbol}`;
              const isOpen = expanded === expandedKey;
              return (
                <RowGroup
                  key={expandedKey}
                  stock={s}
                  poolName={pool.pool_name}
                  isOpen={isOpen}
                  onToggle={() => toggleExpandedPool(isOpen ? null : expandedKey)}
                />
              );
            })}
            {items.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-12 text-center text-sm text-slate-500">
                  该池子暂无数据
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface RowGroupProps {
  stock: PoolStock;
  poolName: string;
  isOpen: boolean;
  onToggle: () => void;
}

function RowGroup({ stock: s, isOpen, onToggle }: RowGroupProps) {
  return (
    <>
      <tr
        className="border-t border-slate-800 hover:bg-slate-800/30 cursor-pointer"
        onClick={onToggle}
      >
        <td className="px-3 py-2">
          <div className="font-semibold">{s.stock_chi_name}</div>
          <div className="text-xs text-slate-500 font-mono">
            {symbolToDisplay(s.symbol).exchange}
            {symbolToDisplay(s.symbol).code}
          </div>
        </td>
        <td className="px-3 py-2 text-right tabular-nums">{s.price.toFixed(2)}</td>
        <td
          className={clsx(
            'px-3 py-2 text-right tabular-nums',
            toneClass(s.change_percent)
          )}
        >
          {s.change_percent > 0 ? '+' : ''}
          {pct(s.change_percent)}
        </td>
        <td className="px-3 py-2 text-right">
          <span
            className={clsx(
              'px-1.5 py-0.5 rounded text-xs font-mono',
              s.limit_up_days >= 3
                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                : 'bg-slate-700/50 text-slate-300'
            )}
          >
            {boardsText(s.limit_up_days ?? 0, s.limit_up_days)}
          </span>
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-400">
          {pct(s.turnover_ratio)}
        </td>
        <td className="px-3 py-2 text-right tabular-nums text-slate-400">
          {num(s.non_restricted_capital)}
        </td>
        <td className="px-3 py-2 text-right font-mono text-xs text-slate-400">
          {s.first_limit_up ? timeSecShort(s.first_limit_up) : '—'}
        </td>
        <td className="px-3 py-2 max-w-md">
          <div className="text-xs text-slate-300 truncate">
            {s.surge_reason?.stock_reason ?? '—'}
          </div>
          {s.surge_reason?.related_plates?.length ? (
            <div className="flex flex-wrap gap-1 mt-0.5">
              {s.surge_reason.related_plates.map((p) => (
                <span
                  key={p.plate_id}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-300 border border-blue-500/20"
                >
                  {p.plate_name}
                </span>
              ))}
            </div>
          ) : null}
        </td>
        <td className="px-3 py-2 text-center text-xs text-slate-500">
          {isOpen ? '收起' : '展开'}
        </td>
      </tr>
      {isOpen && (
        <tr className="border-t border-slate-800 bg-slate-950/40">
          <td colSpan={9} className="px-3 py-3">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-slate-500 uppercase mb-2">
                  关键指标
                </div>
                <dl className="space-y-1 text-xs">
                  <div className="flex gap-2">
                    <dt className="text-slate-500 shrink-0">量比</dt>
                    <dd className="font-mono">{s.volume_bias_ratio.toFixed(2)}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-slate-500 shrink-0">封单比</dt>
                    <dd className="font-mono">
                      {(s.buy_lock_volume_ratio * 100).toFixed(4)}%
                    </dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-slate-500 shrink-0">总市值</dt>
                    <dd className="font-mono">{num(s.total_capital)}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-slate-500 shrink-0">流通市值</dt>
                    <dd className="font-mono">{num(s.non_restricted_capital)}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-slate-500 shrink-0">炸板次数</dt>
                    <dd className="font-mono">{s.break_limit_up_times}</dd>
                  </div>
                </dl>
              </div>
              <div className="md:col-span-2">
                <div className="text-xs text-slate-500 uppercase mb-2">
                  封板时间线
                </div>
                <PoolTimeline items={s.limit_timeline?.items ?? []} />
              </div>
            </div>
            {s.surge_reason?.stock_reason && (
              <div className="mt-3 p-2 rounded bg-slate-900 border border-slate-800 text-xs text-slate-300 leading-relaxed">
                <span className="text-slate-500 mr-1">涨停原因：</span>
                {s.surge_reason.stock_reason}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}