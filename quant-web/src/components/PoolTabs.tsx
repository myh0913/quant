import type { PoolName } from '../types';
import { POOL_LABELS } from '../types';
import clsx from 'clsx';

const ORDER: PoolName[] = [
  'limit_up',
  'limit_up_broken',
  'yesterday_limit_up',
  'super_stock',
  'limit_down',
  'new_stock',
  'nearly_new',
];

interface Props {
  active: PoolName;
  onChange: (n: PoolName) => void;
  counts?: Partial<Record<PoolName, number>>;
}

export function PoolTabs({ active, onChange, counts }: Props) {
  return (
    <div className="flex items-center gap-1 border-b border-slate-800 overflow-x-auto">
      {ORDER.map((name) => {
        const isActive = name === active;
        const count = counts?.[name];
        return (
          <button
            key={name}
            onClick={() => onChange(name)}
            className={clsx(
              'px-3 py-2 text-sm whitespace-nowrap transition-colors border-b-2',
              isActive
                ? 'text-blue-300 border-blue-400'
                : 'text-slate-400 border-transparent hover:text-slate-200'
            )}
          >
            {POOL_LABELS[name]}
            {typeof count === 'number' && (
              <span
                className={clsx(
                  'ml-2 px-1.5 py-0.5 text-[10px] rounded font-mono',
                  isActive
                    ? 'bg-blue-500/20 text-blue-300'
                    : 'bg-slate-800 text-slate-500'
                )}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}