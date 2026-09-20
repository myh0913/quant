import { useState, useEffect } from 'react';
import clsx from 'clsx';
import {
  Lightbulb,
  Clock,
  Target,
  ShieldAlert,
  ChevronDown,
  ChevronRight,
  Thermometer,
  Zap,
  Layers,
  Snowflake,
  CalendarDays,
  TrendingUp,
} from 'lucide-react';
import { useStore } from '../store';
import { EmptyState } from '../components/EmptyState';
import { IntradayTimeline } from '../components/IntradayTimeline';
import { CYCLE_STYLES } from '../lib/cycle';
import { api } from '../lib/api';
import { Activity } from 'lucide-react';
import type {
  AdviceItem,
  AdviceReport,
  CycleReport,
  DailyReport,
  IntradayEntry,
  IntradayPlanReport,
  PoolCandidate,
  PoolReport,
  ReviewReport,
  TailpanPoolReport,
} from '../types';
import { reportKind, entryStrategy } from '../types';
import { num } from '../lib/format';

const SCENE_LABELS: Record<string, string> = {
  A: '大幅低开直接参与',
  B: '低开待盘中确认',
  C: '高开待盘中确认',
  D: '大幅低开直接参与',
  E: '低开待承接横盘',
  F: '高开低走待横盘',
};

function isoTime(iso: string | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '—' : d.toTimeString().slice(0, 8);
}

function reportTitle(r: DailyReport): string {
  switch (reportKind(r)) {
    case 'auction':
      return (r as AdviceReport).strategy;
    case 'intraday':
      return `盘中 · ${entryStrategy(r as IntradayEntry)}`;
    case 'lianban_pool':
      return '盘后建池 · 连板捉妖（明日候选）';
    case 'dragon_pool':
      return '盘后建池 · 龙回头（明日候选）';
    case 'tailpan_pool':
      return '尾盘选股 · 龙回头（当日尾盘候选）';
    case 'cycle':
      return '盘后 · 情绪周期判定';
    case 'review':
      return `复盘 · ${(r as ReviewReport).advice_date} 建议表现`;
    default:
      return '报告';
  }
}

/** 一条操作建议 */
function AdviceRow({ a }: { a: AdviceItem }) {
  const isBuy = a.action.includes('买入');
  const demoted = a.demoted === true;
  return (
    <div className={clsx('bg-slate-950 border rounded-lg p-4', demoted ? 'border-slate-700 opacity-75' : 'border-slate-800')}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <span className={demoted ? 'text-slate-400 font-bold' : 'text-red-400 font-bold'}>{a.name}</span>
          <span className="text-xs text-slate-500 font-mono">{a.thscode}</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          {a.reference_price != null && (
            <span className="text-slate-400">
              参考价 <span className="text-slate-200 font-mono">{a.reference_price.toFixed(2)}</span>
            </span>
          )}
          {a.position_pct != null && (
            <span className={demoted ? 'text-slate-500' : 'text-amber-300 font-mono'}>
              仓位 {a.position_pct > 0 ? `${(a.position_pct * 100).toFixed(0)}%` : '观察'}
            </span>
          )}
          <span
            className={`px-2 py-0.5 rounded border ${
              demoted
                ? 'text-slate-400 bg-slate-800 border-slate-600'
                : isBuy
                  ? 'text-red-300 bg-red-500/10 border-red-500/30'
                  : 'text-slate-400 bg-slate-800 border-slate-700'
            }`}
          >
            {demoted ? '观察不下单' : a.action}
          </span>
        </div>
      </div>
      {demoted && a.portfolio_note && (
        <div className="text-[11px] text-slate-500 mt-2">组合风控：{a.portfolio_note}</div>
      )}
      {a.trigger_condition && (
        <div className="text-xs text-slate-500 mt-2">触发：{a.trigger_condition}</div>
      )}
      {a.reasons.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {a.reasons.map((r, i) => (
            <span
              key={i}
              className="text-[11px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-300"
            >
              {r}
            </span>
          ))}
        </div>
      )}
      {a.pending_confirmations.length > 0 && (
        <div className="text-[11px] text-amber-400/80 mt-2">
          待确认：{a.pending_confirmations.join('；')}
        </div>
      )}
      <div className="text-[10px] text-slate-600 mt-2">
        有效期：{a.valid_until || '—'}
        {a.position && ` · 仓位：${a.position}`}
        {a.stop_loss && ` · 止损：${a.stop_loss}`}
      </div>
    </div>
  );
}

/** 候选池条目行 */
function CandidateRow({ c }: { c: PoolCandidate }) {
  const ratio = c.volume_ratio ?? c.pb_volume_ratio;
  return (
    <div className="flex items-center gap-2 text-xs py-1.5 border-b border-slate-800/50 last:border-0">
      <span className="text-slate-300 font-medium w-24 shrink-0">{c.name}</span>
      <span className="text-slate-600 font-mono">{c.thscode}</span>
      <span className="text-slate-500">{c.boards} 连板</span>
      {c.shape && <span className="text-slate-500">{c.shape}</span>}
      {ratio != null && (
        <span className="text-slate-500 font-mono">量比 {ratio.toFixed(2)}x</span>
      )}
      {c.structure_notes?.map((n, i) => (
        <span key={`sn${i}`} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
          {n}
        </span>
      ))}
      {c.notes?.map((n, i) => (
        <span key={`n${i}`} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
          {n}
        </span>
      ))}
    </div>
  );
}

/** 盘后候选池报告卡 */
function PoolCard({ r, flash }: { r: PoolReport; flash: boolean }) {
  const isLianban = r.type === 'lianban_pool';
  return (
    <div
      className={`bg-slate-900 border rounded-lg p-4 ${
        flash ? 'border-blue-500/60' : 'border-slate-800'
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <Layers size={15} className={isLianban ? 'text-orange-300' : 'text-violet-300'} />
        <span className="text-sm font-medium text-slate-200">{reportTitle(r)}</span>
        <span className="text-xs text-slate-500">
          通过 {r.candidates.length} · 拒 {r.rejected.length} · 服务 {r.date} 次日开盘
        </span>
      </div>
      {r.candidates.length > 0 ? (
        <div className="mt-2">
          {r.candidates.map((c) => (
            <CandidateRow key={c.thscode} c={c} />
          ))}
        </div>
      ) : (
        <div className="text-xs text-slate-500 mt-2">本轮无通过候选</div>
      )}
      {r.rejected.length > 0 && (
        <details className="mt-2">
          <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-400">
            被拒候选 {r.rejected.length}（展开）
          </summary>
          <div className="mt-1">
            {r.rejected.map((c) => (
              <div key={c.thscode} className="flex items-center gap-2 text-xs py-1 border-b border-slate-800/30 last:border-0">
                <span className="text-slate-500 w-24 shrink-0">{c.name}</span>
                <span className="text-slate-600 font-mono">{c.thscode}</span>
                <span className="text-rose-400/70 text-[11px]">{c.reject_reason}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

/** 尾盘选股卡（14:45 龙回头·尾盘当日候选） */
function pctText(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${v > 0 ? '+' : ''}${(v * 100).toFixed(2)}%`;
}

function pctCls(v: number | null | undefined): string {
  if (v == null) return 'text-slate-400';
  return v > 0 ? 'text-red-400' : v < 0 ? 'text-emerald-400' : 'text-slate-300';
}

function TailpanCard({ r, flash }: { r: TailpanPoolReport; flash: boolean }) {
  return (
    <div
      className={`bg-slate-900 border rounded-lg p-4 ${
        flash ? 'border-blue-500/60' : 'border-slate-800'
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <Layers size={15} className="text-amber-300" />
        <span className="text-sm font-medium text-slate-200">{reportTitle(r)}</span>
        <span className="text-xs text-slate-500">
          通过 {r.candidates.length} · 拒 {r.rejected.length} · 14:45 选出，服务当日尾盘
        </span>
        {r.gate_note && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded border ${r.candidates.length === 0 && r.gate_state !== '' && r.rejected.length === 0 ? 'text-rose-300 bg-rose-500/10 border-rose-500/30' : 'text-slate-400 bg-slate-800 border-slate-700'}`}>
            周期 {r.gate_state} · {r.gate_note}
          </span>
        )}
      </div>
      <div className="text-[11px] text-slate-600 mt-1">
        规则：T-1 ≥2 连板波 + 现价 &lt; 今开 + 排除三板组；
        A 高开 ≥3%：未冲高 + 9:33前低 ≤-2% + 9:33后振幅 ≤3% + 量 ≤1.5x；
        B 低开 ≤-2%：量 &lt;0.8x + 全天振幅 ≤3%；
        C 平开(-2%~3%)：量 &lt;1.0x + 未冲高 + 9:33 ≤-2% + 振幅 ≤3%
      </div>
      {r.candidates.length > 0 ? (
        <div className="mt-2">
          {r.candidates.map((c) => (
            <div
              key={c.thscode}
              className="flex items-center gap-2 text-xs py-1.5 border-b border-slate-800/50 last:border-0 flex-wrap"
            >
              <span className="text-red-400 font-bold w-24 shrink-0">{c.name}</span>
              <span className="text-slate-600 font-mono">{c.thscode}</span>
              <span className="text-slate-500">{c.boards} 连板</span>
              {c.scene && (
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded border ${
                    c.scene === 'A'
                      ? 'text-amber-300 bg-amber-500/10 border-amber-500/30'
                      : c.scene === 'B'
                        ? 'text-sky-300 bg-sky-500/10 border-sky-500/30'
                        : 'text-violet-300 bg-violet-500/10 border-violet-500/30'
                  }`}
                >
                  {c.scene === 'A' ? 'A 高开回踩' : c.scene === 'B' ? 'B 低开收敛' : 'C 平开低走'}
                </span>
              )}
              <span className="font-mono">
                开盘 <span className={pctCls(c.open_pct)}>{pctText(c.open_pct)}</span>
              </span>
              {c.scene === 'B' ? (
                <span className="font-mono">
                  全天振幅 <span className="text-slate-300">{pctText(c.range_pct)}</span>
                </span>
              ) : (
                <>
                  {c.scene === 'C' && c.pct_933 != null ? (
                    <span className="font-mono">
                      9:33价 <span className={pctCls(c.pct_933)}>{pctText(c.pct_933)}</span>
                    </span>
                  ) : (
                    <span className="font-mono">
                      9:33低 <span className={pctCls(c.morning_low_pct)}>{pctText(c.morning_low_pct)}</span>
                    </span>
                  )}
                  {c.range_pct != null && (
                    <span className="font-mono">
                      9:33后振幅 <span className="text-slate-300">{pctText(c.range_pct)}</span>
                    </span>
                  )}
                </>
              )}
              {c.volume_ratio != null && (
                <span className="font-mono">
                  量比 <span className="text-slate-300">{c.volume_ratio.toFixed(2)}x</span>
                </span>
              )}
              <span className="font-mono">
                现价{' '}
                <span className={pctCls(c.last_pct)}>{pctText(c.last_pct)}</span>
                {c.last_price != null && (
                  <span className="text-slate-500 ml-1">{c.last_price.toFixed(2)}</span>
                )}
              </span>
              {c.notes?.map((n, i) => (
                <span key={`n${i}`} className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                  {n}
                </span>
              ))}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-slate-500 mt-2">本轮无通过候选</div>
      )}
      {r.rejected.length > 0 && (
        <details className="mt-2">
          <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-400">
            被拒候选 {r.rejected.length}（展开）
          </summary>
          <div className="mt-1">
            {r.rejected.map((c) => (
              <div key={c.thscode} className="flex items-center gap-2 text-xs py-1 border-b border-slate-800/30 last:border-0">
                <span className="text-slate-500 w-24 shrink-0">{c.name}</span>
                <span className="text-slate-600 font-mono">{c.thscode}</span>
                <span className="text-rose-400/70 text-[11px]">{c.reject_reason}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

/** 盘后周期判定卡 */
function CycleCard({ r, flash }: { r: CycleReport; flash: boolean }) {
  const cls = CYCLE_STYLES[r.state] ?? 'text-slate-300 bg-slate-800 border-slate-700';
  const ind = r.indicators;
  return (
    <div
      className={`bg-slate-900 border rounded-lg p-4 ${
        flash ? 'border-blue-500/60' : 'border-slate-800'
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <Snowflake size={15} className="text-sky-300" />
        <span className="text-sm font-medium text-slate-200">{reportTitle(r)}</span>
        <span className={`text-xs px-2 py-0.5 rounded border ${cls}`}>
          {r.state}
          {r.overheated && ' · 过热减半'}
        </span>
        {r.data_degraded && (
          <span className="text-xs px-2 py-0.5 rounded border text-amber-300 bg-amber-500/10 border-amber-500/30">
            ⚠️ 数据降级（指标缺失，判定可信度低）
          </span>
        )}
      </div>
      <div className="text-xs text-slate-500 mt-2">{r.reasons.join('；')}</div>
      <div className="flex flex-wrap gap-3 mt-2 text-xs text-slate-400">
        <span>温度 <span className="text-slate-200 font-mono">{ind.temperature}</span></span>
        <span>涨停 <span className="text-red-300 font-mono">{ind.limit_up}</span></span>
        <span>跌停 <span className="text-emerald-300 font-mono">{ind.limit_down}</span></span>
        <span>炸板率 <span className="text-slate-200 font-mono">{(ind.break_ratio * 100).toFixed(1)}%</span></span>
        <span>晋级率 <span className="text-slate-200 font-mono">{(ind.promotion * 100).toFixed(1)}%</span></span>
        <span>高度 <span className="text-slate-200 font-mono">{ind.height}板</span></span>
      </div>
    </div>
  );
}

/** 复盘卡：上一交易日建议的次日表现（详情见复盘页） */
function ReviewCard({ r, flash }: { r: ReviewReport; flash: boolean }) {
  return (
    <div
      className={`bg-slate-900 border rounded-lg p-4 ${
        flash ? 'border-blue-500/60' : 'border-slate-800'
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <TrendingUp size={15} className="text-emerald-300" />
        <span className="text-sm font-medium text-slate-200">{reportTitle(r)}</span>
        <span className="text-xs text-slate-500">{r.total} 条 · 核算于 {r.date}</span>
      </div>
      <div className="flex flex-wrap gap-3 mt-2 text-xs">
        {Object.entries(r.by_strategy).map(([strat, agg]) => (
          <span key={strat} className="px-2 py-1 rounded bg-slate-800/60 border border-slate-700 text-slate-300">
            {strat}：{agg.count} 条 · 胜率{' '}
            <span className={agg.win_rate != null && agg.win_rate >= 0.5 ? 'text-red-300' : 'text-emerald-300'}>
              {agg.win_rate != null ? `${(agg.win_rate * 100).toFixed(0)}%` : '—'}
            </span>
            {agg.win_rate_close != null && (
              <span className="text-slate-500">
                {' / '}
                <span className={agg.win_rate_close >= 0.5 ? 'text-red-300' : 'text-emerald-300'}>
                  收盘 {(agg.win_rate_close * 100).toFixed(0)}%
                </span>
              </span>
            )}
            {agg.avg_next_high_pct != null && (
              <span className={agg.avg_next_high_pct > 0 ? 'text-red-300' : 'text-emerald-300'}>
                {' '}
                均冲高 {agg.avg_next_high_pct > 0 ? '+' : ''}
                {(agg.avg_next_high_pct * 100).toFixed(2)}%
              </span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

/** 盘中即时建议 / 触发事件卡 */
/** 盘中计划（待确认候选）：场景已建立、等待盘中触发确认 */
function PendingCard({ r, flash }: { r: IntradayPlanReport; flash: boolean }) {
  const pending = r.pending ?? [];
  const cc = r.cycle_check;
  return (
    <div className={`bg-slate-900 border rounded-lg p-4 ${flash ? 'border-blue-500/60' : 'border-slate-800'}`}>
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-slate-200">⏳ 今日待确认候选</span>
        <span className="text-xs text-slate-500">{pending.length} 只 · 场景已建立，等待盘中触发条件</span>
        {cc?.state && (
          <span className={`text-[11px] px-1.5 py-0.5 rounded border ${cc.degraded ? 'text-amber-300 bg-amber-500/10 border-amber-500/30' : 'text-slate-400 bg-slate-800 border-slate-700'}`}>
            周期复核 {cc.state}{cc.degraded ? '（数据降级）' : ''}
          </span>
        )}
        {cc?.vetoed?.map((v) => (
          <span key={v} className="text-[11px] px-1.5 py-0.5 rounded border text-rose-300 bg-rose-500/10 border-rose-500/30">
            {v} 当日周期否决
          </span>
        ))}
      </div>
      {pending.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {pending.map((p2, i) => (
            <span key={i} className="text-xs px-2 py-1 rounded bg-amber-500/10 border border-amber-500/30 text-amber-300">
              {p2.name} · 场景{p2.scene}
            </span>
          ))}
        </div>
      )}
      <div className="mt-2 text-[11px] text-slate-600">触发条件满足后会实时推送到“盘中”时间线</div>
    </div>
  );
}

function IntradayCard({ r, flash }: { r: IntradayEntry; flash: boolean }) {
  const isTriggered = !!r.result && ('triggered' in r.result || 'confirmed' in r.result);
  const sceneLabel = SCENE_LABELS[r.scene] ?? r.scene;
  const price = r.result?.trigger_price ?? r.result?.confirm_price;
  const time = r.result?.trigger_time ?? r.result?.confirm_time ?? r.triggered_at;
  return (
    <div
      className={`bg-slate-900 border rounded-lg p-4 ${
        flash ? 'border-blue-500/60' : 'border-slate-800'
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-xs font-bold px-2 py-0.5 rounded bg-red-500/25 border border-red-400/60 text-red-200">
          🎯 操作建议
        </span>
        <Zap size={15} className="text-amber-300" />
        <span className="text-sm font-medium text-slate-200">
          {r.name}
          <span className="text-slate-600 font-mono ml-1.5 text-xs">{r.thscode}</span>
        </span>
        <span className="text-xs px-2 py-0.5 rounded border text-red-300 bg-red-500/10 border-red-500/30">
          {entryStrategy(r)} · 场景{r.scene}
        </span>
        {r.demoted === true ? (
          <span className="text-xs px-2 py-0.5 rounded border text-slate-400 bg-slate-800 border-slate-600">
            观察不下单
          </span>
        ) : r.position_pct != null && r.position_pct > 0 && (
          <span className="text-xs text-amber-300 font-mono">仓位 {(r.position_pct * 100).toFixed(0)}%</span>
        )}
        <span className="text-xs text-slate-500">{sceneLabel}</span>
        {time && (
          <span className="text-xs text-slate-500 font-mono">
            {isTriggered ? isoTime(r.triggered_at) : isoTime(r.ran_at)}
          </span>
        )}
      </div>
      <div className="text-xs text-slate-400 mt-2">{r.detail}</div>
      {r.result?.detail && <div className="text-xs text-slate-500 mt-1">{r.result.detail}</div>}
      {(price != null || r.result?.minute_pct != null || r.result?.volume_ratio != null) && (
        <div className="flex flex-wrap gap-3 mt-2 text-xs text-slate-400">
          {price != null && (
            <span>价格 <span className="text-slate-200 font-mono">{price.toFixed(2)}</span></span>
          )}
          {r.result?.minute_pct != null && (
            <span>
              分钟涨幅{' '}
              <span className={r.result.minute_pct > 0 ? 'text-red-400 font-mono' : 'text-emerald-400 font-mono'}>
                {(r.result.minute_pct * 100).toFixed(2)}%
              </span>
            </span>
          )}
          {r.result?.volume_ratio != null && (
            <span>
              量比 <span className="text-slate-200 font-mono">{r.result.volume_ratio.toFixed(2)}x</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** 竞价抢筹报告卡（可展开候选明细） */
function AuctionCard({
  report,
  expanded,
  onToggle,
  flash,
}: {
  report: AdviceReport;
  expanded: boolean;
  onToggle: () => void;
  flash: boolean;
}) {
  const cycleCls = CYCLE_STYLES[report.cycle_state] ?? 'text-slate-300 bg-slate-800 border-slate-700';
  return (
    <div
      className={`bg-slate-900 border rounded-lg transition-colors ${
        flash ? 'border-blue-500/60' : 'border-slate-800'
      }`}
    >
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span className="text-xs text-slate-500 font-mono w-20 shrink-0">
          {isoTime(report.ran_at)}
        </span>
        <span className="text-sm font-medium text-slate-200">{report.strategy}</span>
        <span className={`text-xs px-2 py-0.5 rounded border ${cycleCls}`}>
          周期 · {report.cycle_state}
        </span>
        <span className="text-xs text-slate-500">
          候选 {report.candidates} · 建议 {report.advices.length}
          {report.blocked.length > 0 && ` · 拦截 ${report.blocked.length}`}
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-800 pt-3">
          <div className="flex items-start gap-2 text-xs text-slate-500">
            <Thermometer size={14} className="mt-0.5 shrink-0" />
            <div>
              <span className="text-slate-300">{report.cycle_state}</span>
              <span className="mx-1">·</span>
              仓位因子 {report.cycle_position_factor}
              <div className="mt-0.5">{report.cycle_reasons.join('；')}</div>
            </div>
          </div>

          {report.advices.length > 0 && (
            <div className="space-y-2">
              {report.advices.map((a, i) => (
                <AdviceRow key={`${a.thscode}-${i}`} a={a} />
              ))}
            </div>
          )}
          {report.blocked.map((a, i) => (
            // blocked 是拦截记录 {thscode,name,reasons}，非完整 Advice（无 action 等字段），
            // 不能走 AdviceRow（2026-09-15 实测：blocked>0 时 undefined.includes 整页白屏）
            <div
              key={`${a.thscode}-${i}`}
              className="bg-slate-950 border border-rose-500/30 rounded-lg p-3"
            >
              <div className="flex items-center gap-2 text-xs">
                <ShieldAlert size={13} className="text-rose-300 shrink-0" />
                <span className="text-rose-200 font-medium">{a.name}</span>
                <span className="text-slate-500 font-mono">{a.thscode}</span>
                <span className="text-rose-300/80">已拦截</span>
              </div>
              {(a.reasons ?? []).map((reason, j) => (
                <div key={j} className="text-[11px] text-slate-500 mt-1">
                  {reason}
                </div>
              ))}
            </div>
          ))}
          {report.advices.length === 0 && report.blocked.length === 0 && (
            <div className="text-xs text-slate-500">本轮无操作建议（全部候选被拒或环境不满足）</div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 border-b border-slate-800">
                  <th className="text-left py-1.5 pr-3 font-medium">#</th>
                  <th className="text-left py-1.5 pr-3 font-medium">股票</th>
                  <th className="text-right py-1.5 pr-3 font-medium">竞价额</th>
                  <th className="text-right py-1.5 pr-3 font-medium">9:20</th>
                  <th className="text-right py-1.5 pr-3 font-medium">9:25</th>
                  <th className="text-right py-1.5 pr-3 font-medium" title="9:25 相对 9:20 的拉升幅度">拉升</th>
                  <th className="text-right py-1.5 pr-3 font-medium" title="9:25 相对昨收">vs昨收</th>
                  <th className="text-left py-1.5 font-medium">判定</th>
                </tr>
              </thead>
              <tbody>
                {report.factors.map((f) => {
                  const r = report.results[f.thscode];
                  return (
                    <tr key={f.thscode} className="border-b border-slate-800/50">
                      <td className="py-1.5 pr-3 text-slate-500">{f.rank}</td>
                      <td className="py-1.5 pr-3">
                        <span className="text-slate-300">{f.name}</span>
                        <span className="text-slate-600 font-mono ml-1.5">{f.thscode}</span>
                      </td>
                      <td className="py-1.5 pr-3 text-right text-slate-400 font-mono">
                        {num(f.auction_amount_yuan)}
                      </td>
                      <td className="py-1.5 pr-3 text-right text-slate-400 font-mono">
                        {f.p920?.toFixed(2) ?? '—'}
                      </td>
                      <td className="py-1.5 pr-3 text-right text-slate-400 font-mono">
                        {f.p925?.toFixed(2) ?? '—'}
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono">
                        {f.rise_920_925 != null ? (
                          <span className={f.rise_920_925 > 0 ? 'text-red-400' : 'text-emerald-400'}>
                            {f.rise_920_925 > 0 ? '+' : ''}{(f.rise_920_925 * 100).toFixed(2)}%
                          </span>
                        ) : '—'}
                      </td>
                      <td className="py-1.5 pr-3 text-right font-mono">
                        {f.chg_925 != null ? (
                          <span className={f.chg_925 > 0 ? 'text-red-400' : 'text-emerald-400'}>
                            {f.chg_925 > 0 ? '+' : ''}{(f.chg_925 * 100).toFixed(2)}%
                          </span>
                        ) : '—'}
                      </td>
                      <td className="py-1.5">
                        {r?.signal ? (
                          <span className="text-red-300">✓ 信号</span>
                        ) : (
                          <span className="text-slate-500" title={r?.rejected.join('；')}>
                            ✗ {r?.rejected[0] ?? '未触发'}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function ReportItem({
  r,
  expanded,
  onToggle,
  flash,
}: {
  r: DailyReport;
  expanded: boolean;
  onToggle: () => void;
  flash: boolean;
}) {
  switch (reportKind(r)) {
    case 'auction':
      return (
        <AuctionCard
          report={r as AdviceReport}
          expanded={expanded}
          onToggle={onToggle}
          flash={flash}
        />
      );
    case 'intraday':
      return <IntradayCard r={r as IntradayEntry} flash={flash} />;
    case 'intraday_plan':
      return <PendingCard r={r as IntradayPlanReport} flash={flash} />;
    case 'lianban_pool':
    case 'dragon_pool':
      return <PoolCard r={r as PoolReport} flash={flash} />;
    case 'tailpan_pool':
      return <TailpanCard r={r as TailpanPoolReport} flash={flash} />;
    case 'cycle':
      return <CycleCard r={r as CycleReport} flash={flash} />;
    case 'review':
      return <ReviewCard r={r as ReviewReport} flash={flash} />;
  }
}

function todayStr(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate()
  ).padStart(2, '0')}`;
}

function yesterdayStr(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate()
  ).padStart(2, '0')}`;
}

export function Jianyi() {
  const advices = useStore((s) => s.advices);
  const flash = useStore((s) => s.flash);
  const me = useStore((s) => s.me);
  // 普通用户：看不到实时建议（后端也不推送/不返回当日），强制历史模式
  const historyOnly = me?.role === 'user';

  // 历史查看：默认今天走 WS 实时；选其他日期走 REST /api/advice?date=
  const [date, setDate] = useState(historyOnly ? yesterdayStr() : todayStr());
  const [hist, setHist] = useState<DailyReport[] | null>(null);
  const [histLoading, setHistLoading] = useState(false);
  const isToday = !historyOnly && date === todayStr();

  useEffect(() => {
    if (isToday) {
      setHist(null);
      return;
    }
    setHistLoading(true);
    api
      .advices('/api', date)
      .then((r) => setHist(r.items as DailyReport[]))
      .catch(() => setHist([]))
      .finally(() => setHistLoading(false));
  }, [date, isToday]);

  const reports = isToday ? advices : (hist ?? []);

  // 默认展开最新一轮竞价报告（仅当天模式）
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const auctionReports = reports.filter((r) => reportKind(r) === 'auction') as AdviceReport[];
  const intradayEntries = reports.filter((r) => reportKind(r) === 'intraday') as IntradayEntry[];
  const planReports = reports.filter((r) => reportKind(r) === 'intraday_plan') as IntradayPlanReport[];
  const postmarketReports = reports.filter((r) =>
    ['lianban_pool', 'dragon_pool', 'cycle', 'review'].includes(reportKind(r))
  );
  const tailpanReports = reports.filter((r) => reportKind(r) === 'tailpan_pool') as TailpanPoolReport[];
  const latestAuction = auctionReports[auctionReports.length - 1];
  const latest = reports[reports.length - 1];
  const expanded = expandedKey ?? latestAuction?.file ?? null;

  // 四 Tab：盘中（触发时间线）/ 竞价（策略一报告）/ 尾盘（尾盘选股）/ 盘后（周期+候选池）；默认盘中（用户确认）
  const [pageTab, setPageTab] = useState<'intraday' | 'auction' | 'tailpan' | 'postmarket'>('intraday');

  return (
    <div className="p-6 space-y-6 flex-1 min-h-0 overflow-y-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">
            {isToday ? '量化选股' : '选股历史'}
          </h1>
          {isToday && flash.advices && (
            <span className="ml-2 text-blue-400 text-xs">· 已推送最新</span>
          )}
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-400">
          <CalendarDays size={15} />
          <input
            type="date"
            value={date}
            max={historyOnly ? yesterdayStr() : todayStr()}
            onChange={(e) => setDate(e.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-md px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-slate-600 [color-scheme:dark]"
          />
        </label>
      </div>

      {histLoading ? (
        <EmptyState icon={<Lightbulb size={28} className="text-slate-600" />} title="加载中…" hint={`正在拉取 ${date} 的报告`} />
      ) : reports.length === 0 ? (
        <EmptyState
          icon={<Lightbulb size={28} className="text-slate-600" />}
          title={isToday ? '今日暂无报告' : `${date} 无报告`}
          hint={
            isToday
              ? '调度器在 9:25 竞价 / 盘中轮询 / 14:45 尾盘 / 17:00 盘后产出报告后，会实时推送到这里'
              : '该日调度器未产出报告（非交易日或任务未运行）'
          }
        />
      ) : (
        <>
          <div className="text-sm text-slate-500">
            {date} · 共 {reports.length} 份报告
          </div>

          {/* 四 Tab：竞价 / 盘中 / 尾盘 / 盘后（按交易日时间轴排序）；默认盘中（用户确认） */}
          <div className="flex gap-1 border-b border-slate-800">
            {([['auction', `竞价 (${auctionReports.length})`], ['intraday', `盘中 (${intradayEntries.length})`], ['tailpan', `尾盘 (${tailpanReports.length})`], ['postmarket', `盘后 (${postmarketReports.length})`]] as const).map(
              ([id, label]) => (
                <button
                  key={id}
                  onClick={() => setPageTab(id)}
                  className={clsx(
                    'px-4 py-2 text-sm whitespace-nowrap transition-colors border-b-2',
                    pageTab === id
                      ? 'text-blue-300 border-blue-400'
                      : 'text-slate-400 border-transparent hover:text-slate-200'
                  )}
                >
                  {label}
                </button>
              )
            )}
          </div>

          {pageTab === 'auction' && (
            <div className="space-y-2">
              {auctionReports.map((r) => {
                const key = ('file' in r && r.file) || '';
                return (
                  <ReportItem
                    key={key}
                    r={r}
                    expanded={expanded === key}
                    onToggle={() => setExpandedKey(expanded === key ? '' : key)}
                    flash={isToday && !!flash.advices && !!key && key === ('file' in latest ? latest.file : '')}
                  />
                );
              })}
            </div>
          )}

          {pageTab === 'tailpan' && (
            <div className="space-y-2">
              {tailpanReports.map((r) => {
                const key = r.file ?? r.ran_at ?? '';
                return (
                  <TailpanCard
                    key={key}
                    r={r}
                    flash={isToday && !!flash.advices && !!key && key === ('file' in latest ? latest.file : '')}
                  />
                );
              })}
              {tailpanReports.length === 0 && (
                <EmptyState
                  icon={<Activity size={28} className="text-slate-600" />}
                  title="暂无尾盘选股"
                  hint="交易日 14:45 调度器产出龙回头·尾盘候选后实时推送到这里"
                />
              )}
            </div>
          )}

          {pageTab === 'postmarket' && (
            <div className="space-y-2">
              {[...reports].reverse().map((r) => {
                const kind = reportKind(r);
                // 盘后 tab 只放周期判定与候选池；intraday_plan（待确认候选）属盘中语境，尾盘选股单列 tab
                if (kind === 'intraday' || kind === 'auction' || kind === 'intraday_plan' || kind === 'tailpan_pool') return null;
                const key = ('file' in r && r.file) || (r as { ran_at?: string }).ran_at || '';
                return (
                  <ReportItem
                    key={key}
                    r={r}
                    expanded={expanded === key}
                    onToggle={() => setExpandedKey(expanded === key ? '' : key)}
                    flash={isToday && !!flash.advices && !!key && key === ('file' in latest ? latest.file : '')}
                  />
                );
              })}
            </div>
          )}

          {pageTab === 'intraday' && (
            <div className="space-y-2">
              {planReports.map((r) => (
                <PendingCard key={r.file ?? r.ran_at} r={r} flash={false} />
              ))}
              {intradayEntries.length > 0 ? (
                <IntradayTimeline entries={intradayEntries} />
              ) : (
                <EmptyState
                  icon={<Activity size={28} className="text-slate-600" />}
                  title="今日盘中无触发"
                  hint="候选在 9:30-10:00 满足放量上攻/承接横盘条件时会实时推送"
                />
              )}
            </div>
          )}
        </>
      )}

      <div className="flex items-center gap-4 text-[11px] text-slate-600">
        <span className="flex items-center gap-1">
          <Clock size={12} /> 时间为策略运行时间
        </span>
        <span className="flex items-center gap-1">
          <Target size={12} /> 只生成建议，不自动交易
        </span>
        <span className="flex items-center gap-1">
          <ShieldAlert size={12} /> 情绪周期退潮/冰点时策略自动零建议
        </span>
      </div>
    </div>
  );
}
