import { useStore } from '../store';
import { Wifi, WifiOff, Loader } from 'lucide-react';
import clsx from 'clsx';
import type { WsStatus } from '../types';

const META: Record<
  WsStatus,
  { icon: typeof Wifi; color: string; label: string; dot: string }
> = {
  open: {
    icon: Wifi,
    color: 'text-emerald-400',
    label: '实时连接',
    dot: 'bg-emerald-400',
  },
  connecting: {
    icon: Loader,
    color: 'text-blue-400',
    label: '连接中',
    dot: 'bg-blue-400 animate-pulse',
  },
  closed: {
    icon: WifiOff,
    color: 'text-rose-400',
    label: '已断开',
    dot: 'bg-rose-400',
  },
};

export function ConnectionStatus() {
  const status = useStore((s) => s.status);
  const config = META[status as WsStatus];
  const Icon = config.icon;
  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-slate-800/50">
      <div className={clsx('w-2 h-2 rounded-full', config.dot)} />
      <Icon size={14} className={config.color} />
      <span className={clsx('text-xs', config.color)}>{config.label}</span>
    </div>
  );
}