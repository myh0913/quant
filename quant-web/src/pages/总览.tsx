import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { TrendingUp } from 'lucide-react';
import clsx from 'clsx';
import { useStore } from '../store';
import { SentimentGauge } from '../components/SentimentGauge';
import { StatRow } from '../components/StatRow';
import { HistoryChart } from '../components/HistoryChart';
import { CycleStatusCard } from '../components/CycleStatusCard';
import { latestCycle } from '../lib/cycle';
import { pct } from '../lib/format';
import { api } from '../lib/api';
import type { ReviewReport } from '../types';

/** 昨日建议表现摘要卡：盘后复盘任务产出，点击进入复盘页看明细 */
function YesterdayReviewCard() {
  // undefined=加载中 null=无数据（均不占位，避免总览闪空块）
  const [rep, setRep] = useState<ReviewReport | null | undefined>(undefined);

  useEffect(() => {
    api
      .reviewHistory('/api', 1)
      .then((r) => setRep(r.items[0] ?? null))
      .catch(() => setRep(null));
  }, []);

  if (rep == null) return null;

  // 有效口径：竞价涨停买不进的不计胜负；盈亏按次日冲高（可卖出的卖点）
  const scored = rep.items.filter((it) => !it.unfillable && it.next_high_pct != null);
  const avg = scored.length
    ? scored.reduce((a, it) => a + (it.next_high_pct ?? 0), 0) / scored.length
    : null;

  return (
    <Link
      to="/review"
      className="block bg-slate-900 border border-slate-800 rounded-lg p-4 hover:border-slate-700 transition-colors"
    >
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <TrendingUp size={15} className="text-emerald-300 shrink-0" />
        <span className="text-sm font-medium text-slate-200">昨日建议表现</span>
        <span className="text-[11px] text-slate-500">
          {rep.advice_date} 的建议 · 次日冲高核算 · 点击查看明细
        </span>
        {/* 分策略胜率（胜率分母=可成交条数，买不进不计） */}
        <div className="ml-auto flex items-center gap-3 flex-wrap">
          {Object.entries(rep.by_strategy).map(([strat, agg]) => (
            <span key={strat} className="text-slate-400">
              {strat}{' '}
              <span
                className={clsx(
                  'font-medium',
                  agg.win_rate != null && agg.win_rate >= 0.5 ? 'text-red-300' : 'text-emerald-300'
                )}
              >
                {agg.win_rate != null ? pct(agg.win_rate, 0) : '—'}
              </span>
            </span>
          ))}
          <span className="text-slate-400">
            平均冲高{' '}
            <span className={clsx('font-medium', avg != null && avg > 0 ? 'text-red-300' : 'text-emerald-300')}>
              {avg != null ? pct(avg) : '—'}
            </span>
          </span>
        </div>
      </div>
    </Link>
  );
}

export function Gaishan() {
  const sentiment = useStore((s) => s.sentiment);
  const history = useStore((s) => s.history);
  const advices = useStore((s) => s.advices);
  const flash = useStore((s) => s.flash);
  const me = useStore((s) => s.me);
  const cycle = latestCycle(advices);
  // 普通用户：实时选股建议不可见（最新建议卡展示的是当天竞价报告）
  const canSeeAdvice = me?.role !== 'user';


  const stats = sentiment
    ? [
        { label: '涨停', value: sentiment.limit_up_count, tone: 'up' as const },
        { label: '跌停', value: sentiment.limit_down_count, tone: 'down' as const },
        {
          label: '炸板',
          value: sentiment.limit_up_broken_count,
          tone: 'warn' as const,
          hint: sentiment.limit_up_broken_ratio
            ? `炸板率 ${pct(sentiment.limit_up_broken_ratio, 0)}`
            : undefined,
        },
        { label: '上涨', value: sentiment.rise_count, tone: 'up' as const },
        { label: '下跌', value: sentiment.fall_count, tone: 'down' as const },
      ]
    : [];

  return (
    <div className="p-6 space-y-6 flex-1 min-h-0 overflow-y-auto">
      <div>
        <h1 className="text-2xl font-bold">总览</h1>
      </div>

      <CycleStatusCard info={cycle} />

      <YesterdayReviewCard />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <SentimentGauge sentiment={sentiment} flash={!!flash.sentiment} />
        {/* 右列：5 个统计小卡片 + 观察要点（补齐与左侧温度计卡的高度差） */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          <StatRow stats={stats} />
          {sentiment && (
            <div className="flex-1 bg-slate-900 border border-slate-800 rounded-lg p-5 text-xs text-slate-500 leading-relaxed">
              <div className="text-slate-300 mb-2 font-medium">观察要点</div>
              当前市场处于
              <span className="text-slate-200 mx-1">
                {sentiment.temperature >= 50 ? '偏热' : '偏冷'}
              </span>
              区间，
              {sentiment.limit_up_count >= 60
                ? '涨停扩散明显，赚钱效应强'
                : sentiment.limit_up_count >= 30
                  ? '涨停家数正常，情绪平稳'
                  : '涨停家数偏少，警惕情绪转弱'}
              。
              {sentiment.limit_up_broken_ratio >= 0.4 && (
                <span className="text-amber-400 ml-1">
                  炸板率 {pct(sentiment.limit_up_broken_ratio, 0)} 偏高，接力需谨慎。
                </span>
              )}
              {sentiment.yesterday_limit_up_avg_pcp > 0 && (
                <span className="text-emerald-400 ml-1">
                  昨日涨停今日平均溢价 {pct(sentiment.yesterday_limit_up_avg_pcp)}，正反馈。
                </span>
              )}
              {sentiment.yesterday_limit_up_avg_pcp < 0 && (
                <span className="text-rose-400 ml-1">
                  昨日涨停今日平均溢价 {pct(sentiment.yesterday_limit_up_avg_pcp)}，负反馈。
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <div>
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-300">20 日情绪走势</h2>
          {history.length > 0 && (
            <span className="text-xs text-slate-500">
              {history[0]?.date} ~ {history[history.length - 1]?.date}
            </span>
          )}
        </div>
        <HistoryChart data={history} />
      </div>
    </div>
  );
}