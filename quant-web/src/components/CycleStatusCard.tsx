import { Link } from 'react-router-dom';
import { Thermometer, ChevronRight } from 'lucide-react';
import { CYCLE_STYLES, factorLabel, type CycleInfo } from '../lib/cycle';

/**
 * 情绪周期状态卡（总览页顶部）
 * 当前周期六态 + 判定依据 + 仓位门控因子——所有策略的总开关
 */
export function CycleStatusCard({ info }: { info: CycleInfo | null }) {
  if (!info) return null;
  const cls = CYCLE_STYLES[info.state] ?? 'text-slate-300 bg-slate-800 border-slate-700';
  const fl = factorLabel(info.positionFactor);
  const ind = info.indicators;
  const srcLabel =
    info.source === 'auction'
      ? `竞价判定 ${info.ranAt ? new Date(info.ranAt).toTimeString().slice(0, 5) : ''}`
      : `盘后判定 ${info.ranAt ? new Date(info.ranAt).toTimeString().slice(0, 5) : ''}`;

  return (
    <Link
      to="/advice"
      className={`block bg-slate-900 border rounded-lg p-4 transition-colors hover:border-slate-700 ${
        info.overheated ? 'border-rose-500/40' : 'border-slate-800'
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <Thermometer size={15} className="text-slate-400" />
        <span className="text-sm font-medium text-slate-200">情绪周期</span>
        <span className={`text-xs px-2 py-0.5 rounded border ${cls}`}>
          {info.state}
          {info.overheated && ' · 过热减半'}
        </span>
        {fl && (
          <span
            className={`text-xs px-2 py-0.5 rounded border ${
              info.positionFactor != null && info.positionFactor <= 0
                ? 'text-rose-300 bg-rose-500/10 border-rose-500/30'
                : 'text-slate-300 bg-slate-800 border-slate-700'
            }`}
          >
            仓位因子 {info.positionFactor != null ? info.positionFactor : '—'} · {fl}
          </span>
        )}
        <span className="text-xs text-slate-500">{srcLabel}</span>
        <ChevronRight size={15} className="ml-auto text-slate-500" />
      </div>
      <div className="text-xs text-slate-500 mt-2">{info.reasons.join('；')}</div>
      {ind && (
        <div className="flex flex-wrap gap-3 mt-2 text-xs text-slate-400">
          <span>温度 <span className="text-slate-200 font-mono">{ind.temperature.toFixed(1)}</span></span>
          <span>涨停 <span className="text-red-300 font-mono">{ind.limit_up}</span></span>
          <span>跌停 <span className="text-emerald-300 font-mono">{ind.limit_down}</span></span>
          <span>炸板率 <span className="text-slate-200 font-mono">{(ind.break_ratio * 100).toFixed(1)}%</span></span>
          <span>晋级率 <span className="text-slate-200 font-mono">{(ind.promotion * 100).toFixed(1)}%</span></span>
          <span>高度 <span className="text-slate-200 font-mono">{ind.height}板</span></span>
          {ind.leader && <span>龙头 <span className="text-slate-200">{ind.leader}</span></span>}
        </div>
      )}
    </Link>
  );
}
