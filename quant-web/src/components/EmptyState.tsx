import type { ReactNode } from 'react';

export function EmptyState({
  title,
  hint,
  icon,
}: {
  title: string;
  hint?: string;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-500 bg-slate-900 border border-slate-800 rounded-lg">
      {icon}
      <div className="text-sm mt-2">{title}</div>
      {hint && <div className="text-xs mt-1 text-slate-600">{hint}</div>}
    </div>
  );
}