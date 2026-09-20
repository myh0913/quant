import { useCallback, useEffect, useState } from 'react';
import {
  Users,
  UserPlus,
  Trash2,
  KeyRound,
  RefreshCw,
  Ticket,
  Copy,
  Ban,
  Plug,
  ShieldCheck,
  RotateCcw,
} from 'lucide-react';
import { useStore } from '../store';
import { ConnectionStatus } from '../components/ConnectionStatus';
import { dataSource } from '../lib/dataSource';
import { api } from '../lib/api';
import {
  DEFAULT_DS_CONFIG,
  type DataSourceConfig,
  type ManagedUser,
  type Role,
  type RoleInfo,
  type Invitation,
} from '../types';
import { ROLE_LABELS, ROLE_USER, ROLE_ADVANCED, ROLE_ADMIN } from '../lib/roles';

const ROLE_OPTIONS: Role[] = [ROLE_USER, ROLE_ADVANCED, ROLE_ADMIN];

/** 可配置页面（settings 仅 admin，不参与矩阵） */
const PAGE_MATRIX: { key: string; label: string }[] = [
  { key: 'overview', label: '总览' },
  { key: 'advice', label: '量化选股' },
  { key: 'pools', label: '涨停池' },
  { key: 'ladder', label: '连板天梯' },
  { key: 'newsflash', label: '7×24 快讯' },
  { key: 'themes', label: '主题机会' },
  { key: 'monitor', label: '监管名单' },
];
const DEFAULT_PAGES = PAGE_MATRIX.map((p) => p.key); // 非管理员默认：全部可看

/** 角色权限管理（仅超管）：新建/删除角色 + 角色×页面勾选矩阵 */
function RolesPanel() {
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [pagesState, setPagesState] = useState<Record<string, string[]>>({});
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [newName, setNewName] = useState('');
  const [newLabel, setNewLabel] = useState('');

  const reload = useCallback(() => {
    api
      .roles('/api')
      .then((rs) => {
        setRoles(rs);
        const next: Record<string, string[]> = {};
        for (const r of rs) next[r.name] = r.pages_configured ? r.pages : [...DEFAULT_PAGES];
        setPagesState(next);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : '加载失败'));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const dirty = (r: RoleInfo) => {
    if (r.is_system && r.name === ROLE_ADMIN) return false;
    const cur = [...(pagesState[r.name] ?? [])].sort();
    const saved = r.pages_configured ? [...r.pages].sort() : [...DEFAULT_PAGES].sort();
    return JSON.stringify(cur) !== JSON.stringify(saved);
  };

  const toggle = (roleName: string, pageKey: string) => {
    setPagesState((s) => {
      const cur = s[roleName] ?? [];
      return {
        ...s,
        [roleName]: cur.includes(pageKey)
          ? cur.filter((k) => k !== pageKey)
          : [...cur, pageKey],
      };
    });
  };

  const save = async (r: RoleInfo) => {
    setErr('');
    setNotice('');
    try {
      await api.setRolePages('/api', r.name, pagesState[r.name] ?? []);
      setNotice(`角色「${r.label}」页面权限已保存（用户重新登录后生效）`);
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '保存失败');
    }
  };

  const reset = async (r: RoleInfo) => {
    setErr('');
    setNotice('');
    try {
      await api.setRolePages('/api', r.name, [], true);
      setNotice(`角色「${r.label}」已恢复默认权限`);
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '恢复失败');
    }
  };

  const createRole = async () => {
    setErr('');
    setNotice('');
    try {
      await api.createRole('/api', newName.trim(), newLabel.trim());
      setNotice(`角色「${newLabel.trim()}」已创建，默认可见全部页面（除设置）`);
      setNewName('');
      setNewLabel('');
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '创建失败');
    }
  };

  const deleteRole = async (r: RoleInfo) => {
    if (!window.confirm(`确认删除角色「${r.label}」（${r.name}）？`)) return;
    setErr('');
    setNotice('');
    try {
      await api.deleteRole('/api', r.name);
      setNotice('角色已删除');
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '删除失败');
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
      <div className="flex items-center gap-2">
        <ShieldCheck size={15} className="text-emerald-300" />
        <span className="text-sm font-medium text-slate-200">角色权限</span>
        <button
          onClick={reload}
          className="ml-auto p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          title="刷新"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-800">
              <th className="text-left py-2 pr-3 font-normal">角色</th>
              {PAGE_MATRIX.map((p) => (
                <th key={p.key} className="px-2 py-2 font-normal text-center">
                  {p.label}
                </th>
              ))}
              <th className="py-2 font-normal text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {roles.map((r) => {
              const isAdminRole = r.name === ROLE_ADMIN;
              const pages = pagesState[r.name] ?? [];
              return (
                <tr key={r.name} className="border-b border-slate-900">
                  <td className="py-2 pr-3 whitespace-nowrap">
                    <span className="text-slate-200 text-xs">{r.label}</span>
                    <span className="text-[10px] text-slate-600 ml-1.5 font-mono">{r.name}</span>
                    {r.pages_configured ? (
                      <span className="text-[10px] text-amber-300/80 ml-1.5">已自定义</span>
                    ) : (
                      !isAdminRole && (
                        <span className="text-[10px] text-slate-600 ml-1.5">默认</span>
                      )
                    )}
                  </td>
                  {PAGE_MATRIX.map((p) => (
                    <td key={p.key} className="px-2 py-2 text-center">
                      <input
                        type="checkbox"
                        disabled={isAdminRole}
                        checked={isAdminRole || pages.includes(p.key)}
                        onChange={() => toggle(r.name, p.key)}
                        className="accent-blue-500 disabled:opacity-60 disabled:cursor-not-allowed"
                      />
                    </td>
                  ))}
                  <td className="py-2">
                    <div className="flex items-center justify-end gap-1.5">
                      {dirty(r) && (
                        <button
                          onClick={() => save(r)}
                          className="text-xs px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                        >
                          保存
                        </button>
                      )}
                      {r.pages_configured ? (
                        <button
                          title="恢复默认（全部页面，除设置）"
                          onClick={() => reset(r)}
                          className="p-1.5 rounded text-slate-500 hover:text-amber-300 hover:bg-slate-800 transition-colors"
                        >
                          <RotateCcw size={13} />
                        </button>
                      ) : null}
                      {!r.is_system && (
                        <button
                          title="删除角色"
                          onClick={() => deleteRole(r)}
                          className="p-1.5 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition-colors"
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                      {isAdminRole && (
                        <span className="text-[10px] text-slate-600">全部页面</span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="border-t border-slate-800 pt-3">
        <div className="flex items-center gap-2 flex-wrap">
          <UserPlus size={14} className="text-slate-500" />
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value.toLowerCase())}
            placeholder="角色标识（如 vip）"
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-xs w-44 focus:outline-none focus:border-blue-500 font-mono"
          />
          <input
            value={newLabel}
            onChange={(e) => setNewLabel(e.target.value)}
            placeholder="显示名（如 VIP 用户）"
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-xs w-44 focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={createRole}
            disabled={!newName.trim() || !newLabel.trim()}
            className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-xs font-medium transition-colors"
          >
            新建角色
          </button>
        </div>
        <div className="text-[11px] text-slate-600 mt-2">
          新角色默认可见全部页面（除设置）；勾选变更后点「保存」生效，用户重新登录后菜单更新。
          角色删除前需先迁移该角色的用户并撤销引用它的邀请码。
        </div>
      </div>

      {err && <div className="text-xs text-rose-400">{err}</div>}
      {notice && <div className="text-xs text-emerald-400">{notice}</div>}
    </div>
  );
}

/** 用户权限管理（仅超管可见，后端同样校验） */
function UsersPanel() {
  const me = useStore((s) => s.me);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [newName, setNewName] = useState('');
  const [newPw, setNewPw] = useState('');
  const [newRole, setNewRole] = useState<string>(ROLE_USER);

  const reload = useCallback(() => {
    api
      .users('/api')
      .then(setUsers)
      .catch((e) => setErr(e instanceof Error ? e.message : '加载失败'));
    api
      .roles('/api')
      .then(setRoles)
      .catch(() => setRoles([]));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const roleLabel = (name: string) =>
    roles.find((r) => r.name === name)?.label ?? ROLE_LABELS[name as Role] ?? name;
  const roleNames = roles.length ? roles.map((r) => r.name) : ROLE_OPTIONS;

  const run = async (fn: () => Promise<unknown>, okMsg: string) => {
    setErr('');
    setNotice('');
    try {
      await fn();
      setNotice(okMsg);
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '操作失败');
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Users size={15} className="text-blue-300" />
        <span className="text-sm font-medium text-slate-200">用户权限管理</span>
        <button
          onClick={reload}
          className="ml-auto p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          title="刷新"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-800">
              <th className="text-left py-2 pr-3 font-normal">用户名</th>
              <th className="text-left py-2 pr-3 font-normal">角色</th>
              <th className="text-left py-2 pr-3 font-normal">状态</th>
              <th className="text-left py-2 pr-3 font-normal">创建时间</th>
              <th className="text-left py-2 font-normal">操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const self = u.username === me?.username;
              return (
                <tr key={u.username} className="border-b border-slate-900">
                  <td className="py-2 pr-3">
                    <span className="text-slate-200">{u.username}</span>
                    {self && <span className="text-[10px] text-slate-500 ml-1.5">（我）</span>}
                  </td>
                  <td className="py-2 pr-3">
                    <select
                      value={u.role}
                      disabled={self}
                      onChange={(e) =>
                        run(
                          () => api.updateUser('/api', u.username, { role: e.target.value as Role }),
                          '角色已更新'
                        )
                      }
                      className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1 text-xs disabled:opacity-40"
                    >
                      {roleNames.map((r) => (
                        <option key={r} value={r}>
                          {roleLabel(r)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2 pr-3">
                    <button
                      disabled={self}
                      onClick={() =>
                        run(
                          () => api.updateUser('/api', u.username, { enabled: !u.enabled }),
                          u.enabled ? '已停用' : '已启用'
                        )
                      }
                      className={`text-xs px-1.5 py-0.5 rounded border disabled:opacity-40 ${
                        u.enabled
                          ? 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30'
                          : 'text-slate-500 bg-slate-800 border-slate-700'
                      }`}
                    >
                      {u.enabled ? '启用' : '停用'}
                    </button>
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs text-slate-500">
                    {u.created_at ? u.created_at.slice(0, 10) : '—'}
                  </td>
                  <td className="py-2">
                    <div className="flex items-center gap-1.5">
                      <button
                        title="重置密码"
                        onClick={() => {
                          const pw = window.prompt(`为 ${u.username} 设置新密码（≥6 位）`);
                          if (pw)
                            run(
                              () => api.updateUser('/api', u.username, { password: pw }),
                              '密码已重置'
                            );
                        }}
                        className="p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                      >
                        <KeyRound size={13} />
                      </button>
                      <button
                        title={self ? '不能删除自己' : '删除用户'}
                        disabled={self}
                        onClick={() => {
                          if (window.confirm(`确认删除用户 ${u.username}？`))
                            run(() => api.deleteUser('/api', u.username), '已删除');
                        }}
                        className="p-1.5 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 disabled:opacity-30 disabled:hover:text-slate-500 transition-colors"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="border-t border-slate-800 pt-3">
        <div className="flex items-center gap-2 flex-wrap">
          <UserPlus size={14} className="text-slate-500" />
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="用户名"
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-xs w-36 focus:outline-none focus:border-blue-500"
          />
          <input
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            placeholder="密码（≥6 位）"
            type="password"
            className="bg-slate-950 border border-slate-700 rounded px-2 py-1.5 text-xs w-36 focus:outline-none focus:border-blue-500"
          />
          <select
            value={newRole}
            onChange={(e) => setNewRole(e.target.value)}
            className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1.5 text-xs"
          >
            {roleNames.map((r) => (
              <option key={r} value={r}>
                {roleLabel(r)}
              </option>
            ))}
          </select>
          <button
            onClick={() => {
              if (newName && newPw)
                run(
                  () => api.createUser('/api', newName.trim(), newPw, newRole as Role),
                  '用户已创建'
                ).then(() => {
                  setNewName('');
                  setNewPw('');
                });
            }}
            disabled={!newName || !newPw}
            className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-xs font-medium transition-colors"
          >
            创建用户
          </button>
        </div>
        <div className="text-[11px] text-slate-600 mt-2">
          各角色可看哪些页面在「角色权限」tab 配置；默认普通/高级用户看全部（除设置），超管全部
        </div>
      </div>

      {err && <div className="text-xs text-rose-400">{err}</div>}
      {notice && <div className="text-xs text-emerald-400">{notice}</div>}
    </div>
  );
}

/** 邀请码管理（仅超管）：生成（角色下拉 + 有效期）、列表、复制、撤销 */
function InvitationsPanel() {
  const [invs, setInvs] = useState<Invitation[]>([]);
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');
  const [newRole, setNewRole] = useState<Role>(ROLE_ADVANCED);
  const [newDays, setNewDays] = useState(7);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(() => {
    api
      .invitations('/api')
      .then(setInvs)
      .catch((e) => setErr(e instanceof Error ? e.message : '加载失败'));
  }, []);

  useEffect(() => {
    reload();
    api
      .roles('/api')
      .then(setRoles)
      .catch(() => setRoles([]));
  }, [reload]);

  const roleLabel = (name: string) =>
    roles.find((r) => r.name === name)?.label ?? ROLE_LABELS[name as Role] ?? name;

  const statusBadge = (s: Invitation['status']) => {
    const map = {
      active: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
      expired: 'text-slate-500 bg-slate-800 border-slate-700',
      revoked: 'text-rose-300 bg-rose-500/10 border-rose-500/30',
    } as const;
    const label = { active: '生效中', expired: '已过期', revoked: '已撤销' }[s];
    return (
      <span className={`text-xs px-1.5 py-0.5 rounded border ${map[s]}`}>{label}</span>
    );
  };

  const generate = async () => {
    setErr('');
    setNotice('');
    setBusy(true);
    try {
      const inv = await api.createInvitation('/api', newRole, newDays);
      setNotice(`已生成：${inv.code}（${roleLabel(inv.role)}，${newDays} 天内有效）`);
      reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '生成失败');
    } finally {
      setBusy(false);
    }
  };

  const copy = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setNotice(`已复制 ${code}`);
      setErr('');
    } catch {
      setErr('复制失败，请手动选择复制');
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Ticket size={15} className="text-amber-300" />
        <span className="text-sm font-medium text-slate-200">邀请码管理</span>
        <button
          onClick={reload}
          className="ml-auto p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          title="刷新"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      <div className="flex items-center gap-2 flex-wrap border-b border-slate-800 pb-3">
        <span className="text-xs text-slate-500">生成：</span>
        <select
          value={newRole}
          onChange={(e) => setNewRole(e.target.value as Role)}
          className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1.5 text-xs"
        >
          {(roles.length ? roles.map((r) => r.name) : ROLE_OPTIONS).map((r) => (
            <option key={r} value={r}>
              {roleLabel(r)}
            </option>
          ))}
        </select>
        <span className="text-xs text-slate-500">有效</span>
        <input
          type="number"
          min={1}
          max={365}
          value={newDays}
          onChange={(e) => setNewDays(Math.max(1, Math.min(365, Number(e.target.value) || 7)))}
          className="bg-slate-950 border border-slate-700 rounded px-1.5 py-1.5 text-xs w-16"
        />
        <span className="text-xs text-slate-500">天（期内不限人数使用）</span>
        <button
          onClick={generate}
          disabled={busy}
          className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-xs font-medium transition-colors"
        >
          {busy ? '生成中…' : '生成邀请码'}
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-800">
              <th className="text-left py-2 pr-3 font-normal">邀请码</th>
              <th className="text-left py-2 pr-3 font-normal">注册角色</th>
              <th className="text-left py-2 pr-3 font-normal">状态</th>
              <th className="text-left py-2 pr-3 font-normal">到期时间</th>
              <th className="text-left py-2 pr-3 font-normal">已用</th>
              <th className="text-left py-2 pr-3 font-normal">创建人</th>
              <th className="text-left py-2 font-normal">操作</th>
            </tr>
          </thead>
          <tbody>
            {invs.map((inv) => (
              <tr key={inv.code} className="border-b border-slate-900">
                <td className="py-2 pr-3 font-mono text-xs text-amber-200 tracking-wider">
                  {inv.code}
                </td>
                <td className="py-2 pr-3 text-slate-300 text-xs">{roleLabel(inv.role)}</td>
                <td className="py-2 pr-3">{statusBadge(inv.status)}</td>
                <td className="py-2 pr-3 font-mono text-xs text-slate-500">
                  {inv.expires_at.slice(0, 16).replace('T', ' ')}
                </td>
                <td className="py-2 pr-3 text-xs text-slate-400">{inv.use_count} 人</td>
                <td className="py-2 pr-3 text-xs text-slate-500">{inv.created_by}</td>
                <td className="py-2">
                  <div className="flex items-center gap-1.5">
                    <button
                      title="复制邀请码"
                      onClick={() => copy(inv.code)}
                      className="p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                    >
                      <Copy size={13} />
                    </button>
                    <button
                      title={inv.status === 'revoked' ? '已撤销' : '撤销'}
                      disabled={inv.status === 'revoked'}
                      onClick={() => {
                        if (window.confirm(`确认撤销邀请码 ${inv.code}？撤销后立即无法使用`))
                          api
                            .revokeInvitation('/api', inv.code)
                            .then(() => {
                              setNotice('已撤销');
                              setErr('');
                              reload();
                            })
                            .catch((e) => setErr(e instanceof Error ? e.message : '撤销失败'));
                      }}
                      className="p-1.5 rounded text-slate-500 hover:text-rose-400 hover:bg-slate-800 disabled:opacity-30 disabled:hover:text-slate-500 transition-colors"
                    >
                      <Ban size={13} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!invs.length && (
              <tr>
                <td colSpan={7} className="py-4 text-center text-xs text-slate-600">
                  还没有邀请码，用上方表单生成一个
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="text-[11px] text-slate-600">
        注册页填有效邀请码即成为对应角色（永久）；过期/撤销后注册时会明确提示。期内同一邀请码可被多人使用。
      </div>

      {err && <div className="text-xs text-rose-400">{err}</div>}
      {notice && <div className="text-xs text-emerald-400">{notice}</div>}
    </div>
  );
}

type SettingsTab = 'users' | 'invitations' | 'roles' | 'connection';

const TABS: { key: SettingsTab; label: string; icon: typeof Users }[] = [
  { key: 'users', label: '用户管理', icon: Users },
  { key: 'invitations', label: '邀请码管理', icon: Ticket },
  { key: 'roles', label: '角色权限', icon: ShieldCheck },
  { key: 'connection', label: '数据连接', icon: Plug },
];

export function Shezhi() {
  const dsConfig = useStore((s) => s.dsConfig);
  const setDsConfig = useStore((s) => s.setDsConfig);
  const status = useStore((s) => s.status);
  const me = useStore((s) => s.me);
  const [tab, setTab] = useState<SettingsTab>('users');

  const [draft, setDraft] = useState<DataSourceConfig>(dsConfig);

  const apply = () => {
    setDsConfig(draft);
    dataSource.setConfig(draft);
  };

  const reconnect = () => {
    setDsConfig(draft);
    dataSource.setConfig(draft);
    dataSource.start();
  };

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="px-6 py-5 space-y-5">
        <h1 className="text-2xl font-bold">设置</h1>

        {/* 顶部 Tab：全宽下划线式 */}
        <div className="flex gap-1 border-b border-slate-800">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-1.5 px-4 py-2.5 -mb-px border-b-2 text-sm font-medium transition-colors ${
                tab === t.key
                  ? 'border-blue-500 text-blue-300'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <t.icon size={14} />
              {t.label}
            </button>
          ))}
        </div>

        <div className="space-y-5">
          {tab === 'users' && <UsersPanel />}

          {tab === 'invitations' && <InvitationsPanel />}

          {tab === 'roles' && <RolesPanel />}

          {tab === 'connection' && (
            <>
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
        <div>
          <label className="text-xs text-slate-400 uppercase tracking-wider mb-2 block">
            数据通道
          </label>
          <div className="p-3 rounded border bg-blue-600/10 border-blue-500/40 text-sm">
            <div className="font-medium">WebSocket 长连接</div>
            <div className="text-xs text-slate-500 mt-1">
              实时接收量化系统建议推送 + 行情快照定时广播；连接建立时 REST 自动补全初始数据，断线重连不丢数据。
            </div>
          </div>
        </div>

        <div>
          <label className="text-xs text-slate-400 uppercase tracking-wider mb-2 block">
            WebSocket 地址
          </label>
          <input
            value={draft.wsUrl}
            onChange={(e) => setDraft({ ...draft, wsUrl: e.target.value })}
            placeholder="ws://localhost:8000/ws"
            className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm font-mono focus:outline-none focus:border-blue-500"
          />
          <p className="text-xs text-slate-500 mt-2">
            默认同源：<code className="font-mono text-slate-400">/ws</code>。开发时 Vite proxy 转发到
            <code className="font-mono text-slate-400 ml-1">localhost:8000</code>，生产同域直连，无需修改。
          </p>
        </div>

        <div className="flex gap-2 pt-2">
          <button
            onClick={apply}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-md text-sm font-medium transition-colors"
          >
            应用并重连
          </button>
          <button
            onClick={reconnect}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-md text-sm font-medium transition-colors"
          >
            重连
          </button>
          <button
            onClick={() => {
              setDraft(DEFAULT_DS_CONFIG);
              setDsConfig(DEFAULT_DS_CONFIG);
              dataSource.setConfig(DEFAULT_DS_CONFIG);
            }}
            className="px-4 py-2 text-slate-400 hover:text-slate-200 text-sm transition-colors"
          >
            重置
          </button>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-3">
        <div className="text-xs text-slate-400 uppercase tracking-wider">
          当前状态
        </div>
        <ConnectionStatus />
        <p className="text-xs text-slate-500">
          {status === 'open'
            ? '长连接已建立：初始数据已通过 REST 补全，此后由服务端实时推送。'
            : status === 'connecting'
              ? '正在与后端建立长连接…（确认后端已启动并监听 /ws）'
              : '连接断开。将自动重连；请确认后端已启动。'}
        </p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
        <div className="text-xs text-slate-400 uppercase tracking-wider mb-3">
          REST 接口（仅用于连接建立时的初始数据加载）
        </div>
        <pre className="bg-slate-950 border border-slate-800 rounded p-3 text-xs text-slate-300 font-mono overflow-x-auto">
{`GET /api/sentiment
GET /api/sentiment/history?days=10
GET /api/pool/:name          # limit_up / limit_up_broken / yesterday_limit_up /
                             # super_stock / limit_down / new_stock / nearly_new
GET /api/newsflash?limit=50
GET /api/themes
GET /api/monitor             # 东财监管名单（重点监控 + 严重异动）
GET /api/advice?date=YYYY-MM-DD   # 量化系统建议（普通用户仅历史日期）
GET /api/advice/latest
GET /api/users               # 仅超管：用户列表
`}
        </pre>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
        <div className="text-xs text-slate-400 uppercase tracking-wider mb-3">
          WebSocket 协议（实时推送）
        </div>
        <pre className="bg-slate-950 border border-slate-800 rounded p-3 text-xs text-slate-300 font-mono overflow-x-auto">
{`// 后端 → 前端
{ "type": "sentiment",        "data": Sentiment }
{ "type": "sentiment_history","data": DailySnapshot[] }
{ "type": "pool",             "pool_name": "limit_up", "data": PoolResponse }
{ "type": "newsflash",        "data": NewsflashItem[] }
{ "type": "theme",            "data": Theme[] }
{ "type": "monitor",          "data": MonitorData }   // 东财监管名单定时广播
{ "type": "advice",           "data": DailyReport }   // 实时建议（普通用户不推送）
{ "type": "heartbeat",        "ts": 1757200000000 }

// 前端 → 后端
{ "type": "subscribe",   "channels": ["sentiment","pool","newsflash","themes","monitor","advice"] }
{ "type": "ping" }`}
        </pre>
        <div className="mt-3 text-xs text-slate-500">
          报告推送来自后端监听量化系统落盘目录（<code className="font-mono">QUANT_ADVICE_DIR</code>），
          调度器产出的竞价/盘中/盘后文件落盘即推送；行情快照由后端定时广播（约 30s）。
        </div>
      </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
