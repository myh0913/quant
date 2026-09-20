import { useState, useMemo } from 'react';
import { useStore } from '../store';
import { NewsflashItemRow } from '../components/NewsflashItem';
import { EmptyState } from '../components/EmptyState';
import { Zap } from 'lucide-react';
import clsx from 'clsx';

const CATEGORIES = ['全部', '盘中异动', '要闻'] as const;

export function Kuaixun() {
  const newsflash = useStore((s) => s.newsflash);
  const flash = useStore((s) => s.flash);
  const [cat, setCat] = useState<(typeof CATEGORIES)[number]>('全部');
  const [keyword, setKeyword] = useState('');

  const filtered = useMemo(() => {
    let items = newsflash;
    if (cat !== '全部') {
      items = items.filter((n) => n.category === cat);
    }
    if (keyword.trim()) {
      const k = keyword.trim();
      items = items.filter(
        (n) =>
          n.title.includes(k) ||
          n.summary?.includes(k) ||
          n.stocks.some((s) => s.name.includes(k))
      );
    }
    return items;
  }, [newsflash, cat, keyword]);

  return (
    <div className="p-6 space-y-4 flex-1 min-h-0 overflow-y-auto">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-bold">7×24 快讯</h1>
        </div>
        <span className="text-xs text-slate-500 font-mono">
          {filtered.length} / {newsflash.length} 条
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCat(c)}
              className={clsx(
                'px-3 py-1.5 text-xs rounded-md transition-colors border',
                cat === c
                  ? 'bg-blue-600/20 text-blue-300 border-blue-500/30'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700'
              )}
            >
              {c}
            </button>
          ))}
        </div>
        <input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="搜索股票 / 关键词"
          className="flex-1 min-w-[200px] max-w-xs bg-slate-950 border border-slate-700 rounded-md px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
        />
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title="暂无快讯"
          hint={newsflash.length === 0 ? '等待数据推送…' : '没有符合条件的快讯'}
          icon={<Zap size={32} />}
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((n) => (
            <NewsflashItemRow key={n.id} item={n} flash={!!flash.newsflash} />
          ))}
        </div>
      )}
    </div>
  );
}