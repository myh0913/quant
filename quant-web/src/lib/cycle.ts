/**
 * 情绪周期展示逻辑（共享）
 *
 * 周期判定有两个来源（取 ran_at 最新者为"当前状态"）：
 * - 竞价报告 auction_grab_*.json → cycle_state / cycle_reasons / cycle_position_factor（含仓位门控因子）
 * - 盘后报告 cycle_*.json        → state / reasons / indicators（含过热标记，无仓位因子）
 */
import type { AdviceReport, CycleReport, DailyReport } from '../types';
import { reportKind } from '../types';

/** 情绪周期六态配色（红热绿冷） */
export const CYCLE_STYLES: Record<string, string> = {
  冰点: 'text-sky-300 bg-sky-500/10 border-sky-500/30',
  转折: 'text-violet-300 bg-violet-500/10 border-violet-500/30',
  修复: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
  加速: 'text-rose-300 bg-rose-500/10 border-rose-500/30',
  分歧: 'text-orange-300 bg-orange-500/10 border-orange-500/30',
  退潮: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
};

export interface CycleInfo {
  state: string;
  reasons: string[];
  /** 仓位门控因子（仅竞价报告携带；盘后报告无此字段） */
  positionFactor?: number;
  overheated?: boolean;
  indicators?: CycleReport['indicators'];
  /** ISO 时间 */
  ranAt: string;
  /** 来源：auction=竞价盘中判定 / cycle=盘后判定 */
  source: 'auction' | 'cycle';
}

/** 最新周期判定：遍历今日报告，取 ran_at 最新的周期来源 */
export function latestCycle(advices: DailyReport[]): CycleInfo | null {
  let best: CycleInfo | null = null;
  for (const r of advices) {
    let info: CycleInfo | null = null;
    if (reportKind(r) === 'cycle') {
      const c = r as CycleReport;
      info = {
        state: c.state,
        reasons: c.reasons,
        overheated: c.overheated,
        indicators: c.indicators,
        ranAt: c.ran_at ?? '',
        source: 'cycle',
      };
    } else if (reportKind(r) === 'auction') {
      const a = r as AdviceReport;
      info = {
        state: a.cycle_state,
        reasons: a.cycle_reasons,
        positionFactor: a.cycle_position_factor,
        ranAt: a.ran_at,
        source: 'auction',
      };
    }
    if (info && (!best || info.ranAt > best.ranAt)) best = info;
  }
  return best;
}

/** 仓位因子释义（对齐 quant-system pipeline 的门控档位） */
export function factorLabel(f: number | undefined): string | null {
  if (f == null) return null;
  if (f <= 0) return '停开新仓';
  if (f < 1) return `仓位 ×${f}`;
  return '正常仓位';
}
