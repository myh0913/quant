import type { LimitTimelineItem } from '../types';
import clsx from 'clsx';
import { timeSec } from '../lib/format';

/**
 * 涨停时间线（status: 1封涨停 2炸板 3封跌停 4开跌停）
 * 横轴固定 9:25 → 15:00（连续轴，午休 11:30-13:00 以淡虚线标出），
 * 事件名称与时间按发生顺序以列表展示在时间线下方。
 * timestamp 均为 Unix **秒**。
 */

/** 固定轴边界：09:25:00 与 15:00:00（本地时区秒数） */
function daySeconds(ts: number): number {
  const d = new Date(ts * 1000);
  return d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
}

const AXIS_START = 9 * 3600 + 25 * 60; // 09:25:00
const AXIS_END = 15 * 3600; // 15:00:00
const AXIS_SPAN = AXIS_END - AXIS_START;
const LUNCH_START = 11 * 3600 + 30 * 60; // 11:30:00
const LUNCH_END = 13 * 3600; // 13:00:00

export function PoolTimeline({ items }: { items: LimitTimelineItem[] }) {
  if (!items.length) {
    return (
      <div className="text-xs text-slate-500 py-4 text-center">
        暂无封板时间线数据
      </div>
    );
  }

  // 固定轴位置（不随事件自适应）
  const pos = (ts: number) => {
    const t = daySeconds(ts);
    return (Math.min(AXIS_END, Math.max(AXIS_START, t)) - AXIS_START) / AXIS_SPAN * 100;
  };

  // 刻度：9:25 起每 75 分钟
  const ticks = [AXIS_START, 10.5 * 3600, LUNCH_START, LUNCH_END, 14 * 3600, AXIS_END];
  const tickLabel = (s: number) =>
    `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`;

  const sorted = [...items].sort((a, b) => a.timestamp - b.timestamp);

  return (
    <div className="space-y-2">
      {/* 固定 9:25-15:00 时间轴 */}
      <div>
        <div className="relative h-10 bg-slate-900 rounded border border-slate-800 overflow-hidden">
          {/* 中轴线 */}
          <div className="absolute inset-x-0 top-1/2 h-px bg-slate-700" />
          {/* 午休区间（11:30-13:00）淡色阴影 + 边界虚线 */}
          <div
            className="absolute top-0 bottom-0 bg-slate-800/40 border-x border-dashed border-slate-700"
            style={{
              left: `${((LUNCH_START - AXIS_START) / AXIS_SPAN) * 100}%`,
              width: `${((LUNCH_END - LUNCH_START) / AXIS_SPAN) * 100}%`,
            }}
            title="午间休市"
          />
          {/* 事件点 */}
          {sorted.map((it, i) => {
            const isBroken = it.status === 2 || it.status === 4;
            const isDown = it.status === 3 || it.status === 4;
            return (
              <div
                key={i}
                className={clsx(
                  'absolute w-2 h-2 rounded-full -translate-x-1/2 -translate-y-1/2 top-1/2',
                  isDown
                    ? isBroken
                      ? 'bg-rose-400 ring-2 ring-rose-400/30'
                      : 'bg-rose-500'
                    : isBroken
                      ? 'bg-amber-400 ring-2 ring-amber-400/30'
                      : 'bg-emerald-400 ring-2 ring-emerald-400/30'
                )}
                style={{ left: `${pos(it.timestamp)}%` }}
                title={`${timeSec(it.timestamp)} ${label(it.status)}`}
              />
            );
          })}
        </div>
        {/* 轴刻度 */}
        <div className="relative h-4 mt-0.5">
          {ticks.map((t) => (
            <span
              key={t}
              className="absolute -translate-x-1/2 text-[10px] font-mono text-slate-500"
              style={{ left: `${((t - AXIS_START) / AXIS_SPAN) * 100}%` }}
            >
              {tickLabel(t)}
            </span>
          ))}
        </div>
      </div>

      {/* 事件列表（时间线正下方，按时间排序） */}
      {sorted.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {sorted.map((it, i) => {
            const isBroken = it.status === 2 || it.status === 4;
            const isDown = it.status === 3 || it.status === 4;
            return (
              <span
                key={i}
                className={clsx(
                  'flex items-center gap-1.5',
                  isDown ? 'text-rose-300' : isBroken ? 'text-amber-300' : 'text-emerald-300'
                )}
              >
                <span
                  className={clsx(
                    'w-1.5 h-1.5 rounded-full',
                    isDown
                      ? isBroken
                        ? 'bg-rose-400'
                        : 'bg-rose-500'
                      : isBroken
                        ? 'bg-amber-400'
                        : 'bg-emerald-400'
                  )}
                />
                <span className="font-medium">{label(it.status)}</span>
                <span className="font-mono text-slate-400">{timeSec(it.timestamp)}</span>
              </span>
            );
          })}
          <span className="ml-auto font-mono text-slate-500">{items.length} 个事件</span>
        </div>
      )}
    </div>
  );
}

function label(s: number): string {
  return ['', '封涨停', '炸板', '封跌停', '开跌停'][s] ?? '未知';
}
