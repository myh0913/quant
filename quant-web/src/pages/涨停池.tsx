import { useState } from 'react';
import { useStore } from '../store';
import { PoolTabs } from '../components/PoolTabs';
import { PoolTable } from '../components/PoolTable';
import type { PoolName } from '../types';
import { POOL_LABELS } from '../types';
import { EmptyState } from '../components/EmptyState';
import { Filter } from 'lucide-react';

export function Zhangtingchi() {
  const pools = useStore((s) => s.pools);
  const flash = useStore((s) => s.flash);
  const [active, setActive] = useState<PoolName>('limit_up');
  const [boardFilter, setBoardFilter] = useState<number | null>(null);

  const pool = pools[active];

  const counts = (Object.keys(pools) as PoolName[]).reduce(
    (acc, k) => {
      acc[k] = pools[k]?.items.length ?? 0;
      return acc;
    },
    {} as Partial<Record<PoolName, number>>
  );

  const filteredItems =
    pool && boardFilter !== null
      ? {
          ...pool,
          items: pool.items.filter((s) => s.limit_up_days >= boardFilter),
        }
      : pool;

  return (
    <div className="p-6 space-y-4 flex-1 min-h-0 overflow-y-auto">
      <div>
        <h1 className="text-2xl font-bold">涨停池</h1>
      </div>

      <PoolTabs active={active} onChange={setActive} counts={counts} />

      <div className="flex items-center gap-3 text-sm">
        <Filter size={14} className="text-slate-500" />
        <span className="text-slate-500 text-xs">连板筛选：</span>
        {[null, 1, 2, 3, 5].map((b) => (
          <button
            key={b ?? 'all'}
            onClick={() => setBoardFilter(b)}
            className={`px-2 py-0.5 rounded text-xs transition-colors ${
              boardFilter === b
                ? 'bg-blue-600/20 text-blue-300 border border-blue-500/30'
                : 'bg-slate-800 text-slate-400 border border-slate-700 hover:border-slate-600'
            }`}
          >
            {b === null ? '全部' : `${b}+ 板`}
          </button>
        ))}
        {pool && boardFilter !== null && (
          <span className="text-xs text-slate-500 ml-2">
            筛选后 {filteredItems?.items.length ?? 0} / {pool.items.length} 只
          </span>
        )}
      </div>

      {filteredItems ? (
        <PoolTable pool={filteredItems} flash={!!flash[`pool:${active}`]} />
      ) : (
        <EmptyState
          title={`等待${POOL_LABELS[active]}数据…`}
          hint="后端启动后会自动填充"
        />
      )}
    </div>
  );
}