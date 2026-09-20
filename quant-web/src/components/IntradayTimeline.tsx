import { Activity } from 'lucide-react';
import type { IntradayEntry } from '../types';
import { entryStrategy } from '../types';

/**
 * 盘中触发时间线（今日建议页）
 *
 * 渲染策略二/三的分钟级触发点：
 * - 场景 A/D 即时建议：9:25 竞价即可定论（无 result）
 * - 场景 B/C 触发：result.triggered（trigger_time / trigger_price / minute_pct / volume_ratio）
 * - 场景 E/F 确认：result.confirmed（confirm_time / confirm_price）
 * 时间轴按事件时间升序，每个事件一行。
 */

interface TlEvent {
  key: string;
  /** 展示用时间 HH:MM */
  time: string;
  sortKey: string;
  kind: 'immediate' | 'trigger' | 'confirm' | 'expired';
  entry: IntradayEntry;
}

// 用户确认 2026-09-14：三种标签统一为「建议买入」（都是可操作的买入建议）；
// expired = 观察窗口已过未触发的归因记录（2026-09-17），中性灰展示，非建议
const EVENT_BADGES: Record<TlEvent['kind'], { label: string; cls: string }> = {
  immediate: { label: '建议买入', cls: 'text-red-200 bg-red-500/25 border-red-400/60 font-bold' },
  trigger: { label: '建议买入', cls: 'text-red-200 bg-red-500/25 border-red-400/60 font-bold' },
  confirm: { label: '建议买入', cls: 'text-red-200 bg-red-500/25 border-red-400/60 font-bold' },
  expired: { label: '窗口过期未触发', cls: 'text-slate-400 bg-slate-800 border-slate-600' },
};

function isoClock(iso: string | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : d.toTimeString().slice(0, 5);
}

function eventOf(e: IntradayEntry, i: number): TlEvent {
  const r = e.result;
  let kind: TlEvent['kind'] = 'immediate';
  let time = '';
  if (r?.window_expired && !r.triggered && !r.confirmed) {
    kind = 'expired';
    time = isoClock(e.triggered_at ?? e.ran_at);
  } else if (r?.triggered) {
    kind = 'trigger';
    time = r.trigger_time || isoClock(e.triggered_at ?? e.ran_at);
  } else if (r?.confirmed) {
    kind = 'confirm';
    time = r.confirm_time || isoClock(e.triggered_at ?? e.ran_at);
  } else {
    time = isoClock(e.ran_at) || isoClock(e.triggered_at);
  }
  return {
    key: ('file' in e && e.file) || `${e.thscode}-${i}`,
    time: time || '—',
    sortKey: time || '99:99',
    kind,
    entry: e,
  };
}

export function IntradayTimeline({ entries }: { entries: IntradayEntry[] }) {
  const events = entries
    .map(eventOf)
    .sort((a, b) => (a.sortKey > b.sortKey ? 1 : -1));
  if (events.length === 0) return null;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center gap-2">
        <Activity size={15} className="text-amber-300" />
        <span className="text-sm font-medium text-slate-200">盘中触发时间线</span>
        <span className="text-xs text-slate-500">{events.length} 个事件 · 按时间正序</span>
      </div>

      <div className="mt-3">
        {events.map((e, idx) => {
          const r = e.entry.result;
          const badge = EVENT_BADGES[e.kind];
          const price = r?.trigger_price ?? r?.confirm_price;
          return (
            <div key={e.key} className="flex gap-3 px-1">
              {/* 时间列 */}
              <div className="w-11 shrink-0 text-right font-mono text-xs text-slate-500 pt-0.5">
                {e.time}
              </div>
              {/* 轴线 + 节点 */}
              <div className="flex flex-col items-center">
                <span
                  className={`w-2 h-2 rounded-full mt-1 shrink-0 ${
                    e.kind === 'trigger'
                      ? 'bg-red-400'
                      : e.kind === 'confirm'
                        ? 'bg-amber-400'
                        : e.kind === 'expired'
                          ? 'bg-slate-600'
                          : 'bg-blue-400'
                  }`}
                />
                {idx < events.length - 1 && <span className="w-px flex-1 bg-slate-800" />}
              </div>
              {/* 内容 */}
              <div className={`flex-1 min-w-0 ${idx < events.length - 1 ? 'pb-4' : ''}`}>
                <div className="flex items-center gap-2 flex-wrap">
                  {e.kind === 'expired' ? (
                    <span className="text-xs font-bold px-2 py-0.5 rounded bg-slate-800 border border-slate-600 text-slate-400">
                      ⏹ 未触发
                    </span>
                  ) : (
                    <span className="text-xs font-bold px-2 py-0.5 rounded bg-red-500/25 border border-red-400/60 text-red-200">
                      🎯 操作建议
                    </span>
                  )}
                  <span className={`text-sm font-bold ${e.kind === 'expired' ? 'text-slate-400' : 'text-red-400'}`}>{e.entry.name}</span>
                  <span className="text-xs text-slate-600 font-mono">{e.entry.thscode}</span>
                  <span className="text-xs px-1.5 py-0.5 rounded border border-slate-700 bg-slate-800 text-slate-300">
                    {entryStrategy(e.entry)} · 场景{e.entry.scene}
                  </span>
                  <span className={`text-xs px-1.5 py-0.5 rounded border ${badge.cls}`}>
                    {badge.label}
                  </span>
                  {price != null && (
                    <span className="text-xs text-slate-400 font-mono">价 {price.toFixed(2)}</span>
                  )}
                  {r?.minute_pct != null && (
                    <span
                      className={`text-xs font-mono ${
                        r.minute_pct > 0 ? 'text-red-400' : 'text-emerald-400'
                      }`}
                    >
                      {r.minute_pct > 0 ? '+' : ''}
                      {(r.minute_pct * 100).toFixed(2)}%
                    </span>
                  )}
                  {r?.volume_ratio != null && (
                    <span className="text-xs text-slate-400 font-mono">
                      量比 {r.volume_ratio.toFixed(2)}x
                    </span>
                  )}
                </div>
                {e.entry.detail && (
                  <div className="text-xs text-slate-500 mt-1">{e.entry.detail}</div>
                )}
                {r?.detail && <div className="text-xs text-slate-600 mt-0.5">{r.detail}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
