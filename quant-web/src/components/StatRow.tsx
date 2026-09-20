import clsx from 'clsx';

interface Stat {
  label: string;
  value: string | number;
  tone?: 'default' | 'up' | 'down' | 'warn' | 'info';
  hint?: string;
}

interface Props {
  stats: Stat[];
}

const toneClass: Record<NonNullable<Stat['tone']>, string> = {
  default: 'text-slate-100',
  up: 'up',
  down: 'down',
  warn: 'text-amber-400',
  info: 'text-blue-400',
};

export function StatRow({ stats }: Props) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
      {stats.map((s) => (
        <div
          key={s.label}
          className="bg-slate-900 border border-slate-800 rounded-lg px-4 py-3"
        >
          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">
            {s.label}
          </div>
          <div className={clsx('text-2xl font-semibold tabular-nums', toneClass[s.tone ?? 'default'])}>
            {s.value}
          </div>
          {/* hint 行占位：保证各卡片内容高度一致（如"炸板"有炸板率副行） */}
          <div className="text-xs text-slate-500 mt-0.5 h-4 leading-4">{s.hint ?? ''}</div>
        </div>
      ))}
    </div>
  );
}