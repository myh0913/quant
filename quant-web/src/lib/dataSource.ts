/**
 * 数据源（纯 WS 长连接模式）
 *
 * 连接建立（含断线重连）时：
 * 1. 重新 subscribe 所有频道
 * 2. REST 全量拉一轮初始/补数据（断线期间错过的内容由此补齐）
 *
 * 之后：
 * - 行情类数据（情绪/池子/快讯/主题/监管名单/情绪历史）由后端 data_refresh_loop 定时广播
 * - 量化系统建议由后端监听落盘目录实时推送
 *
 * 业务代码只依赖 store，不感知数据来源细节。
 */

import { api } from './api';
import { wsClient } from './ws';
import type {
  DataSourceConfig,
  Sentiment,
  PoolName,
  PoolResponse,
  NewsflashItem,
  Theme,
  MonitorData,
  DailySnapshot,
  DailyReport,
  LadderData,
  WsStatus,
} from '../types';
import { DEFAULT_DS_CONFIG } from '../types';

interface DataSourceHandlers {
  setStatus: (s: WsStatus) => void;
  setSentiment: (s: Sentiment) => void;
  setPool: (name: PoolName, r: PoolResponse) => void;
  pushNewsflash: (items: NewsflashItem[]) => void;
  setThemes: (t: Theme[]) => void;
  setMonitor: (m: MonitorData) => void;
  setHistory: (h: DailySnapshot[]) => void;
  setAdvices: (items: DailyReport[]) => void;
  pushAdviceReport: (r: DailyReport) => void;
  setLadder: (d: LadderData) => void;
  pushAlert: (a: { source: string; message: string; ts: number }) => void;
  setStale: (key: string, label: string, on: boolean) => void;
}

/** WS 消息类型 → staleKeys 展示名 */
const STALE_LABELS: Record<string, string> = {
  sentiment: '市场情绪',
  sentiment_history: '情绪历史',
  pool: '涨停池',
  newsflash: '7×24快讯',
  theme: '主题机会',
  monitor: '监管名单',
  ladder: '连板天梯',
};

class DataSourceImpl {
  private config: DataSourceConfig = { ...DEFAULT_DS_CONFIG };
  private handlers: DataSourceHandlers | null = null;
  private wsUnsub: (() => void) | null = null;
  private running = false;

  /** 安装处理器（store actions） */
  attach(h: DataSourceHandlers): void {
    this.handlers = h;
  }

  setConfig(c: Partial<DataSourceConfig>): void {
    this.config = { ...this.config, ...c };
    if (this.running) {
      // 切地址需要重启
      this.stop();
      this.start();
    }
  }

  getConfig(): DataSourceConfig {
    return { ...this.config };
  }

  start(): void {
    if (this.running || !this.handlers) return;
    this.running = true;
    this.handlers.setStatus('connecting');
    wsClient.connect(this.config.wsUrl);
    this.wsUnsub = wsClient.subscribe((msg) => this.onMessage(msg));
  }

  stop(): void {
    this.running = false;
    if (this.wsUnsub) {
      this.wsUnsub();
      this.wsUnsub = null;
    }
    wsClient.disconnect();
    this.handlers?.setStatus('closed');
  }

  private onMessage(msg: import('../types').WsInbound): void {
    const h = this.handlers;
    if (!h) return;
    if (msg.type === 'hello') {
      if (msg.message.startsWith('status:')) {
        const st = msg.message.slice(7) as WsStatus;
        h.setStatus(st);
        if (st === 'open') {
          // 每次连接建立（含断线重连）都要：
          // 1. 重新订阅 —— 重连后服务端侧的订阅已丢失
          // 2. REST 全量补数据 —— 补上断线期间错过的内容
          wsClient.send({
            type: 'subscribe',
            channels: ['sentiment', 'pool', 'newsflash', 'themes', 'monitor', 'advice', 'ladder'],
          });
          this.fetchAll();
        }
      }
      return;
    }
    switch (msg.type) {
      case 'sentiment':
        h.setSentiment(msg.data);
        break;
      case 'sentiment_history':
        h.setHistory(msg.data);
        break;
      case 'pool':
        h.setPool(msg.pool_name, msg.data);
        break;
      case 'newsflash':
        h.pushNewsflash(msg.data);
        break;
      case 'theme':
        h.setThemes(msg.data);
        break;
      case 'monitor':
        h.setMonitor(msg.data);
        break;
      case 'advice':
        h.pushAdviceReport(msg.data);
        break;
      case 'ladder':
        h.setLadder(msg.data);
        break;
      case 'alert':
        // 上游接口故障 / 量化引擎任务失败 → 全局横幅提示
        h.pushAlert({ source: msg.source, message: msg.message, ts: msg.ts });
        break;
      case 'heartbeat':
        // 收到即证明连接存活（lastSeen 在 wsClient 内部更新）
        break;
    }
    // stale 标记：上游限频/失败时后端回旧值并带 _stale → 顶栏提示
    const label = STALE_LABELS[msg.type];
    if (label) {
      const data = (msg as { data?: { _stale?: boolean } }).data;
      h.setStale(msg.type, label, data?._stale === true);
    }
  }

  /** 连接建立后的初始全量加载（REST） */
  private async fetchAll(): Promise<void> {
    if (!this.handlers) return;
    const base = '/api';
    const [sentiment, history, newsflash, themes, monitor, advices, ladder] = await Promise.all([
      api.sentiment(base).catch(() => null),
      api.sentimentHistory(base, 10).catch(() => null),
      api.newsflash(base).catch(() => null),
      api.themes(base).catch(() => null),
      api.monitor(base).catch(() => null),
      api.advices(base).catch(() => null),
      api.ladder(base).catch(() => null),
    ]);
    const h = this.handlers;
    if (sentiment) h.setSentiment(sentiment);
    if (history) h.setHistory(history);
    if (newsflash) h.pushNewsflash(newsflash);
    if (themes) h.setThemes(themes);
    if (monitor) h.setMonitor(monitor);
    if (advices) h.setAdvices(advices.items);
    if (ladder) h.setLadder(ladder);
    // 7 个池子并行抓
    Promise.all(POOL_ALL.map((n) => api.pool(base, n).catch(() => null))).then((results) => {
      results.forEach((r, i) => {
        if (r) this.handlers?.setPool(POOL_ALL[i], r);
      });
    });
  }
}

const POOL_ALL: PoolName[] = [
  'limit_up',
  'limit_up_broken',
  'yesterday_limit_up',
  'super_stock',
  'limit_down',
  'new_stock',
  'nearly_new',
];

export const dataSource = new DataSourceImpl();
