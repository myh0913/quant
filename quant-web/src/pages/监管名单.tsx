import { useMemo, useState } from 'react';
import { ShieldAlert, Search } from 'lucide-react';
import { useStore } from '../store';
import { EmptyState } from '../components/EmptyState';
import type { MonitorStock } from '../types';
import clsx from 'clsx';

/**
 * 监管名单页：东财重点监控证券（最新名单）+ 严重异常波动（最近 50 条公告）
 * 数据由后端 /api/monitor 拉取，WS monitor 频道定时广播（后端 5min 缓存）
 */

type Tab = 'restricted' | 'severe';

const TABS: { id: Tab; name: string; desc: string }[] = [
  { id: 'restricted', name: '重点监控', desc: '交易所重点监控证券（最新名单）' },
  { id: 'severe', name: '严重异动', desc: '严重异常波动（按公告日倒序，最近 50 条）' },
];

const MARKET_LABEL: Record<string, string> = { '1': '沪', '0': '深', B: '北' };

const dateStr = (s?: string) => (s ? s.slice(0, 10) : '—');

function RestrictedTable({ items }: { items: MonitorStock[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-slate-500 border-b border-slate-800">
          <th className="text-left py-2 pr-3 font-normal">股票</th>
          <th className="text-left py-2 pr-3 font-normal">代码</th>
          <th className="text-left py-2 pr-3 font-normal">市场</th>
          <th className="text-left py-2 pr-3 font-normal">监控起始</th>
          <th className="text-left py-2 font-normal">监控结束</th>
        </tr>
      </thead>
      <tbody>
        {items.map((s) => (
          <tr key={s.code} className="border-b border-slate-900 hover:bg-slate-900/60">
            <td className="py-2 pr-3 font-medium text-red-400">{s.name}</td>
            <td className="py-2 pr-3 font-mono text-xs text-slate-400">{s.thscode || s.code}</td>
            <td className="py-2 pr-3">
              <span className="text-xs px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                {(MARKET_LABEL[s.market ?? ''] ?? s.market) || '—'}
              </span>
            </td>
            <td className="py-2 pr-3 font-mono text-xs text-slate-400">{dateStr(s.start_date)}</td>
            <td className="py-2 font-mono text-xs text-slate-400">{dateStr(s.end_date)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function SevereTable({ items }: { items: MonitorStock[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-slate-500 border-b border-slate-800">
          <th className="text-left py-2 pr-3 font-normal">股票</th>
          <th className="text-left py-2 pr-3 font-normal">代码</th>
          <th className="text-left py-2 pr-3 font-normal">公告日</th>
          <th className="text-left py-2 pr-3 font-normal">异动区间</th>
          <th className="text-left py-2 font-normal">异动原因</th>
        </tr>
      </thead>
      <tbody>
        {items.map((s, i) => (
          <tr key={`${s.code}-${i}`} className="border-b border-slate-900 hover:bg-slate-900/60">
            <td className="py-2 pr-3 font-medium text-red-400 whitespace-nowrap">{s.name}</td>
            <td className="py-2 pr-3 font-mono text-xs text-slate-400">{s.thscode || s.code}</td>
            <td className="py-2 pr-3 font-mono text-xs text-slate-400 whitespace-nowrap">
              {dateStr(s.notice_date)}
            </td>
            <td className="py-2 pr-3 font-mono text-xs text-slate-500 whitespace-nowrap">
              {dateStr(s.start_date)} ~ {dateStr(s.end_date)}
            </td>
            <td className="py-2 text-xs text-slate-400">{s.reason || '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Jianguan() {
  const monitor = useStore((s) => s.monitor);
  const [tab, setTab] = useState<Tab>('restricted');
  const [q, setQ] = useState('');

  const items = useMemo(() => {
    const list = monitor?.[tab] ?? [];
    const kw = q.trim().toLowerCase();
    if (!kw) return list;
    return list.filter(
      (s) =>
        s.name.toLowerCase().includes(kw) ||
        s.code.includes(kw) ||
        s.thscode.toLowerCase().includes(kw)
    );
  }, [monitor, tab, q]);

  const data = tab === 'restricted' ? monitor?.restricted : monitor?.severe;

  return (
    <div className="p-6 space-y-4 flex-1 min-h-0 overflow-y-auto">
      <div className="flex items-center gap-2 flex-wrap">
        <ShieldAlert size={20} className="text-amber-300" />
        <h1 className="text-2xl font-bold">监管名单</h1>
        {monitor?.errors && monitor.errors.length > 0 && (
          <span className="text-xs text-rose-400">
            部分接口异常：{monitor.errors.join('；')}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              'px-3 py-1.5 rounded-md text-sm transition-colors border',
              tab === t.id
                ? 'bg-blue-600/20 text-blue-300 border-blue-500/30'
                : 'text-slate-400 hover:text-slate-200 border-transparent bg-slate-900'
            )}
          >
            {t.name}
            <span className="text-xs text-slate-500 ml-1">
              {(t.id === 'restricted' ? monitor?.restricted.length : monitor?.severe.length) ?? 0}
            </span>
          </button>
        ))}
        <div className="relative ml-auto">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索名称 / 代码"
            className="bg-slate-900 border border-slate-800 rounded-md pl-8 pr-3 py-1.5 text-sm w-52 focus:outline-none focus:border-slate-600"
          />
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
        {!monitor ? (
          <EmptyState icon={<ShieldAlert size={28} />} title="等待数据" hint="连接建立后自动加载监管名单" />
        ) : !data || data.length === 0 ? (
          <EmptyState icon={<ShieldAlert size={28} />} title="暂无数据" hint="接口暂未返回名单" />
        ) : items.length === 0 ? (
          <EmptyState icon={<Search size={28} />} title="无匹配结果" hint={`没有匹配「${q}」的条目`} />
        ) : (
          <>
            <div className="text-xs text-slate-500 mb-2">
              {TABS.find((t) => t.id === tab)?.desc} · {items.length} 条
            </div>
            {tab === 'restricted' ? (
              <RestrictedTable items={items} />
            ) : (
              <SevereTable items={items} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
