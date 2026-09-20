"""SQLite 持久层：用户 / 角色 / 邀请码（十万级用户设计）。

- 密码仅存 PBKDF2 哈希（werkzeug generate_password_hash），绝不明文
- roles 表化：内置三角色起步，为未来"admin 自定义角色 + 页面权限"预留
- invitations：期内不限人数使用，use_count 计数，invitation_uses 留审计明细
- role_pages 表本次仅建表预留，UI 后续实现
- WAL 模式 + 短连接：读多写少场景，十万级主键查询无压力
- 首次启动自动从 users.json 迁移（完成后改名 .migrated 防重复）
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

log = logging.getLogger("quant-web-db")

# 持久化目录：默认 backend/；Docker 部署用 QUANT_BACKEND_DATA 指到共享数据卷
_BACKEND_DATA = Path(os.environ.get("QUANT_BACKEND_DATA") or Path(__file__).parent)
DB_PATH = _BACKEND_DATA / "quant.db"
USERS_JSON = _BACKEND_DATA / "users.json"

# 内置角色（name, label, seq）；is_system=1 不可删除
SYSTEM_ROLES = [
    ("user", "普通用户", 0),
    ("advanced", "高级用户", 1),
    ("admin", "超管", 2),
]

# 邀请码字母表：去掉 0/O/1/I 等易混淆字符
_INVITE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

_conn_lock = threading.Lock()  # 写操作串行化（SQLite 单写者）


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db():
    """显式关闭的连接上下文（退出时 commit + close）。

    ⚠️ 不能用 `with sqlite3.connect() as conn`：它只提交事务、不关连接，
    高请求量下 fd 会累积到上限（Too many open files 实测踩坑）。
    """
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """建表 + 种子角色 + JSON 迁移 + 超管引导（幂等，启动时调用一次）。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS roles (
                name      TEXT PRIMARY KEY,
                label     TEXT NOT NULL,
                is_system INTEGER NOT NULL DEFAULT 0,
                seq       INTEGER NOT NULL DEFAULT 0,
                pages_configured INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS users (
                username      TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL REFERENCES roles(name),
                enabled       INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL,
                last_login_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
            CREATE TABLE IF NOT EXISTS invitations (
                code       TEXT PRIMARY KEY,
                role       TEXT NOT NULL REFERENCES roles(name),
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked    INTEGER NOT NULL DEFAULT 0,
                use_count  INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_inv_expires ON invitations(expires_at);
            CREATE TABLE IF NOT EXISTS invitation_uses (
                code     TEXT NOT NULL,
                username TEXT NOT NULL,
                used_at  TEXT NOT NULL,
                PRIMARY KEY (code, username)
            );
            -- 预留：每种角色可见的页面（page_key 对应前端路由，如 /advice）。
            -- 空行 = 未配置；配置后以本表为准，未配置角色沿用后端默认矩阵。
            CREATE TABLE IF NOT EXISTS role_pages (
                role     TEXT NOT NULL REFERENCES roles(name),
                page_key TEXT NOT NULL,
                PRIMARY KEY (role, page_key)
            );
            -- 7×24 快讯：唯一真增量数据，按上游 id 去重追加，保留 7 天
            CREATE TABLE IF NOT EXISTS news_items (
                id           INTEGER PRIMARY KEY,
                published_at TEXT,
                title        TEXT NOT NULL,
                summary      TEXT,
                stocks_json  TEXT,
                plates_json  TEXT,
                category     TEXT,
                fetched_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_news_pub ON news_items(published_at);
            -- 情绪日结：一天一行，盘中滚动修正，收盘定稿；保留 20 天
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                date         TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                finalized    INTEGER NOT NULL DEFAULT 0,
                updated_at   TEXT NOT NULL
            );
            -- 主题机会每日快照：当日覆盖，保留 7 天（供前端对比）
            CREATE TABLE IF NOT EXISTS theme_snapshots (
                date         TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            );
            -- 覆盖型 key 兜底快照：上游失败时回旧值 + 重启冷启动装载
            CREATE TABLE IF NOT EXISTS snapshots (
                key          TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                fetched_at   TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT OR IGNORE INTO roles(name, label, is_system, seq) VALUES (?, ?, 1, ?)",
            SYSTEM_ROLES,
        )
        # 旧库升级：roles 表缺 pages_configured 列则补
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(roles)").fetchall()}
        if "pages_configured" not in cols:
            conn.execute("ALTER TABLE roles ADD COLUMN pages_configured INTEGER NOT NULL DEFAULT 0")
    _migrate_json_users()
    _bootstrap_admin()


# ============================== JSON → SQLite 迁移 ==============================


def _migrate_json_users() -> None:
    """users.json 存在且 users 表为空 → 导入后改名 .migrated（幂等）。"""
    if not USERS_JSON.exists():
        return
    with _db() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if n:
        return
    try:
        data = json.loads(USERS_JSON.read_text(encoding="utf-8")).get("users", {})
    except Exception:
        log.exception("users.json 解析失败，跳过迁移")
        return
    with _conn_lock, _db() as conn:
        for name, u in data.items():
            conn.execute(
                "INSERT OR IGNORE INTO users(username, password_hash, role, enabled, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    name,
                    u.get("password_hash", ""),
                    u.get("role", "user"),
                    1 if u.get("enabled", True) else 0,
                    u.get("created_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
    USERS_JSON.rename(USERS_JSON.with_suffix(".json.migrated"))
    log.info("users.json → SQLite 迁移完成（%d 用户），原文件已改名 .migrated", len(data))


def _bootstrap_admin() -> None:
    """users 表为空时创建超管（沿用 ADMIN_USERNAME / ADMIN_PASSWORD 环境变量）。"""
    import os

    with _db() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if n:
        return
    name = os.environ.get("ADMIN_USERNAME", "admin").strip() or "admin"
    pw = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(8)
    with _conn_lock, _db() as conn:
        conn.execute(
            "INSERT INTO users(username, password_hash, role, enabled, created_at) VALUES (?, ?, 'admin', 1, ?)",
            (name, generate_password_hash(pw), datetime.now(timezone.utc).isoformat()),
        )
    if os.environ.get("ADMIN_PASSWORD"):
        log.info("已创建超管 %s（密码来自 ADMIN_PASSWORD）", name)
    else:
        log.warning("已创建超管 %s / %s —— 请尽快登录并在设置页修改密码", name, pw)


# ============================== 用户 ==============================


def get_user(name: str) -> dict | None:
    with _db() as conn:
        r = conn.execute("SELECT * FROM users WHERE username = ?", (name,)).fetchone()
    return dict(r) if r else None


def list_users() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT u.username, u.role, r.label AS role_label, u.enabled, u.created_at, u.last_login_at"
            " FROM users u LEFT JOIN roles r ON r.name = u.role ORDER BY u.created_at, u.username"
        ).fetchall()
    return [dict(r) for r in rows]


def count_users() -> int:
    with _db() as conn:
        return conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def create_user(name: str, password_hash: str, role: str) -> None:
    with _conn_lock, _db() as conn:
        conn.execute(
            "INSERT INTO users(username, password_hash, role, enabled, created_at) VALUES (?, ?, ?, 1, ?)",
            (name, password_hash, role, datetime.now(timezone.utc).isoformat()),
        )


def update_user(name: str, **fields) -> None:
    """fields: role / enabled / password_hash / last_login_at（白名单键）。"""
    allowed = {"role", "enabled", "password_hash", "last_login_at"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    cols = ", ".join(f"{k} = ?" for k in sets)
    with _conn_lock, _db() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE username = ?", (*sets.values(), name))


def delete_user(name: str) -> None:
    with _conn_lock, _db() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (name,))


def enabled_admins_exclude(name: str) -> int:
    """除 name 外启用中的超管数（保护最后一个超管）。"""
    with _db() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND enabled=1 AND username != ?",
            (name,),
        ).fetchone()["c"]


# ============================== 角色 ==============================

# 页面 key 与前端导航一一对应（settings/quantconfig 仅 admin，不参与非 admin 配置）
ALL_PAGE_KEYS = [
    "overview", "advice", "review", "pools", "ladder",
    "newsflash", "themes", "monitor", "quantconfig", "settings",
]


def list_roles() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT name, label, is_system, seq, pages_configured FROM roles ORDER BY seq, name"
        ).fetchall()
        page_rows = conn.execute("SELECT role, page_key FROM role_pages").fetchall()
    pages_by_role: dict[str, list[str]] = {}
    for r in page_rows:
        pages_by_role.setdefault(r["role"], []).append(r["page_key"])
    out = []
    for r in rows:
        d = dict(r)
        d["pages"] = pages_by_role.get(r["name"], [])
        out.append(d)
    return out


def role_exists(name: str) -> bool:
    with _db() as conn:
        return conn.execute("SELECT 1 FROM roles WHERE name = ?", (name,)).fetchone() is not None


def create_role(name: str, label: str) -> None:
    """自定义角色：seq 排系统角色之后，默认未配置页面（回退默认矩阵）。"""
    with _conn_lock, _db() as conn:
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS s FROM roles").fetchone()["s"]
        conn.execute(
            "INSERT INTO roles(name, label, is_system, seq, pages_configured) VALUES (?, ?, 0, ?, 0)",
            (name, label, seq),
        )


def delete_role(name: str) -> None:
    """删角色：role_pages 级联清；引用它的**无效**邀请码（已撤销/过期）一并删除
    （有效邀请码已在 main 层 guard 拦截，不会走到这里）。"""
    with _conn_lock, _db() as conn:
        conn.execute("DELETE FROM role_pages WHERE role = ?", (name,))
        conn.execute(
            "DELETE FROM invitations WHERE role = ? AND (revoked = 1 OR expires_at <= ?)",
            (name, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute("DELETE FROM roles WHERE name = ?", (name,))


def role_in_use(name: str) -> dict:
    """角色被引用情况：绑定的用户数 / 引用它的**有效**邀请码数（已撤销/过期不算）。"""
    with _db() as conn:
        users = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = ?", (name,)).fetchone()["c"]
        invs = conn.execute(
            "SELECT COUNT(*) AS c FROM invitations WHERE role = ? AND revoked = 0"
            " AND expires_at > ?",
            (name, datetime.now(timezone.utc).isoformat()),
        ).fetchone()["c"]
    return {"users": users, "invitations": invs}


# ---------- 角色页面权限 ----------


def get_role_pages(role: str) -> list[str]:
    with _db() as conn:
        rows = conn.execute("SELECT page_key FROM role_pages WHERE role = ?", (role,)).fetchall()
    return [r["page_key"] for r in rows]


def set_role_pages(role: str, pages: list[str]) -> None:
    """全量覆盖勾选；pages 为空列表也视为"已配置为空"。"""
    valid = set(ALL_PAGE_KEYS)
    clean = sorted({p for p in pages if p in valid})
    with _conn_lock, _db() as conn:
        conn.execute("DELETE FROM role_pages WHERE role = ?", (role,))
        conn.executemany(
            "INSERT OR IGNORE INTO role_pages(role, page_key) VALUES (?, ?)",
            [(role, p) for p in clean],
        )
        conn.execute("UPDATE roles SET pages_configured = 1 WHERE name = ?", (role,))


def reset_role_pages(role: str) -> None:
    """恢复默认：清配置行 + pages_configured 归零。"""
    with _conn_lock, _db() as conn:
        conn.execute("DELETE FROM role_pages WHERE role = ?", (role,))
        conn.execute("UPDATE roles SET pages_configured = 0 WHERE name = ?", (role,))


def pages_for_role(role: str) -> list[str]:
    """该角色实际可见页面：已配置用配置，未配置回退默认矩阵。"""
    with _db() as conn:
        r = conn.execute(
            "SELECT pages_configured FROM roles WHERE name = ?", (role,)
        ).fetchone()
    if r and r["pages_configured"]:
        return get_role_pages(role)
    if role == "admin":
        return list(ALL_PAGE_KEYS)
    return [p for p in ALL_PAGE_KEYS if p not in ("settings", "quantconfig")]


# ============================== 邀请码 ==============================


def gen_invite_code() -> str:
    """XXXX-XXXX，8 位去混淆字母数字（约 23^8 ≈ 7.8 亿组合，7 天窗口内可暴力空间足够大）。"""
    body = "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(8))
    return f"{body[:4]}-{body[4:]}"


def create_invitation(role: str, created_by: str, days: int = 7) -> dict:
    code = gen_invite_code()
    now = datetime.now(timezone.utc)
    with _conn_lock, _db() as conn:
        while conn.execute("SELECT 1 FROM invitations WHERE code = ?", (code,)).fetchone():
            code = gen_invite_code()  # 撞码重生成（概率极低）
        conn.execute(
            "INSERT INTO invitations(code, role, created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (code, role, created_by, now.isoformat(), (now + timedelta(days=days)).isoformat()),
        )
    return get_invitation(code)


def get_invitation(code: str) -> dict | None:
    with _db() as conn:
        r = conn.execute("SELECT * FROM invitations WHERE code = ?", (code,)).fetchone()
    return dict(r) if r else None


def list_invitations() -> list[dict]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT i.*, r.label AS role_label,"
            " (SELECT COUNT(*) FROM invitation_uses x WHERE x.code = i.code) AS use_count"
            " FROM invitations i LEFT JOIN roles r ON r.name = i.role"
            " ORDER BY i.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_invitation(code: str) -> bool:
    with _conn_lock, _db() as conn:
        cur = conn.execute("UPDATE invitations SET revoked = 1 WHERE code = ?", (code,))
    return cur.rowcount > 0


def check_invitation(code: str) -> tuple[str, str | None]:
    """校验邀请码。返回 (role, 错误提示)；错误时 role 为 ''。"""
    inv = get_invitation((code or "").strip().upper())
    if inv is None:
        return "", "邀请码无效"
    if inv["revoked"]:
        return "", "邀请码已被撤销"
    if datetime.now(timezone.utc) > datetime.fromisoformat(inv["expires_at"]):
        return "", f"邀请码已过期（{inv['expires_at'][:10]}）"
    return inv["role"], None


def consume_invitation(code: str, username: str) -> None:
    """注册成功后调用：计数 + 审计明细。"""
    code = (code or "").strip().upper()
    with _conn_lock, _db() as conn:
        conn.execute("UPDATE invitations SET use_count = use_count + 1 WHERE code = ?", (code,))
        conn.execute(
            "INSERT OR IGNORE INTO invitation_uses(code, username, used_at) VALUES (?, ?, ?)",
            (code, username, datetime.now(timezone.utc).isoformat()),
        )


# ============================== 行情数据入库 ==============================


def save_news(items: list[dict]) -> int:
    """快讯增量入库（按上游 id 去重），返回新插入条数；顺手清理 7 天前的旧闻。"""
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    with _conn_lock, _db() as conn:
        for m in items:
            cur = conn.execute(
                "INSERT OR IGNORE INTO news_items(id, published_at, title, summary,"
                " stocks_json, plates_json, category, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    m.get("id"),
                    str(m.get("published_at") or ""),
                    m.get("title") or "",
                    m.get("summary"),
                    json.dumps(m.get("stocks") or [], ensure_ascii=False),
                    json.dumps(m.get("plates") or [], ensure_ascii=False),
                    m.get("category") or "要闻",
                    now,
                ),
            )
            inserted += cur.rowcount
        conn.execute(
            "DELETE FROM news_items WHERE fetched_at < ?",
            ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),),
        )
    return inserted


def list_news(limit: int = 50) -> list[dict]:
    """快讯按发布时间倒序取 N 条（7 天内）。输出兼容前端原 created_at 字段。"""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM news_items ORDER BY published_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        pub = d.pop("published_at") or ""
        try:
            d["created_at"] = int(pub)  # 上游原始为 Unix 秒
        except (TypeError, ValueError):
            d["created_at"] = pub
        d["stocks"] = json.loads(d.pop("stocks_json") or "[]")
        d["plates"] = json.loads(d.pop("plates_json") or "[]")
        out.append(d)
    return out


def save_daily_snapshot(date: str, payload: dict, finalized: bool = False) -> None:
    """情绪日结：当日覆盖（盘中滚动修正），finalized 后不再覆盖。"""
    with _conn_lock, _db() as conn:
        if finalized:
            if payload:
                # 定稿：新行带 payload 插入；已有行（盘中滚动）只置位，保留其最新 payload
                conn.execute(
                    "INSERT INTO daily_snapshots(date, payload_json, finalized, updated_at)"
                    " VALUES (?, ?, 1, ?)"
                    " ON CONFLICT(date) DO UPDATE SET finalized = 1",
                    (date, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
                )
            else:
                # 空 payload（如 15:30 定稿哨兵）：行存在才置位，不产生空行
                conn.execute(
                    "UPDATE daily_snapshots SET finalized = 1 WHERE date = ? AND finalized = 0",
                    (date,),
                )
        else:
            conn.execute(
                "INSERT INTO daily_snapshots(date, payload_json, finalized, updated_at)"
                " VALUES (?, ?, 0, ?)"
                " ON CONFLICT(date) DO UPDATE SET payload_json = excluded.payload_json,"
                " updated_at = excluded.updated_at WHERE finalized = 0",
                (date, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )
        # 保留最近 20 个自然日（含今天）
        conn.execute(
            "DELETE FROM daily_snapshots WHERE date < ?",
            ((datetime.now(timezone.utc) - timedelta(days=19)).strftime("%Y-%m-%d"),),
        )


def list_daily_snapshots(days: int = 20) -> list[dict]:
    """返回 [{date, last, mean, finalized}]，按日期升序。"""
    with _db() as conn:
        rows = conn.execute(
            "SELECT date, payload_json, finalized FROM daily_snapshots"
            " ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["payload_json"])
        d["date"] = r["date"]
        d["finalized"] = bool(r["finalized"])
        out.append(d)
    out.reverse()
    return out


def save_theme_snapshot(date: str, payload: list) -> None:
    """主题每日快照：当日覆盖，保留 7 天供前端对比。"""
    with _conn_lock, _db() as conn:
        conn.execute(
            "INSERT INTO theme_snapshots(date, payload_json, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(date) DO UPDATE SET payload_json = excluded.payload_json,"
            " updated_at = excluded.updated_at",
            (date, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
        # 保留最近 7 个自然日（含今天）
        conn.execute(
            "DELETE FROM theme_snapshots WHERE date < ?",
            ((datetime.now(timezone.utc) - timedelta(days=6)).strftime("%Y-%m-%d"),),
        )


def list_theme_dates(days: int = 7) -> list[str]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT date FROM theme_snapshots ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
    return [r["date"] for r in rows]


def get_theme_snapshot(date: str) -> list | None:
    with _db() as conn:
        r = conn.execute(
            "SELECT payload_json FROM theme_snapshots WHERE date = ?", (date,)
        ).fetchone()
    return json.loads(r["payload_json"]) if r else None


def save_snapshot(key: str, payload) -> None:
    """覆盖型 key 的兜底快照（上游失败回旧值 / 重启冷启动）。"""
    with _conn_lock, _db() as conn:
        conn.execute(
            "INSERT INTO snapshots(key, payload_json, fetched_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET payload_json = excluded.payload_json,"
            " fetched_at = excluded.fetched_at",
            (key, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )


def get_snapshot(key: str):
    with _db() as conn:
        r = conn.execute("SELECT payload_json FROM snapshots WHERE key = ?", (key,)).fetchone()
    return json.loads(r["payload_json"]) if r else None


def load_all_snapshots() -> dict:
    """冷启动：一次读出全部兜底快照。"""
    with _db() as conn:
        rows = conn.execute("SELECT key, payload_json FROM snapshots").fetchall()
    return {r["key"]: json.loads(r["payload_json"]) for r in rows}
