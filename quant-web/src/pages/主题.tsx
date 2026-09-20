import { useState, useMemo, useEffect } from 'react';
import type { Theme } from '../types';
import { useStore } from '../store';
import { ThemeCard } from '../components/ThemeCard';
import { ThemeDetail } from '../components/ThemeDetail';
import { EmptyState } from '../components/EmptyState';
import { api } from '../lib/api';
import { Compass, History, RotateCcw } from 'lucide-react';

const TODAY = '今天';

export function Zhuti() {
  const themes = useStore((s) => s.themes);
  const flash = useStore((s) => s.flash);
  const [activeId, setActiveId] = useState<number | null>(null);

  // 历史对比：'' = 今天；其它 = /api/themes/history/<date> 的快照
  const [viewDate, setViewDate] = useState<string>(TODAY);
  const [dates, setDates] = useState<string[]>([]);
  const [hist, setHist] = useState<Theme[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    api.themeDates('/api').then(setDates).catch(() => setDates([]));
  }, [flash.themes]);

  useEffect(() => {
    if (viewDate === TODAY) {
      setHist(null);
      setErr('');
      return;
    }
    let alive = true;
    setLoading(true);
    setErr('');
    api
      .themeHistory('/api', viewDate)
      .then((d) => {
        if (alive) setHist(d);
      })
      .catch((e) => {
        if (alive) {
          setHist(null);
          setErr(e instanceof Error ? e.message : '加载失败');
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [viewDate]);

  const isHistory = viewDate !== TODAY;
  const shown = isHistory ? (hist ?? []) : themes;
  const todayIds = useMemo(() => new Set(themes.map((t) => t.id)), [themes]);

  const active = useMemo(
    () => shown.find((t) => t.id === activeId) ?? shown[0] ?? null,
    [shown, activeId]
  );

  return (
    <div className="p-6 space-y-4 flex-1 min-h-0 overflow-y-auto">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          主题机会
          {isHistory && (
            <span className="text-xs font-normal px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
              历史快照 {viewDate.slice(5)}
            </span>
          )}
        </h1>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <History size={14} />
          <select
            value={viewDate}
            onChange={(e) => setViewDate(e.target.value)}
            className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-blue-500"
          >
            <option value={TODAY}>今天（实时）</option>
            {dates.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          {isHistory && (
            <button
              onClick={() => setViewDate(TODAY)}
              className="flex items-center gap-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300"
            >
              <RotateCcw size={12} /> 返回今天
            </button>
          )}
        </label>
      </div>

      {loading && <div className="text-sm text-slate-400">加载历史快照…</div>}
      {err && <div className="text-sm text-red-400">历史快照加载失败：{err}</div>}

      {shown.length === 0 && !loading ? (
        <EmptyState
          title={isHistory ? '该日无快照' : '暂无主题'}
          hint={isHistory ? '此日期没有保存的主题数据（仅保留最近 7 天）' : '等待主题数据推送…'}
          icon={<Compass size={32} />}
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <aside className="lg:col-span-1 space-y-2 max-h-[80vh] overflow-y-auto pr-2">
            <div className="text-xs text-slate-500 mb-2">
              {shown.length} 个主题 · {isHistory ? '历史快照' : '点击查看详情'}
            </div>
            {shown.map((t) => (
              <ThemeCard
                key={t.id}
                theme={t}
                active={t.id === active?.id}
                onClick={() => setActiveId(t.id)}
                badge={
                  isHistory && todayIds.has(t.id) ? (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 whitespace-nowrap">
                      今日仍在榜
                    </span>
                  ) : undefined
                }
              />
            ))}
          </aside>
          <main className="lg:col-span-2">
            <ThemeDetail theme={active} />
          </main>
        </div>
      )}
    </div>
  );
}
