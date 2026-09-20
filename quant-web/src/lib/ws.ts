import type { WsInbound, WsOutbound, WsStatus } from '../types';

type Listener = (msg: WsInbound) => void;

/** 心跳间隔（发送 ping） */
const PING_INTERVAL = 30_000;
/** 超过该时长未收到任何消息视为半开连接，主动断开触发重连 */
const STALE_TIMEOUT = 60_000;

class WsClientImpl {
  private listeners = new Set<Listener>();
  private socket: WebSocket | null = null;
  private url: string | null = null;
  private statusVal: WsStatus = 'closed';
  private reconnectAttempt = 0;
  private reconnectTimer: number | null = null;
  private heartbeatTimer: number | null = null;
  private lastSeen = 0;
  private intentionalClose = false;

  status(): WsStatus {
    return this.statusVal;
  }

  subscribe(cb: Listener): () => void {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  }

  private emit(msg: WsInbound): void {
    this.listeners.forEach((l) => {
      try {
        l(msg);
      } catch (e) {
        console.error('[ws] listener error', e);
      }
    });
  }

  connect(url: string): void {
    if (this.url === url && this.statusVal === 'open') return;
    this.disconnect();
    this.url = url;
    this.intentionalClose = false;
    this.setStatus('connecting');
    console.info('[ws] connecting to', url);

    try {
      const sock = new WebSocket(url);
      this.socket = sock;

      sock.onopen = () => {
        this.reconnectAttempt = 0;
        this.setStatus('open');
        this.startHeartbeat();
      };

      sock.onmessage = (ev) => {
        this.lastSeen = Date.now();
        try {
          const data = JSON.parse(ev.data) as WsInbound;
          this.emit(data);
        } catch (e) {
          console.error('[ws] parse error', e, ev.data);
        }
      };

      sock.onerror = () => {
        // onclose will fire next
      };

      sock.onclose = () => {
        this.stopHeartbeat();
        if (this.socket === sock) this.socket = null;
        this.setStatus('closed');
        if (!this.intentionalClose) this.scheduleReconnect();
      };
    } catch (e) {
      console.error('[ws] connect error', e);
      this.setStatus('closed');
      this.scheduleReconnect();
    }
  }

  /** 定时 ping 保活；长时间无任何消息则视为死连接，主动断开触发重连 */
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.lastSeen = Date.now();
    this.heartbeatTimer = window.setInterval(() => {
      if (Date.now() - this.lastSeen > STALE_TIMEOUT) {
        console.warn('[ws] stale connection (no message in', STALE_TIMEOUT, 'ms), closing');
        try {
          this.socket?.close();
        } catch {
          /* onclose will fire */
        }
        return;
      }
      this.send({ type: 'ping' });
    }, PING_INTERVAL);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private setStatus(s: WsStatus): void {
    this.statusVal = s;
    this.emit({ type: 'hello', message: `status:${s}` });
  }

  private scheduleReconnect(): void {
    if (!this.url) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempt, 30000);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      if (this.url) {
        console.log(`[ws] reconnect attempt ${this.reconnectAttempt}`);
        this.connect(this.url);
      }
    }, delay);
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.onclose = null;
      try {
        this.socket.close();
      } catch {
        /* ignore */
      }
      this.socket = null;
    }
    this.url = null;
    this.setStatus('closed');
  }

  send(msg: WsOutbound): void {
    if (this.statusVal === 'open' && this.socket) {
      this.socket.send(JSON.stringify(msg));
    }
  }
}

export const wsClient = new WsClientImpl();