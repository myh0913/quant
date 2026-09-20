import type {
  Sentiment,
  PoolName,
  PoolResponse,
  NewsflashItem,
  Theme,
  MonitorData,
  DailySnapshot,
  AdviceReport,
  LadderData,
  Me,
  ManagedUser,
  Role,
  RoleInfo,
  Invitation,
  ConfigStrategiesResp,
  ConfigVersion,
  DataSourceInfo,
  DataSourcesResp,
  SandboxTestResp,
  ReplayResp,
  ReviewHistoryResp,
  ConfigPerfResp,
  BacktestRunResp,
  BacktestListItem,
  BacktestReport,
} from '../types';
import { APP_BASE } from './appBase';

// 调用方一律传 '/api'；这里统一补上应用挂载前缀（生产 '/qg'，本地 dev ''），
// 使子路径反代部署下请求命中 /qg/api/*，而不是裸根路径 /api/*。
const BASE = (url: string) => `${APP_BASE}${url.replace(/\/$/, '')}`;

/** 401 时派发全局事件（App 监听后切到登录页） */
function handle(res: Response, path: string): Promise<unknown> {
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('quant:unauthorized'));
    throw new Error('未登录或会话已过期');
  }
  if (!res.ok) {
    // 尽量透出后端错误信息（如 403 的角色限制提示）
    return res
      .json()
      .then((b) => {
        throw new Error((b as { error?: string }).error || `HTTP ${res.status} ${path}`);
      })
      .catch((e) => {
        if (e instanceof Error && e.message && !e.message.startsWith('HTTP')) throw e;
        throw new Error(`HTTP ${res.status} ${path}`);
      });
  }
  return res.json();
}

async function get<T>(base: string, path: string): Promise<T> {
  const r = await fetch(`${BASE(base)}${path}`, {
    headers: { Accept: 'application/json' },
  });
  return (await handle(r, path)) as T;
}

async function request<T>(
  base: string,
  method: 'POST' | 'PATCH' | 'DELETE' | 'PUT',
  path: string,
  body?: unknown
): Promise<T> {
  const r = await fetch(`${BASE(base)}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return (await handle(r, path)) as T;
}

export const api = {
  sentiment(base: string): Promise<Sentiment> {
    return get<Sentiment>(base, '/sentiment');
  },
  sentimentHistory(base: string, days = 10): Promise<DailySnapshot[]> {
    return get<DailySnapshot[]>(base, `/sentiment/history?days=${days}`);
  },
  pool(base: string, name: PoolName, date?: string): Promise<PoolResponse> {
    const qs = date ? `?date=${encodeURIComponent(date)}` : '';
    return get<PoolResponse>(base, `/pool/${name}${qs}`);
  },
  newsflash(base: string, limit = 50): Promise<NewsflashItem[]> {
    return get<NewsflashItem[]>(base, `/newsflash?limit=${limit}`);
  },
  themes(base: string): Promise<Theme[]> {
    return get<Theme[]>(base, '/themes');
  },
  /** 可对比的主题快照日期（最近 7 天，降序） */
  themeDates(base: string): Promise<string[]> {
    return get<string[]>(base, '/themes/dates');
  },
  /** 历史某天的主题快照 */
  themeHistory(base: string, date: string): Promise<Theme[]> {
    return get<Theme[]>(base, `/themes/history/${encodeURIComponent(date)}`);
  },
  /** 东财监管名单（重点监控 + 严重异动） */
  monitor(base: string): Promise<MonitorData> {
    return get<MonitorData>(base, '/monitor');
  },
  /** 量化系统建议（date 缺省=今天；普通用户仅历史日期可用） */
  advices(base: string, date?: string): Promise<{ date: string; items: AdviceReport[] }> {
    const qs = date ? `?date=${encodeURIComponent(date)}` : '';
    return get<{ date: string; items: AdviceReport[] }>(base, `/advice${qs}`);
  },
  /** 连板天梯（涨停池历史聚合，仅 >=2 连板）
   * opts: days=N 或 start/end=YYYY-MM-DD 闭区间（后端上限一年跨度） */
  ladder(
    base: string,
    opts?: { days?: number; start?: string; end?: string }
  ): Promise<LadderData> {
    const qs = new URLSearchParams();
    if (opts?.start && opts?.end) {
      qs.set('start', opts.start);
      qs.set('end', opts.end);
    } else {
      qs.set('days', String(opts?.days ?? 30));
    }
    return get<LadderData>(base, `/ladder?${qs.toString()}`);
  },

  // ====== 鉴权 ======
  login(base: string, username: string, password: string): Promise<Me> {
    return request<Me>(base, 'POST', '/login', { username, password });
  },
  register(
    base: string,
    username: string,
    password: string,
    captcha: string,
    inviteCode?: string
  ): Promise<Me> {
    return request<Me>(base, 'POST', '/register', {
      username,
      password,
      captcha,
      invite_code: inviteCode || '',
    });
  },
  /** 拿一张图形验证码（PNG，session 存答案，公网 Funnel 下注册必传） */
  captchaUrl(base: string, nonce: number): string {
    return `${BASE(base)}/captcha?_=${nonce}`;
  },
  logout(base: string): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(base, 'POST', '/logout');
  },
  me(base: string): Promise<Me | null> {
    return get<{ user: Me | null }>(base, '/me').then((r) => r.user);
  },

  // ====== 用户管理（超管） ======
  users(base: string): Promise<ManagedUser[]> {
    return get<ManagedUser[]>(base, '/users');
  },
  /** 角色列表（邀请码生成/用户管理的下拉数据源） */
  roles(base: string): Promise<RoleInfo[]> {
    return get<RoleInfo[]>(base, '/roles');
  },
  // ====== 邀请码（超管） ======
  invitations(base: string): Promise<Invitation[]> {
    return get<Invitation[]>(base, '/invitations');
  },
  /** 生成邀请码：days 默认 7 天有效，期内不限人数使用 */
  createInvitation(base: string, role: Role, days = 7): Promise<Invitation> {
    return request<Invitation>(base, 'POST', '/invitations', { role, days });
  },
  revokeInvitation(base: string, code: string): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(base, 'POST', `/invitations/${encodeURIComponent(code)}/revoke`);
  },
  /** 新建自定义角色 */
  createRole(base: string, name: string, label: string): Promise<RoleInfo> {
    return request<RoleInfo>(base, 'POST', '/roles', { name, label });
  },
  deleteRole(base: string, name: string): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(base, 'DELETE', `/roles/${encodeURIComponent(name)}`);
  },
  /** 保存角色可见页面；reset=true 恢复默认矩阵 */
  setRolePages(base: string, name: string, pages: string[], reset = false): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(base, 'PUT', `/roles/${encodeURIComponent(name)}/pages`, {
      pages,
      reset,
    });
  },
  createUser(base: string, username: string, password: string, role: Role): Promise<ManagedUser> {
    return request<ManagedUser>(base, 'POST', '/users', { username, password, role });
  },
  updateUser(
    base: string,
    username: string,
    patch: { role?: Role; enabled?: boolean; password?: string }
  ): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(base, 'PATCH', `/users/${encodeURIComponent(username)}`, patch);
  },
  deleteUser(base: string, username: string): Promise<{ ok: boolean }> {
    return request<{ ok: boolean }>(base, 'DELETE', `/users/${encodeURIComponent(username)}`);
  },

  // ====== 量化配置（超管）：策略参数读取/启用/历史/回滚 ======
  configStrategies(base: string): Promise<ConfigStrategiesResp> {
    return get<ConfigStrategiesResp>(base, '/config/strategies');
  },
  /** 保存并启用策略参数（values 为该策略全参数整包；percent 传小数） */
  saveConfigStrategy(
    base: string,
    sid: string,
    values: Record<string, number | boolean>
  ): Promise<{ ok: boolean; version: number }> {
    return request<{ ok: boolean; version: number }>(
      base, 'POST', `/config/strategies/${encodeURIComponent(sid)}`, { values }
    );
  },
  configHistory(base: string): Promise<{ items: ConfigVersion[] }> {
    return get<{ items: ConfigVersion[] }>(base, '/config/history');
  },
  /** 回滚：把历史版本参数作为新版本重新启用 */
  rollbackConfig(base: string, version: number): Promise<{ ok: boolean; version: number }> {
    return request<{ ok: boolean; version: number }>(
      base, 'POST', `/config/rollback/${version}`
    );
  },

  // ====== 量化配置 P2：数据源 + 在线测试沙箱 ======
  datasources(base: string): Promise<DataSourcesResp> {
    return get<DataSourcesResp>(base, '/datasources');
  },
  /** 保存能力源偏好（主/备），quant-system 下一调度 tick 热生效 */
  saveDatasourcePref(
    base: string,
    body: { capability: string; primary: string; fallback?: string | null }
  ): Promise<{ ok: boolean; prefs: Record<string, { primary: string; fallback?: string | null }> }> {
    return request(base, 'POST', '/datasources/prefs', body);
  },
  /** 连通性探测（id 缺省探测全部；结果持久化到 datasource_health.json） */
  pingDatasource(base: string, id?: string): Promise<{ ok: boolean; results: Record<string, DataSourceInfo['health']> }> {
    return request(base, 'POST', '/datasources/ping', id ? { id } : {});
  },
  /** 在线沙箱测试：以注入参数重跑策略，不落盘不推 WS */
  testStrategy(
    base: string,
    body: { strategy: string; date: string; params?: Record<string, number | boolean> }
  ): Promise<SandboxTestResp> {
    return request<SandboxTestResp>(base, 'POST', '/strategy/test', body);
  },
  /** 回放测试：对历史标准化快照重跑策略（不打真实数据源） */
  replayStrategy(
    base: string,
    body: { strategy: string; date: string; params?: Record<string, number | boolean> }
  ): Promise<ReplayResp> {
    return request<ReplayResp>(base, 'POST', '/strategy/replay', body);
  },
  /** 复盘历史：最近 N 个有复盘报告的交易日 */
  reviewHistory(base: string, days = 14): Promise<ReviewHistoryResp> {
    return get<ReviewHistoryResp>(base, `/review?days=${days}`);
  },

  // ====== M1 版本绩效闭环 / M2 批量回测 ======
  /** 参数版本绩效聚合（盘后 report.export_perf 产出） */
  configPerf(base: string): Promise<ConfigPerfResp> {
    return get<ConfigPerfResp>(base, '/config/perf');
  },
  /** 批量回测（重任务，可能数分钟；全局串行） */
  runBacktest(
    base: string,
    body: { start: string; end: string; strategies?: string[]; params?: Record<string, Record<string, number | boolean>> }
  ): Promise<BacktestRunResp> {
    return request<BacktestRunResp>(base, 'POST', '/backtest/run', body);
  },
  backtestList(base: string): Promise<{ items: BacktestListItem[] }> {
    return get<{ items: BacktestListItem[] }>(base, '/backtest/list');
  },
  backtestReport(base: string, runId: string): Promise<BacktestReport> {
    return get<BacktestReport>(base, `/backtest/report/${encodeURIComponent(runId)}`);
  },
};
