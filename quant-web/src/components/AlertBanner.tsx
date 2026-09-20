/**
 * 全局告警横幅：上游接口故障（超时/报错）/ 量化引擎任务失败。
 * 数据来自 WS alert 广播（后端同源 5 分钟节流），每条可手动关闭，60s 无操作自动消失。
 */
import { useEffect } from 'react';
import { AlertTriangle, Clock, X } from 'lucide-react';
import { useStore } from '../store';

const AUTO_DISMISS_MS = 60_000;

/** 故障来源 → 展示名 */
function sourceLabel(source: string): string {
  if (source.startsWith('engine:')) {
    const task = source.slice(7);
    const names: Record<string, string> = {
      auction: '竞价任务',
      intraday: '盘中监控',
      postmarket: '盘后建池',
    };
    return `量化引擎·${names[task] ?? task}`;
  }
  if (source.startsWith('pool:')) return `行情接口·${source.slice(5)}`;
  const names: Record<string, string> = {
    sentiment: '情绪接口',
    sentiment_history: '情绪历史接口',
    newsflash: '快讯接口',
    themes: '主题接口',
    monitor: '监管名单接口',
  };
  return names[source] ?? source;
}

function AlertRow({ ts, source, message }: { ts: number; source: string; message: string }) {
  const dismissAlert = useStore((s) => s.dismissAlert);

  useEffect(() => {
    const t = setTimeout(() => dismissAlert(ts), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [ts, dismissAlert]);

  return (
    <div className="flex items-start gap-2.5 bg-amber-500/10 border border-amber-500/40 text-amber-200 rounded-md px-3 py-2 text-xs">
      <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-400" />
      <div className="min-w-0 flex-1">
        <span className="font-semibold">{sourceLabel(source)}</span>
        <span className="text-amber-200/70">：{message || '接口异常'}</span>
      </div>
      <button
        onClick={() => dismissAlert(ts)}
        className="shrink-0 p-0.5 rounded text-amber-300/60 hover:text-amber-100 hover:bg-amber-500/20 transition-colors"
        title="关闭"
      >
        <X size={13} />
      </button>
    </div>
  );
}

export function AlertBanner() {
  const alerts = useStore((s) => s.alerts);
  const staleKeys = useStore((s) => s.staleKeys);

  const staleLabels = Object.values(staleKeys);

  return (
    <div className="sticky top-0 z-40 px-4 pt-3 space-y-2">
      {/* stale 提示：上游限频/失败时数据为缓存快照（轻量、持续显示直到恢复新鲜） */}
      {staleLabels.length > 0 && (
        <div className="flex items-center gap-2.5 bg-sky-500/10 border border-sky-500/40 text-sky-200 rounded-md px-3 py-2 text-xs">
          <Clock size={14} className="shrink-0 text-sky-400" />
          <span>
            <span className="font-semibold">{staleLabels.join('、')}</span>
            <span className="text-sky-200/70">
              ：当前为缓存数据（上游限流），正常后自动恢复
            </span>
          </span>
        </div>
      )}
      {alerts.map((a) => (
        <AlertRow key={a.ts} ts={a.ts} source={a.source} message={a.message} />
      ))}
    </div>
  );
}
