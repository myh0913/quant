import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  ListChecks,
  Zap,
  Compass,
  ShieldAlert,
  Settings as SettingsIcon,
  Lightbulb,
  TrendingUp,
  Flame,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  SlidersHorizontal,
} from 'lucide-react';
import { AlertBanner } from './AlertBanner';
import { useStore } from '../store';
import { api } from '../lib/api';
import { ROLE_ADMIN, ROLE_LABELS } from '../lib/roles';
import clsx from 'clsx';

export function AppLayout() {
  const me = useStore((s) => s.me);
  const setMe = useStore((s) => s.setMe);
  const navigate = useNavigate();
  const isAdmin = me?.role === ROLE_ADMIN;

  // 菜单栏收起/展开（收起时仅显示图标）
  const [collapsed, setCollapsed] = useState(false);

  const nav = [
    { to: '/', label: '总览', icon: LayoutDashboard, end: true, key: 'overview', show: true },
    { to: '/advice', label: '量化选股', icon: Lightbulb, end: false, key: 'advice', show: true },
    { to: '/review', label: '复盘', icon: TrendingUp, end: false, key: 'review', show: true },
    { to: '/pools', label: '涨停池', icon: ListChecks, end: false, key: 'pools', show: true },
    { to: '/ladder', label: '连板天梯', icon: Flame, end: false, key: 'ladder', show: true },
    { to: '/newsflash', label: '7×24 快讯', icon: Zap, end: false, key: 'newsflash', show: true },
    { to: '/themes', label: '主题机会', icon: Compass, end: false, key: 'themes', show: true },
    { to: '/monitor', label: '监管名单', icon: ShieldAlert, end: false, key: 'monitor', show: true },
    {
      to: '/quantconfig',
      label: '量化配置',
      icon: SlidersHorizontal,
      end: false,
      key: 'quantconfig',
      show: isAdmin,
    },
    {
      to: '/settings',
      label: '设置',
      icon: SettingsIcon,
      end: false,
      key: 'settings',
      show: isAdmin,
    },
  ]
    .filter((n) => n.show)
    // 页面权限：me.pages 由后端按角色下发（未拿到时回退旧行为，避免闪空菜单）
    .filter((n) => !me?.pages || me.pages.length === 0 || me.pages.includes(n.key));

  const logout = async () => {
    try {
      await api.logout('/api');
    } finally {
      setMe(null);
      navigate('/login', { replace: true });
    }
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <aside
        className={clsx(
          'bg-slate-900 border-r border-slate-800 flex flex-col transition-all duration-200 shrink-0',
          collapsed ? 'w-14' : 'w-56'
        )}
      >
        {/* 标题行：右侧固定展开/收起按钮 */}
        <div
          className={clsx(
            'flex items-center border-b border-slate-800 shrink-0',
            collapsed ? 'justify-center px-1 py-4' : 'px-3 py-4 pl-5 gap-1'
          )}
        >
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <div className="text-lg font-bold tracking-tight">炒猫量化平台</div>
              <div className="text-xs text-slate-500 mt-0.5">实时 A 股数据面板</div>
            </div>
          )}
          <button
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? '展开菜单栏' : '收起菜单栏'}
            className="p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors shrink-0"
          >
            {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          </button>
        </div>
        <nav className="flex-1 px-2 py-3 space-y-1 overflow-y-auto">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              title={label}
              className={({ isActive }) =>
                clsx(
                  'flex items-center rounded-md text-sm transition-colors',
                  collapsed ? 'justify-center py-2' : 'gap-2.5 px-3 py-2',
                  isActive
                    ? 'bg-blue-600/20 text-blue-300 border border-blue-500/30'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-transparent'
                )
              }
            >
              <Icon size={16} className="shrink-0" />
              {!collapsed && label}
            </NavLink>
          ))}
        </nav>
        <div
          className={clsx(
            'border-t border-slate-800 py-3',
            collapsed ? 'px-1 flex justify-center' : 'px-3 space-y-2'
          )}
        >
          {me && (
            <div className={clsx('flex items-center gap-2', !collapsed && 'px-1')}>
              {!collapsed && (
                <div className="min-w-0">
                  <div className="text-xs text-slate-300 truncate">{me.username}</div>
                  <div className="text-[10px] text-slate-500">{ROLE_LABELS[me.role]}</div>
                </div>
              )}
              <button
                onClick={logout}
                title="退出登录"
                className={clsx(
                  'p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors shrink-0',
                  !collapsed && 'ml-auto'
                )}
              >
                <LogOut size={14} />
              </button>
            </div>
          )}
        </div>
      </aside>
      {/* 页面自管滚动：内容页 h-full overflow-y-auto，天梯等 flex 布局页内部区域滚动 */}
      <main className="flex-1 min-h-0 overflow-hidden flex flex-col">
        <AlertBanner />
        <Outlet />
      </main>
    </div>
  );
}
