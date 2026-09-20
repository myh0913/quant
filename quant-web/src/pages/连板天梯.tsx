/**
 * 连板天梯：Excel 式列布局回看每日 >=2 连板股票。
 * 横向往右 = 日期递增；每列内个股按当天连板数降序、同板数按首封时间升序，
 * 紧挨着往下排（不做跨日期行对齐）。单元格 = 股票名称 + 当天连板数。
 * hover / 单击高亮同一只票在所有列的单元格；再点一次取消固定高亮。
 * 日期范围：默认近 30 个交易日（跟随 WS），可选任意区间，跨度上限一年（后端强制）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Flame, MousePointerClick, Download, Search } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../lib/api';
import type { LadderData } from '../types';
import clsx from 'clsx';

/** 连板数 → 文字颜色（板数越高越暖） */
function boardColor(n: number): string {
  if (n >= 5) return 'text-amber-300';
  if (n === 4) return 'text-violet-300';
  if (n === 3) return 'text-sky-300';
  return 'text-slate-200';
}

interface DayCell {
  symbol: string;
  name: string;
  boards: number;
  first_limit_up: number;
}

const fmtDate = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

const daysAgo = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return fmtDate(d);
};

const todayStr = () => fmtDate(new Date());

/** 跨度（天） */
const spanDays = (s: string, e: string) =>
  (new Date(`${e}T00:00:00`).getTime() - new Date(`${s}T00:00:00`).getTime()) / 86400000;

export function LadderPage() {
  const wsLadder = useStore((s) => s.ladder);
  // view = 当前展示数据；custom = null 表示默认近30个交易日（跟随 WS 推送）
  const [view, setView] = useState<LadderData | null>(null);
  const [custom, setCustom] = useState<{ start: string; end: string } | null>(null);
  const [startD, setStartD] = useState('');
  const [endD, setEndD] = useState('');
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // 数据/日期变化后自动滚动到最右（最新日期）
  useEffect(() => {
    if (scrollRef.current && view && (view.days?.length ?? 0) > 0) {
      scrollRef.current.scrollLeft = scrollRef.current.scrollWidth;
    }
  }, [view, startD, endD]);

  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!custom && wsLadder) setView(wsLadder);
  }, [wsLadder, custom]);

  const fetchRange = useCallback(async (start: string, end: string) => {
    setBusy(true);
    setErr(null);
    try {
      const data = await api.ladder('/api', { start, end });
      setCustom({ start, end });
      setView(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const backToDefault = () => {
    setCustom(null);
    setErr(null);
    if (wsLadder) setView(wsLadder);
  };

  /** 预设按钮：填入日期并立即查询 */
  const applyDates = (s: string, e: string) => {
    setStartD(s);
    setEndD(e);
    void fetchRange(s, e);
  };

  /** 日期输入变更：只更新输入框，点「查询」才发请求 */
  const onDateChange = (which: 'start' | 'end', v: string) => {
    if (which === 'start') setStartD(v);
    else setEndD(v);
  };

  /** 点查询：纠正起止顺序、截断超一年跨度后发请求 */
  const handleQuery = () => {
    let s = startD;
    let e = endD;
    if (!s || !e) return;
    if (s > e) {
      [s, e] = [e, s];
      setStartD(s);
      setEndD(e);
    }
    if (spanDays(s, e) > 366) {
      const ed = new Date(`${e}T00:00:00`);
      ed.setDate(ed.getDate() - 366);
      s = fmtDate(ed);
      setStartD(s);
    }
    void fetchRange(s, e);
  };

  /** 每个交易日一列：列内按当天连板数降序 → 首封时间升序 */
  const perDay = useMemo(() => {
    const map: Record<string, DayCell[]> = {};
    if (!view) return map;
    for (const d of view.days) map[d] = [];
    for (const r of view.rows) {
      for (const [d, c] of Object.entries(r.cells)) {
        if (map[d]) {
          map[d].push({
            symbol: r.symbol,
            name: r.name,
            boards: c.boards,
            first_limit_up: c.first_limit_up ?? 0,
          });
        }
      }
    }
    for (const d of Object.keys(map)) {
      map[d].sort((a, b) => b.boards - a.boards || a.first_limit_up - b.first_limit_up);
    }
    return map;
  }, [view]);

  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<Set<string>>(new Set());

  const togglePin = (sym: string) =>
    setPinned((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });

  /** 按当前展示的日期范围导出 .xlsx：表头=日期，列内顺序与页面一致 */
  const exportExcel = async () => {
    if (!view || rows.length === 0) return;
    const XLSX = await import('xlsx');
    const maxLen = Math.max(...days.map((d) => (perDay[d] ?? []).length), 1);
    const aoa: string[][] = [
      [...days],
      ...Array.from({ length: maxLen }, (_, i) =>
        days.map((d) => {
          const c = (perDay[d] ?? [])[i];
          return c ? `${c.name} ${c.boards}板` : '';
        })
      ),
    ];
    const ws = XLSX.utils.aoa_to_sheet(aoa);
    ws['!cols'] = days.map(() => ({ wch: 12 }));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, '连板天梯');
    XLSX.writeFile(wb, `连板天梯_${days[0]}_${days[days.length - 1]}.xlsx`);
  };

  if (!view) {
    return (
      <div className="h-full flex items-center justify-center text-slate-500 text-sm">
        连板天梯加载中…
      </div>
    );
  }

  const { days, rows } = view;

  const presets: { label: string; run: () => void; active: boolean }[] = [
    { label: '近30交易日', run: backToDefault, active: !custom },
    {
      label: '近60天',
      run: () => applyDates(daysAgo(59), todayStr()),
      active: custom?.start === daysAgo(59),
    },
    {
      label: '近120天',
      run: () => applyDates(daysAgo(119), todayStr()),
      active: custom?.start === daysAgo(119),
    },
    {
      label: '今年以来',
      run: () => applyDates(`${new Date().getFullYear()}-01-01`, todayStr()),
      active: custom?.start === `${new Date().getFullYear()}-01-01`,
    },
    {
      label: '近一年',
      run: () => applyDates(daysAgo(365), todayStr()),
      active: custom?.start === daysAgo(365),
    },
  ];

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="px-6 pt-5 pb-2 flex items-baseline gap-3 shrink-0">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Flame size={18} className="text-orange-400" />
          连板天梯
        </h1>
        <span className="text-xs text-slate-500">
          {days.length} 个交易日 · {rows.length} 只 ≥2 连板 · 列内按当天连板数降序，同板数按首封时间
        </span>
        <span className="ml-auto text-xs text-slate-500 flex items-center gap-1">
          <MousePointerClick size={13} />
          悬停高亮同一只票 · 点击固定，再点取消
        </span>
      </div>

      {/* 日期范围选择器 */}
      <div className="px-6 pb-2 flex items-center gap-2 text-xs shrink-0 flex-wrap">
        {presets.map((p) => (
          <button
            key={p.label}
            onClick={p.run}
            className={clsx(
              'px-2 py-1 rounded border',
              p.active
                ? 'bg-sky-600 border-sky-500 text-white'
                : 'bg-slate-900 border-slate-700 text-slate-300 hover:bg-slate-800'
            )}
          >
            {p.label}
          </button>
        ))}
        <span className="text-slate-500 mx-1">|</span>
        <span className="text-slate-400">自定义</span>
        <input
          type="date"
          value={startD}
          max={endD || undefined}
          onChange={(e) => onDateChange('start', e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
          className="bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-slate-200 [color-scheme:dark]"
        />
        <span className="text-slate-500">至</span>
        <input
          type="date"
          value={endD}
          min={startD || undefined}
          max={todayStr()}
          onChange={(e) => onDateChange('end', e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
          className="bg-slate-900 border border-slate-700 rounded px-1.5 py-1 text-slate-200 [color-scheme:dark]"
        />
        <button
          onClick={handleQuery}
          disabled={!startD || !endD || busy}
          className="flex items-center gap-1 px-3 py-1 rounded bg-sky-600 text-white hover:bg-sky-500 disabled:opacity-40 disabled:hover:bg-sky-600"
        >
          <Search size={13} />
          查询
        </button>
        {busy && <span className="text-sky-400 animate-pulse">加载中…</span>}
        {err && <span className="text-rose-400">加载失败：{err}</span>}
        <button
          onClick={() => void exportExcel()}
          disabled={!rows.length || busy}
          className="ml-auto flex items-center gap-1 px-2 py-1 rounded border bg-slate-900 border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:hover:bg-slate-900"
        >
          <Download size={13} />
          导出Excel
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-slate-500 text-sm">
          该区间内暂无 ≥2 连板数据
        </div>
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-auto px-6 pb-6">
          <div className="flex min-w-max items-start">
            {days.map((d) => {
              const cells = perDay[d] ?? [];
              return (
                <div
                  key={d}
                  className="min-w-[9rem] max-w-[11rem] border border-slate-600 -mr-px bg-slate-950/40"
                >
                  <div className="sticky top-0 z-10 bg-slate-800 border-b border-slate-600 px-2 py-1.5 text-xs text-slate-200 font-medium text-center">
                    {d.slice(5).replace('-', '/')}
                    <span className="text-[10px] text-slate-400 ml-1">{cells.length}</span>
                  </div>
                  {cells.map((c) => {
                    const isPinned = pinned.has(c.symbol);
                    const active = isPinned || hovered === c.symbol;
                    return (
                      <div
                        key={c.symbol}
                        onMouseEnter={() => setHovered(c.symbol)}
                        onMouseLeave={() => setHovered((h) => (h === c.symbol ? null : h))}
                        onClick={() => togglePin(c.symbol)}
                        className={clsx(
                          'px-2 py-1 text-xs whitespace-nowrap cursor-pointer select-none border-b border-slate-700/70',
                          active
                            ? isPinned
                              ? 'bg-amber-400/45'
                              : 'bg-amber-400/25'
                            : 'hover:bg-slate-800/50'
                        )}
                      >
                        <span className={boardColor(c.boards)}>
                          {c.name} <span className="font-bold">{c.boards}板</span>
                        </span>
                      </div>
                    );
                  })}
                  {cells.length === 0 && (
                    <div className="px-2 py-1 text-[11px] text-slate-600 text-center border-b border-slate-700/70">
                      —
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
