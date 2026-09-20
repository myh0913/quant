import { create } from 'zustand';
import type {
  Sentiment,
  PoolName,
  PoolResponse,
  NewsflashItem,
  Theme,
  MonitorData,
  WsStatus,
  DataSourceConfig,
  DailySnapshot,
  DailyReport,
  Me,
  AlertMessage,
  LadderData,
} from '../types';
import { DEFAULT_DS_CONFIG } from '../types';

interface State {
  // ===== 连接 =====
  status: WsStatus;
  dsConfig: DataSourceConfig;
  setStatus: (s: WsStatus) => void;
  setDsConfig: (c: Partial<DataSourceConfig>) => void;

  // ===== 鉴权 =====
  /** null=未登录；meLoaded 区分"未登录"与"还没校验完" */
  me: Me | null;
  meLoaded: boolean;
  setMe: (u: Me | null) => void;

  // ===== 业务数据 =====
  sentiment: Sentiment | null;
  pools: Partial<Record<PoolName, PoolResponse>>;
  newsflash: NewsflashItem[];
  themes: Theme[];
  /** 东财监管名单（重点监控 + 严重异动） */
  monitor: MonitorData | null;
  history: DailySnapshot[];
  /** 量化系统今日全部报告（ran_at 升序） */
  advices: DailyReport[];

  /** 连板天梯（涨停池历史聚合，仅 >=2 连板） */
  ladder: LadderData | null;

  // ===== 闪光（推送触发 UI 高亮） =====
  flash: Record<string, number>;

  // ===== 服务端告警（上游接口故障 / 引擎任务失败） =====
  alerts: AlertMessage[];
  pushAlert: (a: AlertMessage) => void;
  dismissAlert: (ts: number) => void;

  // ===== stale 数据（上游限频/失败时回旧值）：key → 展示名 =====
  staleKeys: Record<string, string>;
  setStale: (key: string, label: string, on: boolean) => void;

  // ===== 展开状态（移到 store 避免推送重置） =====
  expandedPool: string | null;
  toggleExpandedPool: (key: string | null) => void;

  // ===== Actions =====
  setSentiment: (s: Sentiment) => void;
  setPool: (name: PoolName, r: PoolResponse) => void;
  pushNewsflash: (items: NewsflashItem[]) => void;
  setThemes: (t: Theme[]) => void;
  setMonitor: (m: MonitorData) => void;
  setHistory: (h: DailySnapshot[]) => void;
  setAdvices: (items: DailyReport[]) => void;
  pushAdviceReport: (r: DailyReport) => void;
  setLadder: (d: LadderData) => void;
}

/** 报告唯一键：来源文件名优先，退化用 ran_at+名称 */
function adviceKey(r: DailyReport): string {
  if ('file' in r && r.file) return r.file;
  const name = 'strategy' in r ? r.strategy : 'type' in r ? r.type : '';
  return `${(r as { ran_at?: string }).ran_at}|${name}`;
}

export const useStore = create<State>((set) => ({
  status: 'closed',
  dsConfig: { ...DEFAULT_DS_CONFIG },
  setStatus: (s) => set({ status: s }),
  setDsConfig: (c) => set((st) => ({ dsConfig: { ...st.dsConfig, ...c } })),

  me: null,
  meLoaded: false,
  setMe: (u) => set({ me: u, meLoaded: true }),

  sentiment: null,
  pools: {},
  newsflash: [],
  themes: [],
  monitor: null,
  history: [],
  advices: [],
  ladder: null,
  flash: {},
  expandedPool: null,
  toggleExpandedPool: (key) => set({ expandedPool: key }),

  setSentiment: (s) =>
    set((st) => ({
      sentiment: s,
      flash: { ...st.flash, sentiment: Date.now() },
    })),
  setPool: (name, r) =>
    set((st) => ({
      pools: { ...st.pools, [name]: r },
      flash: { ...st.flash, [`pool:${name}`]: Date.now() },
    })),
  pushNewsflash: (items) =>
    set((st) => {
      const existing = new Set(st.newsflash.map((n) => n.id));
      const merged = [
        ...items.filter((n) => !existing.has(n.id)),
        ...st.newsflash,
      ].slice(0, 300);
      return {
        newsflash: merged,
        flash: { ...st.flash, newsflash: Date.now() },
      };
    }),
  setThemes: (t) => {
    set((st) => ({
      themes: t,
      flash: { ...st.flash, themes: Date.now() },
    }));
  },
  setMonitor: (m) =>
    set((st) => ({
      monitor: m,
      flash: { ...st.flash, monitor: Date.now() },
    })),
  setHistory: (h) =>
    set((st) => ({
      history: h,
      flash: { ...st.flash, history: Date.now() },
    })),
  setAdvices: (items) =>
    set((st) => ({
      advices: [...items].sort((a, b) =>
        (((a as { ran_at?: string }).ran_at ?? '') >
        ((b as { ran_at?: string }).ran_at ?? ''))
          ? 1
          : -1
      ),
      flash: { ...st.flash, advices: Date.now() },
    })),
  pushAdviceReport: (r) =>
    set((st) => {
      const key = adviceKey(r);
      const exists = st.advices.some((a) => adviceKey(a) === key);
      // 已存在 → 静默更新（文件覆盖场景），不重复追加
      const merged = exists
        ? st.advices.map((a) => (adviceKey(a) === key ? r : a))
        : [...st.advices, r];
      merged.sort((a, b) =>
        (((a as { ran_at?: string }).ran_at ?? '') >
        ((b as { ran_at?: string }).ran_at ?? ''))
          ? 1
          : -1
      );
      return {
        advices: merged,
        flash: { ...st.flash, advices: Date.now() },
      };
    }),
  setLadder: (d) => set({ ladder: d }),

  alerts: [],
  // 同 source+message 去重；最多保留 5 条，新的顶掉旧的
  pushAlert: (a) =>
    set((st) => {
      if (st.alerts.some((x) => x.source === a.source && x.message === a.message && x.ts === a.ts)) {
        return st;
      }
      return { alerts: [...st.alerts, a].slice(-5) };
    }),
  dismissAlert: (ts) =>
    set((st) => ({ alerts: st.alerts.filter((x) => x.ts !== ts) })),

  staleKeys: {},
  setStale: (key, label, on) =>
    set((st) => {
      if (on) {
        if (st.staleKeys[key]) return st;
        return { staleKeys: { ...st.staleKeys, [key]: label } };
      }
      if (!(key in st.staleKeys)) return st;
      const next = { ...st.staleKeys };
      delete next[key];
      return { staleKeys: next };
    }),
}));