import { useCallback, useEffect, useState } from 'react';
import clsx from 'clsx';
import {
  SlidersHorizontal, RotateCcw, Save, RefreshCw, History,
  Database, Play, X, CheckCircle2, XCircle, AlertTriangle, Loader2,
  LineChart,
} from 'lucide-react';
import { api } from '../lib/api';
import { useStore } from '../store';
import type {
  ConfigVersion, StrategyConfig, StrategyParam, DataSourceInfo, SandboxTestResp, ReplayResp,
  VersionPerf, ConfigPerfResp, BacktestRunResp, BacktestListItem, BacktestReport, BacktestAgg,
} from '../types';

/**
 * 量化配置（超管）：策略参数查看/修改/启用/回滚。
 *
 * 数据流：quant-system 启动时导出参数 schema → backend /api/config/* → 本页。
 * 保存即启用（版本化，quant-system 下一调度 tick 热生效，无需重启）。
 * percent 参数以小数存储（0.02=2%），编辑时换算为百分数展示。
 */

function displayValue(p: StrategyParam, v: number | boolean): string {
  if (p.type === 'percent') return ((v as number) * 100).toFixed(2);
  if (p.type === 'bool') return v ? '开' : '关';
  return String(v);
}

/** 上海时区今天（YYYY-MM-DD） */
function todaySH(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date());
}

/** 上海时区昨天（回放默认日期：当日快照往往不全） */
function yesterdaySH(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' })
    .format(new Date(Date.now() - 24 * 3600 * 1000));
}

/** 编辑框数值 → 存储值（bool 走独立分支不经过此函数）；非法输入返回 null */
function parseEdit(p: StrategyParam, raw: string): number | null {
  if (p.type === 'int') {
    const n = Number.parseInt(raw, 10);
    return Number.isNaN(n) ? null : n;
  }
  const n = Number.parseFloat(raw);
  if (Number.isNaN(n)) return null;
  return p.type === 'percent' ? n / 100 : n;
}

function ParamRow({
  p,
  raw,
  onChange,
}: {
  p: StrategyParam;
  raw: string;
  onChange: (v: string) => void;
}) {
  const isPercent = p.type === 'percent';
  // percent 的编辑范围/步进按百分数换算
  const min = p.min != null ? (isPercent ? p.min * 100 : p.min) : undefined;
  const max = p.max != null ? (isPercent ? p.max * 100 : p.max) : undefined;
  const step = p.step != null ? (isPercent ? p.step * 100 : p.step) : undefined;
  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-slate-800/60 last:border-0">
      <div className="w-48 shrink-0">
        <div className="text-sm text-slate-200">{p.label}</div>
        {p.desc && <div className="text-[11px] text-slate-500 mt-0.5">{p.desc}</div>}
      </div>
      <div className="flex items-center gap-2">
        <input
          type="number"
          value={raw}
          min={min}
          max={max}
          step={step}
          onChange={(e) => onChange(e.target.value)}
          className="w-28 bg-slate-950 border border-slate-700 rounded-md px-2.5 py-1.5 text-sm text-slate-200 font-mono focus:outline-none focus:border-blue-500 [color-scheme:dark]"
        />
        {isPercent && <span className="text-xs text-slate-500">%</span>}
        {!isPercent && p.unit && <span className="text-xs text-slate-500">{p.unit}</span>}
      </div>
      <div className="text-[11px] text-slate-600 mt-1.5">
        默认 {displayValue(p, p.default)}
        {min != null && ` · 下限 ${String(min)}`}
        {max != null && ` · 上限 ${String(max)}`}
      </div>
    </div>
  );
}

function StrategyCard({
  s,
  version,
  perf,
  onSaved,
}: {
  s: StrategyConfig;
  version: number;
  perf?: VersionPerf | null;
  onSaved: (msg: string) => void;
}) {
  // 编辑态：key → 输入框原始字符串
  const [edits, setEdits] = useState<Record<string, string>>(() =>
    Object.fromEntries(s.params.map((p) => [p.key, displayValue(p, s.values[p.key] ?? p.default)]))
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [testing, setTesting] = useState(false);
  const dirty = s.params.some((p) => edits[p.key] !== displayValue(p, s.values[p.key] ?? p.default));

  const save = async () => {
    setErr('');
    const values: Record<string, number | boolean> = {};
    for (const p of s.params) {
      if (p.type === 'bool') {
        values[p.key] = edits[p.key] === '开' || edits[p.key] === 'true';
        continue;
      }
      const v = parseEdit(p, edits[p.key]);
      if (v == null) {
        setErr(`参数「${p.label}」不是有效数字`);
        return;
      }
      if (p.min != null && v < p.min) {
        setErr(`参数「${p.label}」低于下限 ${displayValue(p, p.min)}`);
        return;
      }
      if (p.max != null && v > p.max) {
        setErr(`参数「${p.label}」超过上限 ${displayValue(p, p.max)}`);
        return;
      }
      values[p.key] = v;
    }
    setSaving(true);
    try {
      const r = await api.saveConfigStrategy('/api', s.id, values);
      onSaved(`「${s.label}」已启用（v${r.version}），下一调度周期热生效`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center gap-2 flex-wrap">
        <SlidersHorizontal size={15} className="text-blue-300" />
        <span className="text-sm font-medium text-slate-200">{s.label}</span>
        <span className="text-xs text-slate-600 font-mono">{s.id}</span>
        <span className="text-[11px] text-slate-500">当前版本 v{version}</span>
        <button
          onClick={() => setTesting(true)}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
        >
          <Play size={13} /> 沙箱测试
        </button>
        <button
          onClick={save}
          disabled={saving || !dirty}
          className={clsx(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors',
            dirty
              ? 'bg-blue-600 text-white hover:bg-blue-500'
              : 'bg-slate-800 text-slate-500 cursor-not-allowed'
          )}
        >
          <Save size={13} />
          {saving ? '保存中…' : '保存并启用'}
        </button>
      </div>
      {testing && <SandboxModal s={s} onClose={() => setTesting(false)} />}
      {perf && (
        <div className="mt-1 text-[11px] text-slate-500 flex items-center gap-2 flex-wrap">
          <LineChart size={12} className="text-emerald-300/70" />
          <span>
            本版本（v{version}）累计 <span className="text-slate-300 font-mono">{perf.count}</span> 条
            {perf.count > 0 && (
              <>
                {' '}· 胜率{' '}
                <span className="text-slate-300 font-mono">
                  {perf.win_rate != null ? `${(perf.win_rate * 100).toFixed(0)}%` : '—'}
                </span>
                {' / '}
                <span className="text-slate-400 font-mono">
                  {perf.win_rate_close != null ? `${(perf.win_rate_close * 100).toFixed(0)}%（收）` : '—'}
                </span>
              </>
            )}
          </span>
          {!perf.sample_enough && (
            <span className="text-amber-400/80">样本不足（&lt;10 条可成交），仅供参考</span>
          )}
        </div>
      )}
      <div className="mt-1">
        {s.params.map((p) => (
          <ParamRow
            key={p.key}
            p={p}
            raw={edits[p.key] ?? ''}
            onChange={(v) => setEdits((m) => ({ ...m, [p.key]: v }))}
          />
        ))}
      </div>
      {err && <div className="text-xs text-rose-400 mt-2">{err}</div>}
    </div>
  );
}

// =========================================================
// P2：在线测试沙箱（modal + 结果渲染）与数据源管理
// =========================================================

/** 宽松解析沙箱结果的建议行（auction/lianban/dragon 的 advices 同构） */
interface AdviceRow {
  thscode?: string;
  name?: string;
  action?: string;
  trigger_condition?: string;
}

function resultNum(r: Record<string, unknown>, k: string): number | null {
  const v = r[k];
  return typeof v === 'number' ? v : null;
}

function resultArr(r: Record<string, unknown>, k: string): unknown[] {
  const v = r[k];
  return Array.isArray(v) ? v : [];
}

function AdviceRows({ rows, title }: { rows: AdviceRow[]; title: string }) {
  if (rows.length === 0) return null;
  return (
    <div>
      <div className="text-xs text-slate-500 mb-1">{title}（{rows.length}）</div>
      <div className="space-y-1">
        {rows.map((a, i) => (
          <div key={`${a.thscode}-${i}`} className="text-xs bg-slate-950/60 border border-slate-800/60 rounded px-2.5 py-1.5">
            <span className="font-medium text-slate-200">{a.name || a.thscode}</span>
            {a.thscode && <span className="text-slate-600 font-mono ml-1.5">{a.thscode}</span>}
            {a.action && <span className="text-amber-300/90 ml-2">{a.action}</span>}
            {a.trigger_condition && <div className="text-slate-500 mt-0.5">{a.trigger_condition}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

function SandboxResultView({ resp }: { resp: SandboxTestResp }) {
  const r = resp.result;
  // lianban/dragon 特有：pool / intraday
  const pool = (r.pool ?? null) as Record<string, unknown> | null;
  const intraday = (r.intraday ?? null) as Record<string, unknown> | null;
  const triggeredKey = intraday
    ? (resultArr(intraday, 'triggered').length ? 'triggered' : 'confirmed')
    : '';
  const advices = resultArr(r, 'advices') as AdviceRow[];

  const chips: Array<{ label: string; value: string | number; cls?: string }> = [];
  const candidates = resultNum(r, 'candidates');
  if (candidates != null) chips.push({ label: '候选', value: candidates });
  if (pool) {
    chips.push({ label: '通过', value: resultArr(pool, 'passed').length });
    chips.push({ label: '拒绝', value: resultArr(pool, 'rejected').length });
  }
  if (Array.isArray(r.scenes)) chips.push({ label: '场景', value: r.scenes.length });
  if (typeof r.cycle_state === 'string' && r.cycle_state) chips.push({ label: '周期', value: r.cycle_state });
  if (intraday && triggeredKey) chips.push({ label: '盘中触发', value: resultArr(intraday, triggeredKey).length });
  chips.push({ label: '建议', value: advices.length });
  if (Array.isArray(r.blocked) && r.blocked.length > 0) chips.push({ label: '拦截', value: r.blocked.length });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-slate-500">耗时 {(resp.duration_ms / 1000).toFixed(1)}s</span>
        {chips.map((c) => (
          <span key={c.label} className="px-2 py-0.5 rounded border border-slate-700 bg-slate-800/60 text-slate-300">
            {c.label} <span className="text-slate-100 font-medium">{c.value}</span>
          </span>
        ))}
      </div>
      {resp.warnings.length > 0 && (
        <div className="text-[11px] text-amber-300/80 bg-amber-500/10 border border-amber-500/30 rounded px-2.5 py-1.5 space-y-0.5">
          {resp.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}
      {typeof r.gate_note === 'string' && r.gate_note && (
        <div className="text-[11px] text-amber-300/90 bg-amber-500/10 border border-amber-500/30 rounded px-2.5 py-1.5">
          周期门控{typeof r.gate_state === 'string' && r.gate_state ? `（${r.gate_state}）` : ''}：{r.gate_note}
        </div>
      )}
      <AdviceRows rows={advices} title="建议（沙箱产出，未落盘）" />
      {intraday && triggeredKey && resultArr(intraday, triggeredKey).length > 0 && (
        <div>
          <div className="text-xs text-slate-500 mb-1">盘中触发明细</div>
          <div className="space-y-1">
            {(resultArr(intraday, triggeredKey) as Record<string, unknown>[]).map((t, i) => (
              <div key={`${t.thscode}-${i}`} className="text-xs bg-slate-950/60 border border-slate-800/60 rounded px-2.5 py-1.5">
                <span className="text-slate-200 font-medium">{String(t.name)}</span>
                <span className="text-slate-600 font-mono ml-1.5">{String(t.thscode)}</span>
                <span className="text-emerald-300/90 ml-2">场景{String(t.scene)}</span>
                <span className="text-slate-500 ml-2">
                  {String((t.intraday as Record<string, unknown> | undefined)?.detail ?? t.detail ?? '')}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      <details className="text-xs">
        <summary className="text-slate-500 cursor-pointer hover:text-slate-400">原始 JSON</summary>
        <pre className="mt-1.5 max-h-72 overflow-auto bg-slate-950 border border-slate-800 rounded p-2.5 text-[10px] leading-relaxed text-slate-400">
          {JSON.stringify(resp.result, null, 2)}
        </pre>
      </details>
    </div>
  );
}

/** 回放结果视图：summary 摘要 + 各阶段建议（对历史快照重跑，不打真实数据源） */
function ReplayResultView({ resp, sid }: { resp: ReplayResp; sid: string }) {
  const sum = resp.summary[sid] ?? {};
  const res = resp.results[sid];
  const au = res?.phases?.auction;
  const po = res?.phases?.pool;

  const chips: Array<{ label: string; value: number | string }> = [];
  if (sum.candidates != null) chips.push({ label: '候选', value: sum.candidates });
  if (sum.pool_passed != null) chips.push({ label: '池通过', value: sum.pool_passed });
  if (sum.scenes != null) chips.push({ label: '场景', value: sum.scenes });
  if (sum.triggered != null) chips.push({ label: '盘中触发', value: sum.triggered });
  if (sum.blocked != null) chips.push({ label: '拦截', value: sum.blocked });
  if (sum.advices != null) chips.push({ label: '建议', value: sum.advices });
  if (sum.snapshot_missing) chips.push({ label: '快照缺失', value: sum.snapshot_missing });

  const advices = au && au.ok ? (resultArr(au, 'advices') as AdviceRow[]) : [];
  const poIntraday = po && po.ok ? (po.intraday as Record<string, unknown> | undefined) : undefined;
  const triggered = poIntraday ? (resultArr(poIntraday, 'triggered') as Record<string, unknown>[]) : [];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="text-slate-500">耗时 {(resp.duration_ms / 1000).toFixed(1)}s · 快照日 {resp.date}</span>
        {chips.map((c) => (
          <span key={c.label} className="px-2 py-0.5 rounded border border-slate-700 bg-slate-800/60 text-slate-300">
            {c.label} <span className="text-slate-100 font-medium">{c.value}</span>
          </span>
        ))}
      </div>
      {resp.warnings.length > 0 && (
        <div className="text-[11px] text-amber-300/80 bg-amber-500/10 border border-amber-500/30 rounded px-2.5 py-1.5 space-y-0.5">
          {resp.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}
      {au && !au.ok && typeof au.error === 'string' && (
        <div className="text-[11px] text-rose-300/90 bg-rose-500/10 border border-rose-500/30 rounded px-2.5 py-1.5">
          竞价阶段：{au.error}
        </div>
      )}
      {po && !po.ok && typeof po.error === 'string' && (
        <div className="text-[11px] text-rose-300/90 bg-rose-500/10 border border-rose-500/30 rounded px-2.5 py-1.5">
          建池阶段：{po.error}
        </div>
      )}
      <AdviceRows rows={advices} title="竞价建议（快照重跑，秒级验证参数）" />
      {triggered.length > 0 && (
        <div>
          <div className="text-xs text-slate-500 mb-1">盘中触发明细（快照重跑）</div>
          <div className="space-y-1">
            {triggered.map((t, i) => (
              <div key={`${t.thscode}-${i}`} className="text-xs bg-slate-950/60 border border-slate-800/60 rounded px-2.5 py-1.5">
                <span className="text-slate-200 font-medium">{String(t.name)}</span>
                <span className="text-slate-600 font-mono ml-1.5">{String(t.thscode)}</span>
                <span className="text-emerald-300/90 ml-2">场景{String(t.scene)}</span>
                <span className="text-slate-500 ml-2">{String(t.detail ?? '')}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <details className="text-xs">
        <summary className="text-slate-500 cursor-pointer hover:text-slate-400">原始 JSON（results）</summary>
        <pre className="mt-1.5 max-h-72 overflow-auto bg-slate-950 border border-slate-800 rounded p-2.5 text-[10px] leading-relaxed text-slate-400">
          {JSON.stringify(resp.results, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function SandboxModal({ s, onClose }: { s: StrategyConfig; onClose: () => void }) {
  const [mode, setMode] = useState<'sandbox' | 'replay'>('sandbox');
  const [date, setDate] = useState(todaySH());
  const [edits, setEdits] = useState<Record<string, string>>(() =>
    Object.fromEntries(s.params.map((p) => [p.key, displayValue(p, s.values[p.key] ?? p.default)]))
  );
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState('');
  const [resp, setResp] = useState<SandboxTestResp | null>(null);
  const [replay, setReplay] = useState<ReplayResp | null>(null);

  const switchMode = (m: 'sandbox' | 'replay') => {
    if (m === mode) return;
    setMode(m);
    setResp(null);
    setReplay(null);
    setErr('');
    // 回放对历史快照重跑，默认日期切到昨天（当日快照往往不全）
    if (m === 'replay' && date === todaySH()) setDate(yesterdaySH());
  };

  const buildParams = (): Record<string, number | boolean> | null => {
    const values: Record<string, number | boolean> = {};
    for (const p of s.params) {
      if (p.type === 'bool') {
        values[p.key] = edits[p.key] === '开' || edits[p.key] === 'true';
        continue;
      }
      const v = parseEdit(p, edits[p.key] ?? '');
      if (v == null) {
        setErr(`参数「${p.label}」不是有效数字`);
        return null;
      }
      values[p.key] = v;
    }
    return values;
  };

  const run = async () => {
    setErr('');
    setResp(null);
    setReplay(null);
    const values = buildParams();
    if (values == null) return;
    setRunning(true);
    try {
      if (mode === 'replay') {
        const r = await api.replayStrategy('/api', { strategy: s.id, date, params: values });
        setReplay(r);
      } else {
        const r = await api.testStrategy('/api', { strategy: s.id, date, params: values });
        setResp(r);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-6 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-2xl my-8 p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <Play size={15} className={mode === 'replay' ? 'text-cyan-300' : 'text-emerald-300'} />
          <span className="text-sm font-medium text-slate-200">
            {mode === 'replay' ? '快照回放' : '沙箱测试'} · {s.label}
          </span>
          <span className="text-[11px] text-slate-500">
            {mode === 'replay'
              ? '对历史标准化快照重跑（秒级，不打真实数据源，结果留档 data/replay）'
              : '独立子进程重跑策略，不落盘、不推送、不影响生产'}
          </span>
          <button onClick={onClose} className="ml-auto text-slate-500 hover:text-slate-300">
            <X size={16} />
          </button>
        </div>

        {/* 模式切换：实时沙箱（拉真实行情）vs 快照回放（读本地快照，验证参数用） */}
        <div className="flex items-center gap-1 p-1 bg-slate-950/60 border border-slate-800 rounded-md w-fit">
          {([['sandbox', '实时沙箱'], ['replay', '快照回放']] as const).map(([m, label]) => (
            <button
              key={m}
              onClick={() => switchMode(m)}
              className={clsx(
                'px-3 py-1 rounded text-xs transition-colors',
                mode === m ? 'bg-slate-800 text-slate-100' : 'text-slate-500 hover:text-slate-300'
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-400 shrink-0">{mode === 'replay' ? '快照日期' : '测试日期'}</span>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="bg-slate-950 border border-slate-700 rounded-md px-2.5 py-1.5 text-sm text-slate-200 font-mono focus:outline-none focus:border-blue-500 [color-scheme:dark]"
          />
          <span className="text-[11px] text-slate-600">
            {mode === 'replay'
              ? '选择系统运行过的交易日（live 取数自动落快照；当日快照不全）'
              : s.id === 'auction_grab'
                ? '竞价排行仅支持当日实时数据'
                : '历史日期支持分钟级回放'}
          </span>
        </div>

        <div className="border border-slate-800 rounded-md px-3 py-1">
          {s.params.map((p) => (
            <ParamRow
              key={p.key}
              p={p}
              raw={edits[p.key] ?? ''}
              onChange={(v) => setEdits((m) => ({ ...m, [p.key]: v }))}
            />
          ))}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={run}
            disabled={running}
            className={clsx(
              'flex items-center gap-1.5 px-4 py-1.5 rounded-md text-xs transition-colors',
              running
                ? 'bg-slate-800 text-slate-500'
                : mode === 'replay'
                  ? 'bg-cyan-600 text-white hover:bg-cyan-500'
                  : 'bg-emerald-600 text-white hover:bg-emerald-500'
            )}
          >
            {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            {running
              ? mode === 'replay'
                ? '回放中…（读本地快照）'
                : '沙箱运行中…（拉取行情，可能需要 1~3 分钟）'
              : mode === 'replay'
                ? '运行回放'
                : '运行测试'}
          </button>
          {err && <span className="text-xs text-rose-400">{err}</span>}
        </div>

        {resp && !resp.error && (
          <div className="border border-slate-800 rounded-lg p-3">
            <SandboxResultView resp={resp} />
          </div>
        )}
        {replay && !replay.error && (
          <div className="border border-slate-800 rounded-lg p-3">
            <ReplayResultView resp={replay} sid={s.id} />
          </div>
        )}
      </div>
    </div>
  );
}

function DatasourcesSection() {
  const [dsList, setDsList] = useState<DataSourceInfo[] | null>(null);
  const [providers, setProviders] = useState<Record<string, string[]>>({});
  const [prefs, setPrefs] = useState<Record<string, { primary: string; fallback?: string | null }>>({});
  const [err, setErr] = useState('');
  const [pinging, setPinging] = useState<string | null>(null); // id | 'all' | null

  const reload = useCallback(async () => {
    setErr('');
    try {
      const r = await api.datasources('/api');
      setDsList(r.datasources);
      setProviders(r.capability_providers ?? {});
      setPrefs(r.prefs ?? {});
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setDsList(null);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const ping = async (id?: string) => {
    setPinging(id ?? 'all');
    setErr('');
    try {
      await api.pingDatasource('/api', id);
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPinging(null);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Database size={15} className="text-cyan-300" />
        <span className="text-sm font-medium text-slate-200">数据源</span>
        <span className="text-[11px] text-slate-500">
          注册表由 quant-system 导出 · 探测走各源真实取数路径的最小请求
        </span>
        <button
          onClick={() => ping()}
          disabled={pinging != null}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors disabled:opacity-50"
        >
          {pinging === 'all' ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          全部测活
        </button>
      </div>
      {err && <div className="text-xs text-rose-400 mt-2">{err}</div>}
      {dsList == null ? (
        <div className="text-xs text-slate-500 mt-2">
          注册表不可用：quant-system 调度器启动（或任一次测活）后自动生成。
        </div>
      ) : (
        <>
          <div className="mt-1">
            {dsList.map((d) => {
              const h = d.health;
              return (
                <div key={d.id} className="flex items-center gap-3 py-2.5 border-b border-slate-800/60 last:border-0">
                  <span className={clsx('w-2 h-2 rounded-full shrink-0', h ? (h.ok ? 'bg-emerald-400' : 'bg-rose-400') : 'bg-slate-600')} />
                  <div className="w-40 shrink-0">
                    <div className="text-sm text-slate-200">{d.label}</div>
                    <div className="text-[11px] text-slate-600 font-mono">{d.id} · {d.kind}</div>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] text-slate-500 truncate">{d.desc}</div>
                    <div className="text-[11px] text-slate-600 truncate">
                      能力：{d.capabilities.join(' / ')}
                    </div>
                  </div>
                  <div className="w-56 shrink-0 text-right">
                    {h ? (
                      <>
                        <div className={clsx('text-xs', h.ok ? 'text-emerald-300/90' : 'text-rose-300/90')}>
                          {h.ok ? <CheckCircle2 size={11} className="inline mr-1 -mt-0.5" /> : <XCircle size={11} className="inline mr-1 -mt-0.5" />}
                          {h.ok ? '正常' : '异常'} · {h.latency_ms}ms
                        </div>
                        <div className="text-[11px] text-slate-600 truncate" title={h.detail}>
                          {h.detail}
                        </div>
                        <div className="text-[10px] text-slate-700 font-mono">
                          {h.checked_at.replace('T', ' ').slice(0, 19)} UTC
                        </div>
                      </>
                    ) : (
                      <span className="text-[11px] text-slate-600">未探测</span>
                    )}
                  </div>
                  <button
                    onClick={() => ping(d.id)}
                    disabled={pinging != null}
                    className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors disabled:opacity-50 shrink-0"
                  >
                    {pinging === d.id ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
                    测活
                  </button>
                </div>
              );
            })}
          </div>
          <CapabilityPrefsSection providers={providers} prefs={prefs} dsList={dsList} onSaved={reload} />
        </>
      )}
    </div>
  );
}

/** 能力级源映射与主备切换（P3）：多源能力可配置主/备，主源失败自动切换备源 */
function CapabilityPrefsSection({
  providers,
  prefs,
  dsList,
  onSaved,
}: {
  providers: Record<string, string[]>;
  prefs: Record<string, { primary: string; fallback?: string | null }>;
  dsList: DataSourceInfo[];
  onSaved: () => void;
}) {
  const labelOf = (id: string) => dsList.find((d) => d.id === id)?.label ?? id;
  const caps = Object.entries(providers);
  const [edits, setEdits] = useState<Record<string, { primary: string; fallback: string | null }>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [err, setErr] = useState('');

  const cur = (cap: string) =>
    edits[cap] ?? {
      primary: prefs[cap]?.primary ?? providers[cap]?.[0] ?? '',
      fallback: prefs[cap]?.fallback ?? null,
    };
  const dirty = (cap: string) => {
    const base = { primary: prefs[cap]?.primary ?? providers[cap]?.[0] ?? '', fallback: prefs[cap]?.fallback ?? null };
    const e = edits[cap];
    return e && (e.primary !== base.primary || e.fallback !== base.fallback);
  };

  const save = async (cap: string) => {
    setErr('');
    setSaving(cap);
    try {
      const e = cur(cap);
      await api.saveDatasourcePref('/api', { capability: cap, primary: e.primary, fallback: e.fallback });
      setEdits((m) => {
        const n = { ...m };
        delete n[cap];
        return n;
      });
      onSaved();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setSaving(null);
    }
  };

  const multi = caps.filter(([, ps]) => ps.length > 1);
  const single = caps.filter(([, ps]) => ps.length <= 1);

  return (
    <div className="mt-3 border-t border-slate-800 pt-3">
      <div className="text-xs text-slate-400 mb-1.5">
        能力与主备切换
        <span className="text-slate-600 ml-2">主源失败时自动切换备源；备源接口口径可能略有差异（如涨停池筛选范围），切换会在调度日志留痕</span>
      </div>
      {err && <div className="text-xs text-rose-400 mb-1.5">{err}</div>}
      {multi.length === 0 ? (
        <div className="text-[11px] text-slate-600">暂无可配置主备的多源能力。</div>
      ) : (
        <div className="space-y-1.5">
          {multi.map(([cap, ps]) => {
            const e = cur(cap);
            return (
              <div key={cap} className="flex items-center gap-2.5 flex-wrap bg-slate-950/50 border border-slate-800/60 rounded px-2.5 py-2">
                <span className="text-xs text-slate-300 font-mono w-40 shrink-0">{cap}</span>
                <label className="text-[11px] text-slate-500">主源</label>
                <select
                  value={e.primary}
                  onChange={(ev) => setEdits((m) => ({ ...m, [cap]: { ...e, primary: ev.target.value } }))}
                  className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
                >
                  {ps.map((id) => <option key={id} value={id}>{labelOf(id)}（{id}）</option>)}
                </select>
                <label className="text-[11px] text-slate-500">备源</label>
                <select
                  value={e.fallback ?? ''}
                  onChange={(ev) => setEdits((m) => ({ ...m, [cap]: { ...e, fallback: ev.target.value || null } }))}
                  className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
                >
                  <option value="">（无）</option>
                  {ps.filter((id) => id !== e.primary).map((id) => (
                    <option key={id} value={id}>{labelOf(id)}（{id}）</option>
                  ))}
                </select>
                {dirty(cap) ? (
                  <button
                    onClick={() => save(cap)}
                    disabled={saving === cap}
                    className="flex items-center gap-1 px-2.5 py-1 rounded text-[11px] bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50"
                  >
                    {saving === cap ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
                    保存
                  </button>
                ) : (
                  <span className="text-[10px] text-slate-600">
                    {prefs[cap] ? '已自定义（未保存的修改丢弃）' : '默认（未配置）'}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {single.length > 0 && (
        <div className="text-[11px] text-slate-600 mt-2">
          单一来源能力（无备源）：
          {single.map(([cap, ps]) => `${cap}→${labelOf(ps[0])}`).join(' · ')}
        </div>
      )}
    </div>
  );
}

/** 版本对比弹窗：历史版本 vs 当前生效（参数级 diff，仅覆盖当前 schema 内的参数） */
function DiffModal({
  old,
  current,
  onClose,
}: {
  old: ConfigVersion;
  current: StrategyConfig[];
  onClose: () => void;
}) {
  const rows: Array<{ strategy: string; param: string; label: string; a: string; b: string; changed: boolean }> = [];
  for (const s of current) {
    const oldVals = old.strategies[s.id] ?? {};
    for (const p of s.params) {
      const b = oldVals[p.key] ?? p.default; // 历史版本未覆盖 → 代码默认值
      const a = s.values[p.key] ?? p.default;
      rows.push({
        strategy: s.label, param: p.key, label: p.label,
        a: displayValue(p, a), b: displayValue(p, b),
        changed: a !== b,
      });
    }
  }
  const changed = rows.filter((r) => r.changed);
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-6 overflow-y-auto" onClick={onClose}>
      <div
        className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-2xl my-8 p-5 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <History size={15} className="text-slate-400" />
          <span className="text-sm font-medium text-slate-200">
            v{old.version}（{old.saved_at.replace('T', ' ').slice(0, 19)}）对比 当前生效
          </span>
          <button onClick={onClose} className="ml-auto text-slate-500 hover:text-slate-300"><X size={16} /></button>
        </div>
        {changed.length === 0 ? (
          <div className="text-xs text-slate-500">参数完全一致（历史版本未覆盖的参数按代码默认值参与对比）。</div>
        ) : (
          <div className="space-y-1">
            {changed.map((r) => (
              <div key={`${r.strategy}-${r.param}`} className="flex items-center gap-2 text-xs bg-slate-950/60 border border-slate-800/60 rounded px-2.5 py-1.5">
                <span className="text-slate-400 w-32 shrink-0 truncate">{r.strategy}</span>
                <span className="text-slate-300 flex-1 truncate">{r.label}</span>
                <span className="font-mono text-rose-300/90 line-through">{r.b}</span>
                <span className="text-slate-600">→</span>
                <span className="font-mono text-emerald-300/90">{r.a}</span>
              </div>
            ))}
          </div>
        )}
        <div className="text-[11px] text-slate-600">
          共 {rows.length} 个参数，其中 {changed.length} 个有差异。
        </div>
      </div>
    </div>
  );
}

export function QuantConfig() {
  const flash = useStore((s) => s.flash);
  const [data, setData] = useState<StrategyConfig[] | null>(null);
  const [version, setVersion] = useState(0);
  const [savedAt, setSavedAt] = useState('');
  const [actor, setActor] = useState('');
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [hist, setHist] = useState<ConfigVersion[]>([]);
  const [diffVer, setDiffVer] = useState<ConfigVersion | null>(null);
  const [backtestOpen, setBacktestOpen] = useState(false);
  const [perf, setPerf] = useState<ConfigPerfResp | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setErr('');
    try {
      const r = await api.configStrategies('/api');
      setData(r.strategies);
      setVersion(r.version);
      setSavedAt(r.saved_at);
      setActor(r.actor);
      const h = await api.configHistory('/api');
      setHist(h.items);
      try {
        setPerf(await api.configPerf('/api'));
      } catch {
        setPerf(null); // perf.json 未产出（新部署）不阻塞配置页
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // 保存/回滚后清除成功提示（复用推送闪光时间戳做触发器）
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(''), 6000);
    return () => clearTimeout(t);
  }, [msg, flash]);

  const rollback = async (v: number) => {
    if (!window.confirm(`确认回滚到 v${v}？将以新版本重新启用该版本的参数。`)) return;
    setErr('');
    try {
      const r = await api.rollbackConfig('/api', v);
      setMsg(`已回滚：v${v} → v${r.version} 生效`);
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="p-6 space-y-6 flex-1 min-h-0 overflow-y-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold">量化配置</h1>
          <div className="text-xs text-slate-500 mt-1">
            策略阈值参数化配置 · 保存即启用（版本化，下一调度周期热生效）
            {version > 0 && (
              <span className="ml-2 font-mono">
                当前 v{version}
                {savedAt && ` · ${savedAt.replace('T', ' ').slice(0, 19)}`}
                {actor && ` · ${actor}`}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setBacktestOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
          >
            <LineChart size={13} /> 批量回测
          </button>
          <button
            onClick={reload}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors"
          >
            <RefreshCw size={13} /> 刷新
          </button>
        </div>
      </div>

      {msg && (
        <div className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-md px-3 py-2">
          {msg}
        </div>
      )}
      {err && (
        <div className="text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-md px-3 py-2">
          {err}
        </div>
      )}

      {loading ? (
        <div className="text-sm text-slate-500">加载中…</div>
      ) : data == null ? (
        <div className="text-sm text-slate-500">
          策略参数 schema 不可用：quant-system 调度器启动后会自动导出，稍后刷新重试。
        </div>
      ) : (
        <>
          <div className="space-y-3">
            {data.map((s) => (
              <StrategyCard
                // key 带版本号：保存/回滚生效后重置编辑态为最新生效值
                key={`${s.id}-v${version}`}
                s={s}
                version={version}
                perf={perf?.strategies?.[s.id]?.[String(version)] ?? null}
                onSaved={(m) => {
                  setMsg(m);
                  reload();
                }}
              />
            ))}
          </div>

          <DatasourcesSection />

          <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
            <div className="flex items-center gap-2">
              <History size={15} className="text-slate-400" />
              <span className="text-sm font-medium text-slate-200">版本历史</span>
              <span className="text-xs text-slate-500">回滚将以新版本重新启用历史参数</span>
            </div>
            {hist.length === 0 ? (
              <div className="text-xs text-slate-500 mt-2">暂无历史版本（保存后生成）</div>
            ) : (
              <div className="mt-2">
                {hist.map((h) => (
                  <div
                    key={h.version}
                    className="flex items-center gap-3 py-2 border-b border-slate-800/60 last:border-0"
                  >
                    <span className="text-xs font-mono text-slate-400 w-10">v{h.version}</span>
                    <span className="text-xs text-slate-500 font-mono">
                      {h.saved_at.replace('T', ' ').slice(0, 19)}
                    </span>
                    <span className="text-xs text-slate-400">{h.actor || '—'}</span>
                    <span className="text-xs text-slate-600 truncate flex-1">
                      {Object.entries(h.strategies)
                        .map(([sid, vals]) => `${sid}: ${Object.values(vals).join('/')}`)
                        .join(' · ')}
                    </span>
                    {h.version !== version && (
                      <>
                        <button
                          onClick={() => setDiffVer(h)}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors shrink-0"
                        >
                          对比当前
                        </button>
                        <button
                          onClick={() => rollback(h.version)}
                          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] text-slate-300 bg-slate-800 hover:bg-slate-700 transition-colors shrink-0"
                        >
                          <RotateCcw size={11} /> 回滚到此版
                        </button>
                      </>
                    )}
                    {h.version === version && (
                      <span className="text-[11px] text-emerald-400/80 shrink-0">当前版本</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
      {diffVer && data && (
        <DiffModal old={diffVer} current={data} onClose={() => setDiffVer(null)} />
      )}
      {backtestOpen && <BacktestModal onClose={() => setBacktestOpen(false)} />}
    </div>
  );
}

// =========================================================
// M2：批量回测（modal）
// =========================================================

/** 回测默认起始：30 个自然日前 */
function daysAgoSH(n: number): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' })
    .format(new Date(Date.now() - n * 24 * 3600 * 1000));
}

function AggRows({ aggregate }: { aggregate: Record<string, BacktestAgg> }) {
  const order = ['overall', 'lianban', 'dragon', 'tailpan'];
  const keys = [
    ...order.filter((k) => aggregate[k]),
    ...Object.keys(aggregate).filter((k) => !order.includes(k) && !k.startsWith('cycle:')),
    ...Object.keys(aggregate).filter((k) => k.startsWith('cycle:')),
  ];
  const label = (k: string) =>
    k === 'overall' ? '整体' : k.startsWith('cycle:') ? `周期·${k.slice(6)}` : k;
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-slate-500 border-b border-slate-800">
          <th className="text-left py-1.5 pr-3 font-medium">范围</th>
          <th className="text-right py-1.5 pr-3 font-medium">建议</th>
          <th className="text-right py-1.5 pr-3 font-medium">可成交</th>
          <th className="text-right py-1.5 pr-3 font-medium" title="次日最高价口径（乐观）">胜率(冲高)</th>
          <th className="text-right py-1.5 pr-3 font-medium" title="次日收盘价口径（保守）">胜率(收盘)</th>
          <th className="text-right py-1.5 font-medium">均冲高</th>
        </tr>
      </thead>
      <tbody>
        {keys.map((k) => {
          const a = aggregate[k];
          const wr = a.win_rate;
          return (
            <tr key={k} className="border-b border-slate-800/50 last:border-0">
              <td className="py-1.5 pr-3 text-slate-300">{label(k)}</td>
              <td className="py-1.5 pr-3 text-right text-slate-400 font-mono">{a.count}</td>
              <td className="py-1.5 pr-3 text-right text-slate-400 font-mono">{a.fillable}</td>
              <td className={`py-1.5 pr-3 text-right font-mono ${wr != null && wr >= 0.5 ? 'text-red-300' : 'text-emerald-300'}`}>
                {wr != null ? `${(wr * 100).toFixed(0)}%` : '—'}
              </td>
              <td className={`py-1.5 pr-3 text-right font-mono ${a.win_rate_close != null && a.win_rate_close >= 0.5 ? 'text-red-300' : 'text-emerald-300'}`}>
                {a.win_rate_close != null ? `${(a.win_rate_close * 100).toFixed(0)}%` : '—'}
              </td>
              <td className="py-1.5 text-right font-mono text-slate-400">
                {a.avg_next_high_pct != null ? `${a.avg_next_high_pct > 0 ? '+' : ''}${(a.avg_next_high_pct * 100).toFixed(2)}%` : '—'}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function BacktestModal({ onClose }: { onClose: () => void }) {
  const [start, setStart] = useState(daysAgoSH(30));
  const [end, setEnd] = useState(yesterdaySH());
  const [sids, setSids] = useState<string[]>(['lianban', 'dragon', 'tailpan']);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState('');
  const [resp, setResp] = useState<BacktestRunResp | null>(null);
  const [history, setHistory] = useState<BacktestListItem[] | null>(null);
  const [report, setReport] = useState<BacktestReport | null>(null);

  const reloadHistory = useCallback(async () => {
    try {
      const r = await api.backtestList('/api');
      setHistory(r.items);
    } catch {
      setHistory([]);
    }
  }, []);
  useEffect(() => {
    reloadHistory();
  }, [reloadHistory]);

  const toggle = (id: string) =>
    setSids((m) => (m.includes(id) ? m.filter((x) => x !== id) : [...m, id]));

  const run = async () => {
    setErr('');
    setResp(null);
    setReport(null);
    if (sids.length === 0) {
      setErr('至少选择一个策略');
      return;
    }
    setRunning(true);
    try {
      const r = await api.runBacktest('/api', { start, end, strategies: sids });
      setResp(r);
      await reloadHistory();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const openReport = async (runId: string) => {
    setErr('');
    try {
      const r = await api.backtestReport('/api', runId);
      setReport(r);
      setResp(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-6 overflow-y-auto" onClick={onClose}>
      <div
        className="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-3xl my-8 p-5 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <LineChart size={15} className="text-emerald-300" />
          <span className="text-sm font-medium text-slate-200">批量回测</span>
          <span className="text-xs text-slate-500">日期驱动全流程模拟 · 快照缺失自动回填（首次较慢）</span>
          <button onClick={onClose} className="ml-auto text-slate-500 hover:text-slate-300"><X size={16} /></button>
        </div>

        <div className="flex items-center gap-3 flex-wrap text-xs">
          <label className="flex items-center gap-1.5 text-slate-400">
            开始
            <input type="date" value={start} max={end}
              onChange={(e) => setStart(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-200 [color-scheme:dark]" />
          </label>
          <label className="flex items-center gap-1.5 text-slate-400">
            结束
            <input type="date" value={end} max={yesterdaySH()} min={start}
              onChange={(e) => setEnd(e.target.value)}
              className="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-slate-200 [color-scheme:dark]" />
          </label>
          {['lianban', 'dragon', 'tailpan'].map((id) => (
            <label key={id} className="flex items-center gap-1 text-slate-300 cursor-pointer">
              <input type="checkbox" checked={sids.includes(id)} onChange={() => toggle(id)}
                className="accent-blue-500" />
              {id}
            </label>
          ))}
          <button
            onClick={run}
            disabled={running}
            className={clsx(
              'ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-colors',
              running ? 'bg-slate-800 text-slate-500 cursor-not-allowed' : 'bg-blue-600 text-white hover:bg-blue-500'
            )}
          >
            {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            {running ? '回测中…（可能数分钟）' : '开始回测'}
          </button>
        </div>
        {err && <div className="text-xs text-rose-300">{err}</div>}

        {resp && (
          <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-3 space-y-2">
            <div className="text-xs text-slate-400">
              run <span className="font-mono text-slate-300">{resp.run_id}</span> · {resp.trading_days} 个交易日 · {resp.entries} 条建议
            </div>
            <AggRows aggregate={resp.aggregate} />
          </div>
        )}
        {report && (
          <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-3 space-y-2">
            <div className="text-xs text-slate-400">
              <span className="font-mono text-slate-300">{report.run_id}</span> · {report.start} ~ {report.end} · {report.trading_days} 个交易日
              {report.entries_truncated && '（建议明细已截断）'}
            </div>
            <AggRows aggregate={report.aggregate} />
            <details>
              <summary className="text-xs text-slate-500 cursor-pointer hover:text-slate-400">
                建议明细 {report.entries.length} 条（展开）
              </summary>
              <div className="mt-1 max-h-64 overflow-y-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-slate-500 border-b border-slate-800">
                      <th className="text-left py-1 pr-2">日期</th>
                      <th className="text-left py-1 pr-2">股票</th>
                      <th className="text-left py-1 pr-2">策略·场景</th>
                      <th className="text-right py-1 pr-2">入场</th>
                      <th className="text-right py-1 pr-2">冲高</th>
                      <th className="text-right py-1 pr-2">收盘</th>
                      <th className="text-left py-1">备注</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.entries.map((e, i) => (
                      <tr key={i} className="border-b border-slate-800/40">
                        <td className="py-1 pr-2 text-slate-500 font-mono">{e.date}</td>
                        <td className="py-1 pr-2 text-slate-300">{e.name}</td>
                        <td className="py-1 pr-2 text-slate-500">{e.strategy}·{e.scene}</td>
                        <td className="py-1 pr-2 text-right text-slate-400 font-mono">{e.entry_price?.toFixed(2) ?? '—'}</td>
                        <td className={`py-1 pr-2 text-right font-mono ${e.next_high_pct != null && e.next_high_pct > 0 ? 'text-red-300' : 'text-emerald-300'}`}>
                          {e.next_high_pct != null ? `${(e.next_high_pct * 100).toFixed(2)}%` : '—'}
                        </td>
                        <td className={`py-1 pr-2 text-right font-mono ${e.next_close_pct != null && e.next_close_pct > 0 ? 'text-red-300' : 'text-emerald-300'}`}>
                          {e.next_close_pct != null ? `${(e.next_close_pct * 100).toFixed(2)}%` : '—'}
                        </td>
                        <td className="py-1 text-slate-600">{[e.unfillable && '买不进', e.demoted && '降级', e.entry_note].filter(Boolean).join('；')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
            <div className="text-[10px] text-slate-600">局限：{report.limitations.join('；')}</div>
          </div>
        )}

        <div>
          <div className="text-xs text-slate-500 mb-1">历史回测</div>
          {history == null ? (
            <div className="text-xs text-slate-600">加载中…</div>
          ) : history.length === 0 ? (
            <div className="text-xs text-slate-600">暂无回测记录</div>
          ) : (
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {history.map((h) => (
                <button
                  key={h.run_id}
                  onClick={() => openReport(h.run_id)}
                  className="w-full flex items-center gap-2 text-xs px-2 py-1.5 rounded bg-slate-950/60 border border-slate-800 hover:border-slate-600 transition-colors text-left"
                >
                  <span className="font-mono text-slate-400">{h.start}~{h.end}</span>
                  <span className="text-slate-500">{h.strategies.join(',')}</span>
                  <span className="text-slate-600">{h.trading_days}日</span>
                  <span className="ml-auto text-slate-500 font-mono">
                    整体 {h.aggregate?.overall?.win_rate != null ? `${(h.aggregate.overall.win_rate * 100).toFixed(0)}%` : '—'}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
