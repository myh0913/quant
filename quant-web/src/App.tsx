import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { Gaishan } from './pages/总览';
import { Jianyi } from './pages/今日建议';
import { ReviewPage } from './pages/复盘';
import { Zhangtingchi } from './pages/涨停池';
import { LadderPage } from './pages/连板天梯';
import { Kuaixun } from './pages/快讯';
import { Zhuti } from './pages/主题';
import { Jianguan } from './pages/监管名单';
import { Shezhi } from './pages/设置';
import { QuantConfig } from './pages/量化配置';
import { AuthPage } from './pages/登录';
import { dataSource } from './lib/dataSource';
import { api } from './lib/api';
import { useStore } from './store';
import { ROLE_ADMIN } from './lib/roles';

export default function App() {
  const me = useStore((s) => s.me);
  const meLoaded = useStore((s) => s.meLoaded);
  const setMe = useStore((s) => s.setMe);
  const setSentiment = useStore((s) => s.setSentiment);
  const setPool = useStore((s) => s.setPool);
  const pushNewsflash = useStore((s) => s.pushNewsflash);
  const setThemes = useStore((s) => s.setThemes);
  const setMonitor = useStore((s) => s.setMonitor);
  const setHistory = useStore((s) => s.setHistory);
  const setAdvices = useStore((s) => s.setAdvices);
  const pushAdviceReport = useStore((s) => s.pushAdviceReport);
  const setLadder = useStore((s) => s.setLadder);
  const pushAlert = useStore((s) => s.pushAlert);
  const setStale = useStore((s) => s.setStale);
  const setStatus = useStore((s) => s.setStatus);

  // 会话校验 + 401 全局处理（会话过期自动回登录页）
  useEffect(() => {
    api
      .me('/api')
      .then((u) => setMe(u))
      .catch(() => setMe(null));
    const onUnauthorized = () => setMe(null);
    window.addEventListener('quant:unauthorized', onUnauthorized);
    return () => window.removeEventListener('quant:unauthorized', onUnauthorized);
  }, [setMe]);

  // 登录后建立长连接；登出断开
  useEffect(() => {
    if (!me) {
      dataSource.stop();
      return;
    }
    dataSource.attach({
      setStatus,
      setSentiment,
      setPool,
      pushNewsflash,
      setThemes,
      setMonitor,
      setHistory,
      setAdvices,
      pushAdviceReport,
      setLadder,
      pushAlert,
      setStale,
    });
    dataSource.start();
    return () => {
      dataSource.stop();
    };
  }, [me, setStatus, setSentiment, setPool, pushNewsflash, setThemes, setMonitor, setHistory, setAdvices, pushAdviceReport, setLadder, pushAlert, setStale]);

  if (!meLoaded) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-500 text-sm">
        正在校验会话…
      </div>
    );
  }

  if (!me) {
    return (
      <Routes>
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="*" element={<AuthPage mode="login" />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Gaishan />} />
        <Route path="/advice" element={<Jianyi />} />
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/pools" element={<Zhangtingchi />} />
        <Route path="/ladder" element={<LadderPage />} />
        <Route path="/newsflash" element={<Kuaixun />} />
        <Route path="/themes" element={<Zhuti />} />
        <Route path="/monitor" element={<Jianguan />} />
        <Route
          path="/quantconfig"
          element={
            me.role === ROLE_ADMIN ? <QuantConfig /> : <Navigate to="/" replace />
          }
        />
        <Route
          path="/settings"
          element={
            me.role === ROLE_ADMIN ? <Shezhi /> : <Navigate to="/" replace />
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
