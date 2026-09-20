import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Lightbulb, LogIn, UserPlus, RefreshCw } from 'lucide-react';
import { api } from '../lib/api';
import { useStore } from '../store';

/** 登录/注册共用页（mode 区分）；成功后 setMe 并回首页 */
export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const setMe = useStore((s) => s.setMe);
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [captcha, setCaptcha] = useState('');
  const [captchaNonce, setCaptchaNonce] = useState(Date.now());
  const [inviteCode, setInviteCode] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  const isLogin = mode === 'login';

  // 注册模式进入/切换时刷新一张新验证码
  useEffect(() => {
    if (!isLogin) setCaptchaNonce(Date.now());
  }, [isLogin]);

  const refreshCaptcha = () => {
    setCaptchaNonce(Date.now());
    setCaptcha('');
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr('');
    if (!isLogin && password !== password2) {
      setErr('两次输入的密码不一致');
      return;
    }
    if (!isLogin && !captcha.trim()) {
      setErr('请输入图形验证码');
      return;
    }
    setBusy(true);
    try {
      const me = isLogin
        ? await api.login('/api', username.trim(), password)
        : await api.register('/api', username.trim(), password, captcha.trim(), inviteCode.trim());
      setMe(me);
      navigate('/', { replace: true });
    } catch (ex) {
      setErr(ex instanceof Error ? ex.message : '请求失败');
      if (!isLogin) refreshCaptcha(); // 失败刷新码
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 p-6">
      <div className="w-full max-w-sm">
        <div className="flex items-center justify-center gap-2 mb-6">
          <Lightbulb size={24} className="text-amber-300" />
          <span className="text-xl font-bold tracking-tight">炒猫量化平台</span>
        </div>

        <form
          onSubmit={submit}
          className="bg-slate-900 border border-slate-800 rounded-lg p-6 space-y-4"
        >
          <h1 className="text-lg font-semibold text-slate-200">
            {isLogin ? '登录' : '注册新账号'}
          </h1>

          <div>
            <label className="text-xs text-slate-400 mb-1 block">用户名</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder="3-32 位字母/数字/下划线"
              className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="text-xs text-slate-400 mb-1 block">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isLogin ? 'current-password' : 'new-password'}
              placeholder="至少 6 位"
              className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
            />
          </div>

          {!isLogin && (
            <div>
              <label className="text-xs text-slate-400 mb-1 block">确认密码</label>
              <input
                type="password"
                value={password2}
                onChange={(e) => setPassword2(e.target.value)}
                autoComplete="new-password"
                className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
          )}

          {!isLogin && (
            <div>
              <label className="text-xs text-slate-400 mb-1 block">
                邀请码 <span className="text-slate-600">（选填）</span>
              </label>
              <input
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value.toUpperCase())}
                placeholder="如 XK7M-3PQD"
                maxLength={12}
                className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm font-mono tracking-wider uppercase focus:outline-none focus:border-blue-500"
              />
            </div>
          )}

          {!isLogin && (
            <div>
              <label className="text-xs text-slate-400 mb-1 block">图形验证码</label>
              <div className="flex gap-2">
                <input
                  value={captcha}
                  onChange={(e) => setCaptcha(e.target.value.toUpperCase())}
                  placeholder="输入图中字符"
                  maxLength={6}
                  className="flex-1 bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm tracking-widest focus:outline-none focus:border-blue-500"
                />
                <button
                  type="button"
                  onClick={refreshCaptcha}
                  className="shrink-0 border border-slate-700 rounded-md px-2 hover:border-blue-500"
                  title="换一张"
                >
                  <img
                    ref={imgRef}
                    src={api.captchaUrl('/api', captchaNonce)}
                    alt="captcha"
                    width={120}
                    height={40}
                    className="block rounded"
                  />
                </button>
              </div>
              <button
                type="button"
                onClick={refreshCaptcha}
                className="mt-1 text-[11px] text-slate-500 hover:text-slate-300 flex items-center gap-1"
              >
                <RefreshCw size={11} /> 看不清？换一张
              </button>
            </div>
          )}

          {err && <div className="text-xs text-rose-400">{err}</div>}

          <button
            type="submit"
            disabled={busy || !username || !password || (!isLogin && !captcha.trim())}
            className="w-full flex items-center justify-center gap-2 py-2 rounded-md text-sm font-medium bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isLogin ? <LogIn size={15} /> : <UserPlus size={15} />}
            {busy ? '请稍候…' : isLogin ? '登录' : '注册并登录'}
          </button>

          <div className="text-xs text-slate-500 text-center">
            {isLogin ? (
              <>
                没有账号？<Link to="/register" className="text-blue-400 hover:text-blue-300">注册</Link>
              </>
            ) : (
              <>
                已有账号？<Link to="/login" className="text-blue-400 hover:text-blue-300">登录</Link>
              </>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}