"""
选股通看板 · 后端代理 (Flask 版)

为前端提供 REST 接口，代理选股通 (xuangutong.com.cn) 真实数据。
- 解决浏览器 CORS 限制
- 集中缓存（避免打选股通）
- 集中管理 x-ivanka-token（不进代码/日志）

WebSocket (/ws)：
- 前端长连接，实时推送 advice（选股建议）
- advice 来源：监听量化系统落盘目录（QUANT_ADVICE_DIR），零侵入 quant-system
- 每 25s 广播 heartbeat 保活

启动：
    XUANGUTONG_IVANKA_TOKEN='<token>' python3 main.py
    QUANT_ADVICE_DIR='../quant-system/data/advice' python3 main.py
"""
import os
import re
import time
import json
import secrets
import hashlib
import logging
import threading
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from flask import Flask, jsonify, request, session, send_from_directory, Response
from flask_sock import Sock
from werkzeug.security import generate_password_hash, check_password_hash
import io

# 图形验证码（轻量 PIL 绘制，无第三方依赖）
try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

# ====== 日志 ======
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("quant-web-backend")

# ====== token ======
TOKEN = os.environ.get("XUANGUTONG_IVANKA_TOKEN", "")
if not TOKEN:
    # 兜底：从 quant-system/.env 读取（唯一密钥源，避免多副本）
    import pathlib

    _qs_env = pathlib.Path(__file__).resolve().parents[2] / "quant-system" / ".env"
    if _qs_env.exists():
        for _line in _qs_env.read_text(encoding="utf-8").splitlines():
            if _line.startswith("XUANGUTONG_IVANKA_TOKEN="):
                TOKEN = _line.split("=", 1)[1].strip()
                break
log.info("token loaded: %s", "yes" if TOKEN else "NO")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ====== Flask ======
# 注意：Funnel 模式同源部署，不需要 CORS；开发跨域请用 Vite proxy（已在 vite.config.js 配置）
# 如确需启用 CORS，设置环境变量 ENABLE_CORS=1 即可（默认关闭，避免公网任意来源）
app = Flask(__name__)
if os.environ.get("ENABLE_CORS") == "1":
    from flask_cors import CORS
    CORS(app, supports_credentials=True)

# ====== 鉴权（角色：user 普通用户 / advanced 高级用户 / admin 超管） ======
# - 持久层：SQLite（db.py），users/roles/invitations 表；密码 PBKDF2 哈希
# - 首次启动自动从 users.json 迁移，并引导超管（ADMIN_USERNAME / ADMIN_PASSWORD）
# - 普通用户：实时选股建议不可见（WS 无 advice 频道 + 当日 REST 403），仅历史
# - 邀请码：admin 生成，7 天内不限人数，注册时填写即获对应角色（永久）
import db as dbm

ROLE_USER, ROLE_ADVANCED, ROLE_ADMIN = "user", "advanced", "admin"
ROLE_LABELS = {ROLE_USER: "普通用户", ROLE_ADVANCED: "高级用户", ROLE_ADMIN: "超管"}
_login_fails = {}  # ip -> [连续失败次数, 锁定截止时间戳]


def _secret_key() -> str:
    """SECRET_KEY 环境变量优先；否则持久化随机密钥到 .secret_key（重启后会话不失效）"""
    key = os.environ.get("SECRET_KEY", "")
    if key:
        return key
    # QUANT_BACKEND_DATA：Docker 部署时指到共享数据卷，密钥随卷持久化
    f = Path(os.environ.get("QUANT_BACKEND_DATA") or Path(__file__).parent) / ".secret_key"
    if not f.exists():
        f.write_text(secrets.token_hex(32), encoding="utf-8")
        log.warning("SECRET_KEY 未设置，已生成并保存到 %s", f)
    return f.read_text(encoding="utf-8").strip()


app.secret_key = _secret_key()
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Funnel 公网部署走 HTTPS，cookie 必须标 Secure（防被嗅探）
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True


def current_user() -> dict | None:
    name = session.get("user")
    if not name:
        return None
    u = dbm.get_user(name)
    if not u or not u["enabled"]:
        return None
    return {
        "username": name,
        "role": u["role"],
        "pages": dbm.pages_for_role(u["role"]),  # 该角色可见页面（前端据此过滤菜单）
    }


def _check_login_rate(ip: str) -> str | None:
    """失败≥5 次锁 5 分钟；返回锁定提示或 None"""
    fails, until = _login_fails.get(ip, [0, 0.0])
    if time.time() < until:
        return f"尝试过多，请 {int(until - time.time()) + 1} 秒后再试"
    return None


def _record_login_fail(ip: str, ok: bool) -> None:
    if ok:
        _login_fails.pop(ip, None)
        return
    fails, until = _login_fails.get(ip, [0, 0.0])
    fails += 1
    _login_fails[ip] = [fails, time.time() + 300 if fails >= 5 else 0.0]


def _validate_username(name: str) -> str | None:
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", name or ""):
        return "用户名需 3-32 位字母/数字/下划线"
    return None


def _validate_password(pw: str) -> str | None:
    if not pw or len(pw) < 6:
        return "密码至少 6 位"
    return None


PUBLIC_API = {"/api/login", "/api/register", "/api/me", "/api/health", "/api/health/", "/api/captcha"}


# ====== 图形验证码 ======
_CAPTCHA_CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 去掉 0/O/1/I 等易混淆字符
_CAPTCHA_LEN = 4
_CAPTCHA_TTL = 180  # 3 分钟过期


def _gen_captcha_text() -> str:
    return "".join(secrets.choice(_CAPTCHA_CHARS) for _ in range(_CAPTCHA_LEN))


def _draw_captcha_png(text: str) -> bytes:
    """纯 PIL 画一张验证码图（不引入第三方 captcha 库）"""
    if not _HAS_PIL:
        raise RuntimeError("PIL 未安装，无法生成图形验证码")
    w, h = 120, 44
    img = Image.new("RGB", (w, h), (245, 247, 250))
    draw = ImageDraw.Draw(img)
    # 字体（macOS 自带，依次尝试；明确抛错以便调试）
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, 26)
            break
        except Exception:
            continue
    if font is None:
        # 最后 fallback：用 PIL 内置默认字体（PIL 10+ 支持 size 参数）
        font = ImageFont.load_default(size=26)
    # 干扰线
    for _ in range(4):
        x1, y1 = secrets.randbelow(w), secrets.randbelow(h)
        x2, y2 = secrets.randbelow(w), secrets.randbelow(h)
        draw.line([(x1, y1), (x2, y2)], fill=(180, 190, 210), width=1)
    # 干扰点
    for _ in range(40):
        x, y = secrets.randbelow(w), secrets.randbelow(h)
        draw.point((x, y), fill=(160, 170, 190))
    # 文字（一次画完，用 anchor 防位置漂移）
    try:
        draw.text((10, 4), text, font=font, fill=(30, 40, 60))
    except Exception:
        # 某些字体不支持中文 anchor 位置，退回到逐字绘制
        for i, ch in enumerate(text):
            x = 15 + i * 22 + secrets.randbelow(3) - 1
            y = 6 + secrets.randbelow(3) - 1
            draw.text((x, y), ch, font=font, fill=(30, 40, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.route("/api/captcha")
def captcha():
    """图形验证码：返回 PNG，答案写 session（一次性）"""
    if not _HAS_PIL:
        return jsonify({"error": "server-misconfigured: PIL 未安装"}), 500
    text = _gen_captcha_text()
    session["captcha_text"] = text.upper()
    session["captcha_at"] = time.time()
    png = _draw_captcha_png(text)
    resp = Response(png, mimetype="image/png")
    # 防缓存，强制每次刷新拿新图
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


def _check_captcha(answer: str) -> str | None:
    """校验并清空（一次性）"""
    expected = session.pop("captcha_text", None)
    at = session.pop("captcha_at", 0)
    if not expected:
        return "请先获取验证码"
    if time.time() - float(at) > _CAPTCHA_TTL:
        return "验证码已过期，请刷新"
    if not answer or answer.strip().upper() != expected:
        return "验证码错误"
    return None


@app.before_request
def _auth_guard():
    p = request.path
    if not p.startswith("/api/"):
        return None  # 静态资源/SPA 入口不拦（登录页是前端路由）
    if p in PUBLIC_API:
        return None
    me = current_user()
    if me is None:
        return jsonify({"error": "unauthorized"}), 401
    if p.startswith("/api/users") and me["role"] != ROLE_ADMIN:
        return jsonify({"error": "forbidden: 仅超管可管理用户"}), 403
    if (p.startswith("/api/invitations") or p.startswith("/api/roles")) \
            and me["role"] != ROLE_ADMIN:
        return jsonify({"error": "forbidden: 仅超管可管理邀请码"}), 403
    if (p.startswith("/api/config") or p.startswith("/api/datasources")
            or p == "/api/strategy/test") and me["role"] != ROLE_ADMIN:
        return jsonify({"error": "forbidden: 仅超管可使用量化配置与沙箱"}), 403
    # 普通用户：实时选股建议不可见，仅可查严格早于今天的历史
    if me["role"] == ROLE_USER and p.startswith("/api/advice"):
        today = datetime.now().strftime("%Y-%m-%d")
        if p == "/api/advice/latest" or (request.args.get("date") or today) >= today:
            return jsonify({"error": "forbidden: 普通用户仅可查看历史建议"}), 403
    return None


@app.route("/api/register", methods=["POST"])
def register():
    """开放注册（必须带图形验证码）。
    不填邀请码 → 普通用户；填有效邀请码 → 邀请码指定角色（永久）。
    无效/已撤销/已过期分别给出明确提示。"""
    body = request.get_json(silent=True) or {}
    name = (body.get("username") or "").strip()
    pw = body.get("password") or ""
    captcha_answer = body.get("captcha") or ""
    invite_code = (body.get("invite_code") or "").strip().upper()
    # 强制校验验证码（包括本机；本地开发想豁免可设环境变量 DISABLE_CAPTCHA=1）
    if os.environ.get("DISABLE_CAPTCHA") != "1":
        if err := _check_captcha(captcha_answer):
            return jsonify({"error": err}), 400
    if err := _validate_username(name):
        return jsonify({"error": err}), 400
    if err := _validate_password(pw):
        return jsonify({"error": err}), 400
    role = ROLE_USER
    if invite_code:
        role, inv_err = dbm.check_invitation(invite_code)
        if inv_err:
            return jsonify({"error": inv_err}), 400
    if dbm.get_user(name):
        return jsonify({"error": "用户名已存在"}), 400
    dbm.create_user(name, generate_password_hash(pw), role)
    if invite_code:
        dbm.consume_invitation(invite_code, name)
    session.permanent = True
    session["user"] = name
    log.info("新用户注册: %s（%s，邀请码=%s, from %s）",
             name, role, invite_code or "无", request.remote_addr)
    return jsonify({"username": name, "role": role, "pages": dbm.pages_for_role(role)})


@app.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    name = (body.get("username") or "").strip()
    pw = body.get("password") or ""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
    if err := _check_login_rate(ip):
        return jsonify({"error": err}), 429
    u = dbm.get_user(name)
    ok = bool(u and u["enabled"] and check_password_hash(u["password_hash"], pw))
    _record_login_fail(ip, ok)
    if not ok:
        return jsonify({"error": "用户名或密码错误，或账号已停用"}), 401
    dbm.update_user(name, last_login_at=now_iso())
    session.permanent = True
    session["user"] = name
    log.info("登录成功: %s", name)
    return jsonify({"username": name, "role": u["role"], "pages": dbm.pages_for_role(u["role"])})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    return jsonify({"ok": True})


@app.route("/api/me")
def me():
    return jsonify({"user": current_user()})


@app.route("/api/roles")
def roles_list():
    """角色列表（admin）：含每角色的页面权限配置。"""
    return jsonify(dbm.list_roles())


@app.route("/api/roles", methods=["POST"])
def roles_create():
    """新建自定义角色：{name, label}；name 2-20 位小写字母/数字/下划线。"""
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip().lower()
    label = (body.get("label") or "").strip()
    if not re.fullmatch(r"[a-z0-9_]{2,20}", name):
        return jsonify({"error": "角色标识需 2-20 位小写字母/数字/下划线"}), 400
    if not label or len(label) > 20:
        return jsonify({"error": "显示名需 1-20 个字"}), 400
    if name in ROLE_LABELS:
        return jsonify({"error": "该角色标识为系统保留"}), 400
    if dbm.role_exists(name):
        return jsonify({"error": "角色已存在"}), 400
    dbm.create_role(name, label)
    log.info("超管新建角色: %s（%s）", name, label)
    return jsonify({"name": name, "label": label, "is_system": 0, "pages_configured": 0, "pages": []})


@app.route("/api/roles/<name>", methods=["DELETE"])
def roles_delete(name: str):
    r = next((x for x in dbm.list_roles() if x["name"] == name), None)
    if r is None:
        return jsonify({"error": "角色不存在"}), 404
    if r["is_system"]:
        return jsonify({"error": "系统内置角色不可删除"}), 400
    usage = dbm.role_in_use(name)
    if usage["users"]:
        return jsonify({"error": f"该角色仍有 {usage['users']} 个用户，请先在用户管理中迁移"}), 400
    if usage["invitations"]:
        return jsonify({"error": f"该角色被 {usage['invitations']} 个邀请码引用，请先撤销"}), 400
    dbm.delete_role(name)
    log.info("超管删除角色: %s", name)
    return jsonify({"ok": True})


@app.route("/api/roles/<name>/pages", methods=["PUT"])
def roles_set_pages(name: str):
    """保存角色可见页面：{pages: [...]} 或 {reset: true} 恢复默认。"""
    if not dbm.role_exists(name):
        return jsonify({"error": "角色不存在"}), 404
    body = request.get_json(silent=True) or {}
    if body.get("reset"):
        dbm.reset_role_pages(name)
        log.info("超管恢复角色默认页面: %s", name)
        return jsonify({"ok": True, "pages_configured": 0, "pages": []})
    pages = body.get("pages") or []
    invalid = [p for p in pages if p not in dbm.ALL_PAGE_KEYS]
    if invalid:
        return jsonify({"error": f"未知页面 key: {', '.join(invalid)}"}), 400
    if name != ROLE_ADMIN and "settings" in pages:
        return jsonify({"error": "settings 页面仅超管可用"}), 400
    if name == ROLE_ADMIN:
        return jsonify({"error": "超管始终可见全部页面，无需配置"}), 400
    dbm.set_role_pages(name, pages)
    log.info("超管配置角色页面: %s → %s", name, pages)
    return jsonify({"ok": True, "pages_configured": 1, "pages": dbm.get_role_pages(name)})


@app.route("/api/users")
def users_list():
    return jsonify(dbm.list_users())


@app.route("/api/users", methods=["POST"])
def users_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("username") or "").strip()
    pw = body.get("password") or ""
    role = body.get("role", ROLE_USER)
    if err := _validate_username(name):
        return jsonify({"error": err}), 400
    if err := _validate_password(pw):
        return jsonify({"error": err}), 400
    if not dbm.role_exists(role):
        return jsonify({"error": "无效角色"}), 400
    if dbm.get_user(name):
        return jsonify({"error": "用户名已存在"}), 400
    dbm.create_user(name, generate_password_hash(pw), role)
    log.info("超管创建用户: %s（%s）", name, role)
    return jsonify({"username": name, "role": role, "enabled": True})


@app.route("/api/users/<name>", methods=["PATCH"])
def users_update(name: str):
    body = request.get_json(silent=True) or {}
    me_name = session.get("user")
    u = dbm.get_user(name)
    if not u:
        return jsonify({"error": "用户不存在"}), 404
    if "role" in body:
        if not dbm.role_exists(body["role"]):
            return jsonify({"error": "无效角色"}), 400
        if name == me_name and body["role"] != ROLE_ADMIN:
            return jsonify({"error": "不能降级自己的超管角色"}), 400
        dbm.update_user(name, role=body["role"])
    if "enabled" in body:
        if name == me_name and not body["enabled"]:
            return jsonify({"error": "不能停用自己"}), 400
        if not body["enabled"] and u["role"] == ROLE_ADMIN and u["enabled"] \
                and dbm.enabled_admins_exclude(name) == 0:
            return jsonify({"error": "不能停用最后一个启用的超管"}), 400
        dbm.update_user(name, enabled=1 if body["enabled"] else 0)
    if "password" in body:
        if err := _validate_password(body["password"]):
            return jsonify({"error": err}), 400
        dbm.update_user(name, password_hash=generate_password_hash(body["password"]))
    log.info("超管更新用户: %s", name)
    return jsonify({"ok": True})


@app.route("/api/users/<name>", methods=["DELETE"])
def users_delete(name: str):
    me_name = session.get("user")
    u = dbm.get_user(name)
    if not u:
        return jsonify({"error": "用户不存在"}), 404
    if name == me_name:
        return jsonify({"error": "不能删除自己"}), 400
    if u["role"] == ROLE_ADMIN and u["enabled"] and dbm.enabled_admins_exclude(name) == 0:
        return jsonify({"error": "不能删除最后一个启用的超管"}), 400
    dbm.delete_user(name)
    log.info("超管删除用户: %s", name)
    return jsonify({"ok": True})


# ====================== 邀请码（admin） ======================
def _invite_status(inv: dict) -> str:
    if inv["revoked"]:
        return "revoked"
    now = datetime.now(timezone.utc)
    return "expired" if now > datetime.fromisoformat(inv["expires_at"]) else "active"


@app.route("/api/invitations")
def invitations_list():
    return jsonify([{**inv, "status": _invite_status(inv)} for inv in dbm.list_invitations()])


@app.route("/api/invitations", methods=["POST"])
def invitations_create():
    """生成邀请码：{role?, days?}，默认 advanced / 7 天；有效期内不限人数使用。"""
    body = request.get_json(silent=True) or {}
    role = body.get("role", ROLE_ADVANCED)
    if not dbm.role_exists(role):
        return jsonify({"error": "无效角色"}), 400
    try:
        days = max(1, min(365, int(body.get("days", 7))))
    except (TypeError, ValueError):
        days = 7
    inv = dbm.create_invitation(role, session.get("user") or "?", days)
    log.info("超管生成邀请码: %s（%s，%d 天）", inv["code"], role, days)
    return jsonify({**inv, "status": "active"})


@app.route("/api/invitations/<code>/revoke", methods=["POST"])
def invitations_revoke(code: str):
    if not dbm.revoke_invitation(code.upper()):
        return jsonify({"error": "邀请码不存在"}), 404
    log.info("超管撤销邀请码: %s", code.upper())
    return jsonify({"ok": True})


# ====== 持久层初始化：建表 / JSON 迁移 / 超管引导 ======
dbm.init_db()

# ====== WebSocket (flask-sock) ======
sock = Sock(app)

# WS 频道（与前端协议一致）
WS_CHANNELS = {"sentiment", "pool", "newsflash", "themes", "monitor", "advice", "ladder"}

_ws_lock = threading.Lock()
_ws_clients = {}  # id(conn) -> {"ws": conn, "channels": set}


def ws_register(conn, channels=None, role=ROLE_ADMIN):
    with _ws_lock:
        _ws_clients[id(conn)] = {
            "ws": conn, "channels": set(channels or WS_CHANNELS), "role": role,
        }


def ws_unregister(conn):
    with _ws_lock:
        _ws_clients.pop(id(conn), None)


def ws_broadcast(msg, channel=None):
    """向订阅了 channel 的客户端广播；channel=None 表示全部"""
    with _ws_lock:
        targets = [
            c for c in _ws_clients.values()
            if channel is None or channel in c["channels"]
        ]
    if not targets:
        return
    payload = json.dumps(msg, ensure_ascii=False)
    for c in targets:
        try:
            c["ws"].send(payload)
        except Exception:
            ws_unregister(c["ws"])


def ws_heartbeat_loop(interval=25):
    """服务端心跳：保活 + 让前端检测半开连接"""
    while True:
        ws_broadcast({"type": "heartbeat", "ts": int(time.time() * 1000)})
        time.sleep(interval)


# ====== 上游接口故障告警 ======
# 引擎任务失败（task_error 文件）与后端自身上游拉取失败都会转为 alert 广播
_upstream_errors: dict = {}  # source -> {"message": str, "ts": float}
_upstream_err_lock = threading.Lock()
_alert_last_ts: dict = {}  # source -> 上次广播时间（同源 5 分钟节流）

ALERT_THROTTLE_S = 300


def _note_upstream_error(source: str, exc: Exception) -> None:
    """getter 上游拉取失败时记录，由 data_refresh_loop 转为 alert 广播。"""
    with _upstream_err_lock:
        prev = _upstream_errors.get(source)
        _upstream_errors[source] = {"message": str(exc)[:200], "ts": time.time()}
    if prev is None:
        log.error("上游接口故障（将告警）: %s %s", source, exc)


def _drain_upstream_alerts() -> list:
    """取自上次广播后新出现的上游错误 → alert 消息（同源节流）。"""
    out = []
    now = time.time()
    with _upstream_err_lock:
        for source, info in _upstream_errors.items():
            if info["ts"] <= _alert_last_ts.get(source, 0):
                continue
            if now - _alert_last_ts.get(source, 0) < ALERT_THROTTLE_S:
                continue
            _alert_last_ts[source] = now
            out.append({
                "type": "alert", "source": source,
                "message": info["message"], "ts": int(now * 1000),
            })
    return out


def engine_task_error_to_alert(j: dict) -> dict:
    """引擎 task_error 报告 → 前端 alert 消息。"""
    task = j.get("task") or "unknown"
    return {
        "type": "alert",
        "source": f"engine:{task}",
        "message": j.get("error") or "量化引擎任务失败",
        "ts": int(time.time() * 1000),
    }


@sock.route("/ws")
def ws_endpoint(conn):
    me = current_user()
    if me is None:
        # 未登录：拒绝握手（前端登录后才会建立连接）
        try:
            conn.send(json.dumps({"type": "hello", "message": "unauthorized"}))
        except Exception:
            pass
        return
    channels = set(WS_CHANNELS)
    if me["role"] == ROLE_USER:
        channels.discard("advice")  # 普通用户收不到实时选股建议
    ws_register(conn, channels, role=me["role"])
    log.info("WS 客户端接入（%s/%s，当前 %d 个）", me["username"], me["role"], len(_ws_clients))
    try:
        while True:
            raw = conn.receive()
            try:
                msg = json.loads(raw)
            except (TypeError, ValueError):
                continue
            mtype = msg.get("type")
            if mtype == "ping":
                conn.send(json.dumps({"type": "heartbeat", "ts": int(time.time() * 1000)}))
            elif mtype in ("subscribe", "unsubscribe"):
                req = msg.get("channels") or []
                with _ws_lock:
                    entry = _ws_clients.get(id(conn))
                    if entry:
                        if mtype == "subscribe":
                            allowed = WS_CHANNELS - (
                                {"advice"} if entry.get("role") == ROLE_USER else set()
                            )
                            entry["channels"].update(c for c in req if c in allowed)
                        else:
                            entry["channels"].difference_update(req)
    except Exception:
        pass  # 客户端断开
    finally:
        ws_unregister(conn)
        log.info("WS 客户端断开（当前 %d 个）", len(_ws_clients))


# ====== HTTP ======
class UpstreamRateLimited(Exception):
    """上游限频窗口已满，本次请求被本地拦截（未真正发出，不消耗配额）。"""


# ====== 上游限频（令牌桶）—— 所有上游请求的唯一出口 http_get 挂钩 ======
UPSTREAM_RPM = int(os.environ.get("UPSTREAM_RPM", "20"))  # 每分钟上游请求上限
_rate_lock = threading.Lock()
_rate_win: list[float] = []  # 最近 60s 已发出的请求时间戳


def _rate_allow() -> bool:
    """60 秒滑动窗口内 < UPSTREAM_RPM 才放行；超限直接拒绝（宁用旧数据不封 token）。"""
    now = time.time()
    with _rate_lock:
        while _rate_win and now - _rate_win[0] > 60:
            _rate_win.pop(0)
        if len(_rate_win) >= UPSTREAM_RPM:
            return False
        _rate_win.append(now)
        return True


def http_get(url, with_token=False, timeout=15, headers=None, params=None):
    if not _rate_allow():
        raise UpstreamRateLimited(f"rate limit {UPSTREAM_RPM}/min reached")
    h = {"User-Agent": UA, "Referer": "https://xuangutong.com.cn/"}
    if headers:
        h.update(headers)
    if with_token and TOKEN:
        h["x-ivanka-token"] = TOKEN
    r = requests.get(url, headers=h, params=params, timeout=timeout)
    r.raise_for_status()
    return r


# ====== 简单缓存（+ single-flight 防惊群 + stale 兜底） ======
_cache = {}


def cache_get(key, ttl):
    hit = _cache.get(key)
    if hit and time.time() - hit["ts"] < ttl:
        return hit["data"]
    return None


def cache_set(key, data):
    _cache[key] = {"data": data, "ts": time.time()}
    # 覆盖型"当日"key 同步入库：上游失败时回旧值 / 重启冷启动装载
    # （快讯/情绪日结/主题另有专用表；历史日期 key 与天梯不进 snapshots）
    if key.endswith(":today") or key in ("sentiment", "themes", "monitor"):
        try:
            dbm.save_snapshot(key, data)
        except Exception:  # noqa: BLE001
            log.exception("snapshot 入库失败: %s", key)


def _peek_cache(key):
    hit = _cache.get(key)
    return hit["data"] if hit else None


# single-flight：同 key 过期瞬间只放一个线程回源，其余等待后共享结果（防惊群）
_flight: dict[str, threading.Lock] = {}
_flight_guard = threading.Lock()


def _flight_lock(key: str) -> threading.Lock:
    with _flight_guard:
        if key not in _flight:
            _flight[key] = threading.Lock()
        return _flight[key]


def cached_fetch(key, ttl, fetch_fn):
    """统一的取数入口：缓存命中直接返回；未命中时 single-flight 回源。

    返回 (data, stale)。上游失败 / 被限频 → 返回旧值 stale=True 而非报错
    （无任何旧值时才向上抛异常）。fetch_fn 内部的上游调用受 http_get 令牌桶约束。
    """
    hit = cache_get(key, ttl)
    if hit is not None:
        return hit, False
    lock = _flight_lock(key)
    with lock:
        hit = cache_get(key, ttl)  # 双检：排队期间可能已被同 key 其它线程刷新
        if hit is not None:
            return hit, False
        try:
            data = fetch_fn()
        except UpstreamRateLimited as e:
            old = _peek_cache(key)
            if old is not None:
                log.warning("限频，%s 返回旧值: %s", key, e)
                return old, True
            raise
        except Exception:
            old = _peek_cache(key)
            if old is not None:
                log.warning("上游失败，%s 返回旧值", key, exc_info=True)
                return old, True
            raise
        cache_set(key, data)
        return data, False


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ======================  /sentiment  ======================
def get_sentiment() -> dict:
    """情绪指标：优先用 flash-api market_indicator/line 当日最新点（字段全）。
    2026-09-08 修复：首页 SSR 结构变化导致 limit_down/broken 等解析为 0，弃用。
    """
    data, stale = cached_fetch("sentiment", 90, _fetch_sentiment)
    if stale:
        data = {**data, "_stale": True}
    return data


def _fetch_sentiment() -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    fields = (
        "market_temperature,limit_up_count,limit_down_count,"
        "limit_up_broken_count,limit_up_broken_ratio,ziranzhangting_count,"
        "rise_count,fall_count,stay_count,yesterday_limit_up_avg_pcp,lianbangaodu"
    )
    try:
        j = http_get(
            f"https://flash-api.xuangubao.com.cn/api/market_indicator/line?fields={fields}&date={today}"
        ).json()
        points = (j.get("data") or []) if j.get("code") == 20000 else []
    except UpstreamRateLimited:
        raise
    except Exception as e:  # noqa: BLE001
        _note_upstream_error("sentiment", e)
        points = []

    data: dict = {}
    if points:
        p = points[-1]  # 当日最新点
        height = 0
        dist = p.get("lianbangaodu") or {}
        for k in dist:
            try:
                height = max(height, int(k))
            except (TypeError, ValueError):
                continue
        data = {
            "temperature": p.get("market_temperature") or 0,
            "limit_up_count": int(p.get("limit_up_count") or 0),
            "limit_down_count": int(p.get("limit_down_count") or 0),
            "limit_up_broken_count": int(p.get("limit_up_broken_count") or 0),
            "natural_limit_up_count": int(p.get("ziranzhangting_count") or 0),
            "limit_up_broken_ratio": p.get("limit_up_broken_ratio") or 0,
            "yesterday_limit_up_avg_pcp": p.get("yesterday_limit_up_avg_pcp") or 0,
            "rise_count": int(p.get("rise_count") or 0),
            "fall_count": int(p.get("fall_count") or 0),
            "stay_count": int(p.get("stay_count") or 0),
            "lianbangaodu": height or None,
            "lianbangaodu_dist": dist,
            "ts": now_iso(),
        }
        # 当日日结入库（盘中滚动修正；finalized 后不再覆盖）
        try:
            dbm.save_daily_snapshot(today, _aggregate_day(points, today))
        except Exception:  # noqa: BLE001
            log.exception("当日情绪日结入库失败")
    else:
        # 兜底：首页 SSR（字段可能不全，标 missing）
        html = http_get("https://xuangutong.com.cn/").text

        def num(field):
            pat = re.compile(rf"\b{re.escape(field)}:(\-?[\d\.]+(?:e\-?\d+)?)")
            m = pat.search(html)
            return float(m.group(1)) if m else 0.0

        def intv(field):
            return int(num(field))

        data = {
            "temperature": num("market_temperature"),
            "limit_up_count": intv("limit_up_count"),
            "limit_down_count": intv("limit_down_count"),
            "limit_up_broken_count": intv("limit_up_broken_count"),
            "natural_limit_up_count": intv("ziranzhangting_count"),
            "limit_up_broken_ratio": num("limit_up_broken_ratio"),
            "yesterday_limit_up_avg_pcp": num("yesterday_limit_up_avg_pcp"),
            "rise_count": intv("rise_count"),
            "fall_count": intv("fall_count"),
            "stay_count": intv("stay_count"),
            "lianbangaodu": int(num("lianbangaodu")) if num("lianbangaodu") else None,
            "ts": now_iso(),
            "_source": "ssr_fallback",
        }
    return data


@app.route("/api/sentiment")
def sentiment():
    return jsonify(get_sentiment())


# ======================  /sentiment/history  ======================
HISTORY_FIELDS = (
    "market_temperature,limit_up_count,limit_down_count,"
    "limit_up_broken_count,limit_up_broken_ratio,"
    "natural_limit_up_count,ziranzhangting_count,"
    "rise_count,fall_count,stay_count,"
    "yesterday_limit_up_avg_pcp,lianbangaodu"
)


def _fetch_one_day(date_str, fields=HISTORY_FIELDS):
    """调选股通 flash-api /api/market_indicator/line?date=XXX
    返回当天所有分钟数据点"""
    url = (
        "https://flash-api.xuangubao.com.cn/api/market_indicator/line"
        f"?fields={fields}&date={date_str}"
    )
    try:
        j = http_get(url).json()
        return (j.get("data") or []) if j.get("code") == 20000 else []
    except UpstreamRateLimited:
        raise  # 限频必须穿透：让循环中断走 stale 兜底，而不是当天空数据
    except Exception as e:
        log.warning("history %s failed: %s", date_str, e)
        _note_upstream_error("sentiment_history", e)
        return []


def _trade_dates(n_days):
    """生成最近 n_days 个交易日的日期列表（含今天；跳过周六周日）。

    2026-09-09 修复：原来从 i=1 起步导致今天永远缺失，情绪历史只到前一交易日。
    非交易日/盘前今天无数据 → _fetch_one_day 返回空自然跳过，无副作用。
    """
    out = []
    today = datetime.now().date()
    i = 0
    while len(out) < n_days and i < n_days * 3:
        d = today - timedelta(days=i)
        # 周一=0 ... 周五=4, 周六=5, 周日=6
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        i += 1
    return out


def _to_snapshot(item, date_str):
    """将选股通单分钟点转成前端用的日快照"""
    boards = item.get("lianbangaodu") or {}
    max_boards = max((int(k) for k in boards.keys()), default=0)
    return {
        "date": date_str,
        "ts": item.get("timestamp"),
        "temperature": item.get("market_temperature") or 0,
        "limit_up_count": item.get("limit_up_count") or 0,
        "limit_down_count": item.get("limit_down_count") or 0,
        "limit_up_broken_count": item.get("limit_up_broken_count") or 0,
        "limit_up_broken_ratio": item.get("limit_up_broken_ratio") or 0,
        "natural_limit_up_count": item.get("natural_limit_up_count") or item.get("ziranzhangting_count") or 0,
        "rise_count": item.get("rise_count") or 0,
        "fall_count": item.get("fall_count") or 0,
        "stay_count": item.get("stay_count") or 0,
        "yesterday_limit_up_avg_pcp": item.get("yesterday_limit_up_avg_pcp") or 0,
        "lianbangaodu": max_boards,
        "lianban_distribution": boards,
    }


@app.route("/api/sentiment/history")
def sentiment_history():
    days = max(1, min(30, int(request.args.get("days", 10))))
    sample = request.args.get("sample", "last")  # last | mean
    return jsonify(get_sentiment_history(days, sample))


def _aggregate_day(points: list, date_str: str) -> dict:
    """全天分钟点 → 日结 payload：{"last": 尾盘快照, "mean": 全天均值快照}。"""
    def avg(k):
        vs = [it.get(k) for it in points if it.get(k) is not None]
        return sum(vs) / len(vs) if vs else 0

    mean_agg = {
        "market_temperature": avg("market_temperature"),
        "limit_up_count": avg("limit_up_count"),
        "limit_down_count": avg("limit_down_count"),
        "limit_up_broken_count": avg("limit_up_broken_count"),
        "rise_count": avg("rise_count"),
        "fall_count": avg("fall_count"),
        "stay_count": avg("stay_count"),
        "yesterday_limit_up_avg_pcp": avg("yesterday_limit_up_avg_pcp"),
        "limit_up_broken_ratio": avg("limit_up_broken_ratio"),
        "natural_limit_up_count": avg("natural_limit_up_count"),
        "ziranzhangting_count": avg("ziranzhangting_count"),
        "lianbangaodu": points[-1].get("lianbangaodu") or {},
        "timestamp": points[-1].get("timestamp"),
    }
    return {"last": _to_snapshot(points[-1], date_str), "mean": _to_snapshot(mean_agg, date_str)}


def get_sentiment_history(days: int = 10, sample: str = "last") -> list:
    """最近 N 天情绪历史（含今天）。

    读库优先：历史天来自 daily_snapshots（终态），仅补拉缺失天——上游配额敏感。
    今天的数据由 get_sentiment 的滚动刷新持续写入本库，这里不再单独拉。
    """
    cache_key = f"sentiment_history:{days}:{sample}"
    data, stale = cached_fetch(cache_key, 300, lambda: _fetch_sentiment_history(days, sample))
    if stale and isinstance(data, list):
        data = [{**item, "_stale": True} for item in data]
    return data


def _fetch_sentiment_history(days: int, sample: str) -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    dates = _trade_dates(days)  # 含今天；非交易日自然无数据
    by_date = {row["date"]: row for row in dbm.list_daily_snapshots(days + 2)}
    # 补拉库内缺失的天（历史拉到即终态；今天缺失时拉一次滚动点）。
    # 每次最多补 4 天：避免冷启动独占 20 次/分钟限频窗口，饿死其它数据源；
    # 剩余天数由后续刷新轮次渐进补齐（约 30s/轮）。
    pulled = 0
    for date_str in [d for d in dates if d not in by_date]:
        if pulled >= 4:
            break
        items = _fetch_one_day(date_str)  # UpstreamRateLimited 直接上抛 → stale 兜底
        if not items:
            continue  # 非交易日 / 偶发失败（下次刷新再补）
        dbm.save_daily_snapshot(date_str, _aggregate_day(items, date_str),
                                finalized=(date_str != today))
        by_date[date_str] = next((r for r in dbm.list_daily_snapshots(days + 2)
                                  if r["date"] == date_str), None)
        pulled += 1
    return [by_date[d][sample] for d in sorted(dates) if by_date.get(d)]


# ======================  /pool/<name>  ======================
VALID_POOLS = {
    "limit_up",
    "limit_up_broken",
    "yesterday_limit_up",
    "super_stock",
    "limit_down",
    "new_stock",
    "nearly_new",
}


@app.route("/api/pool/<name>")
def pool(name):
    date = request.args.get("date")
    return jsonify(get_pool(name, date))


def get_pool(name, date=None):
    if name not in VALID_POOLS:
        return {"pool_name": name, "date": date or "", "items": [], "error": f"unknown pool: {name}"}
    key = f"pool:{name}:{date or 'today'}"
    data, stale = cached_fetch(key, 60, lambda: _fetch_pool(name, date))
    if stale:
        data = {**data, "_stale": True}
    return data


def _fetch_pool(name, date=None) -> dict:
    url = f"https://flash-api.xuangubao.com.cn/api/pool/detail?pool_name={name}"
    if date:
        url += f"&date={date}"
    j = http_get(url).json()
    # flash-api 的 data 字段是 list，不是 dict
    items = j.get("data") if isinstance(j.get("data"), list) else (j.get("data") or {}).get("items") or []
    return {
        "pool_name": name,
        "date": date or datetime.now().strftime("%Y-%m-%d"),
        "items": items,
        "ts": now_iso(),
    }


# ======================  连板天梯（涨停池历史落盘 + 聚合）  ======================
# 每日涨停池快照落盘 data/lianban_ladder/<date>.json（盘中随池变化持续覆盖，收盘即终态），
# 历史缺失日期从选股通 pool/detail?date= 回补。聚合为「连板天梯」：行=个股，列=日期，
# 单元格=名称+连板数，仅保留 >=2 连板。
LADDER_DIR = Path(
    os.environ.get("LIANBAN_LADDER_DIR")
    or Path(__file__).parent / "data" / "lianban_ladder"
)
_ladder_lock = threading.Lock()


def _slim_pool_item(it: dict) -> dict:
    """涨停池条目 → 天梯落盘所需的最小字段集。"""
    return {
        "symbol": it.get("symbol"),
        "name": it.get("stock_chi_name"),
        "limit_up_days": it.get("limit_up_days"),
        "first_limit_up": it.get("first_limit_up"),
        "last_limit_up": it.get("last_limit_up"),
        "price": it.get("price"),
        "change_percent": it.get("change_percent"),
    }


def persist_limit_up_snapshot() -> None:
    """当日涨停池快照落盘（data_refresh_loop 每轮调用）。空池不覆盖，
    避免开盘前把已有文件清空；内容未变不重写，保持 mtime 稳定。

    ⚠️ 归属日判定：凌晨/盘前时段无 date 参数的池接口返回的是上一交易日的
    终态池 —— 用 items 中最新的 first_limit_up 时间戳（Unix 秒，UTC+8）反推
    数据真实所属交易日，避免把昨日数据错标成今天。
    """
    try:
        pool = get_pool("limit_up")
        items = [_slim_pool_item(it) for it in (pool.get("items") or []) if it.get("symbol")]
        if not items:
            return
        stamps = [it["first_limit_up"] for it in items if it.get("first_limit_up")]
        if stamps:
            tz8 = timezone(timedelta(hours=8))
            date = datetime.fromtimestamp(max(stamps), tz=tz8).strftime("%Y-%m-%d")
        else:
            date = datetime.now().strftime("%Y-%m-%d")
        payload = {"date": date, "ts": now_iso(), "items": items}
        LADDER_DIR.mkdir(parents=True, exist_ok=True)
        path = LADDER_DIR / f"{date}.json"
        text = json.dumps(payload, ensure_ascii=False)
        with _ladder_lock:
            if path.exists() and path.read_text(encoding="utf-8") == text:
                return
            path.write_text(text, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("涨停池快照落盘失败: %s", e)


def _ladder_day_items(date_str: str) -> list:
    """某日涨停池条目（原样全量，>=2 过滤在聚合时做）。
    优先读本地文件；过去日期缺失时从选股通历史接口回补并落盘（空结果也落盘，
    视为节假日/无涨停，避免反复打上游）。"""
    path = LADDER_DIR / f"{date_str}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("items") or []
        except Exception:  # noqa: BLE001
            log.warning("连板天梯文件损坏，将重新回补: %s", path)
    today = datetime.now().strftime("%Y-%m-%d")
    if date_str >= today:
        return []  # 当天还没有文件 → 盘中由 persist_limit_up_snapshot 写入
    try:
        j = http_get(
            "https://flash-api.xuangubao.com.cn/api/pool/detail"
            f"?pool_name=limit_up&date={date_str}"
        ).json()
        raw = j.get("data") if isinstance(j.get("data"), list) else (j.get("data") or {}).get("items") or []
        items = [_slim_pool_item(it) for it in raw if it.get("symbol")]
        payload = json.dumps({"date": date_str, "ts": now_iso(), "items": items}, ensure_ascii=False)
        LADDER_DIR.mkdir(parents=True, exist_ok=True)
        with _ladder_lock:
            path.write_text(payload, encoding="utf-8")
        time.sleep(0.15)  # 回补时轻限速
        return items
    except Exception as e:  # noqa: BLE001
        _note_upstream_error("ladder", e)
        return []


def _dates_between(start: str, end: str) -> list:
    """start..end 闭区间内的工作日列表（跳过周六日，升序；节假日靠空数据自然排除）。"""
    out = []
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    d = s
    while d <= e:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


def get_ladder(days: int = 30, start: str | None = None, end: str | None = None) -> dict:
    """连板天梯聚合。列=日期升序（无数据的日期自动跳过）；
    行=个股，按最新连板数降序，同板数按封板时间升序（先封板在前）。

    两种取参方式（二选一）：
    - days=N：最近 N 个交易日（默认 30，上限 366）
    - start/end=YYYY-MM-DD：闭区间，跨度上限 366 天
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if start and end:
        end = min(end, today)
        try:
            if (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days > 366:
                start = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=366)).strftime("%Y-%m-%d")
        except ValueError:
            start = end = None  # 格式不对退回 days 模式
    if start and end:
        cache_key = f"ladder:range:{start}:{end}"
    else:
        days = max(5, min(366, days))
        cache_key = f"ladder:{days}"
    hit = cache_get(cache_key, 60)
    if hit:
        return hit

    if start and end:
        all_dates = _dates_between(start, end)
    else:
        # _trade_dates 已含今天（2026-09-09 修复），不再追加，避免今天列重复
        all_dates = _trade_dates(days)[::-1]  # 升序，今天在最后
    per_day: dict = {}
    used = []
    for d in all_dates:
        items = _ladder_day_items(d)
        if items:
            used.append(d)
            per_day[d] = items

    rows: dict = {}
    for d in used:
        for it in per_day[d]:
            n = it.get("limit_up_days") or 0
            if n < 2:
                continue
            sym = it.get("symbol")
            r = rows.setdefault(sym, {"symbol": sym, "name": it.get("name") or sym, "cells": {}})
            r["cells"][d] = {"boards": n, "first_limit_up": it.get("first_limit_up")}

    out_rows = []
    for r in rows.values():
        if not r["cells"]:
            continue
        last_d = max(r["cells"])
        r["max_boards"] = max(c["boards"] for c in r["cells"].values())
        r["last_date"] = last_d
        r["last_boards"] = r["cells"][last_d]["boards"]
        r["last_first_limit_up"] = r["cells"][last_d].get("first_limit_up") or 0
        out_rows.append(r)
    out_rows.sort(key=lambda r: (-r["last_boards"], r["last_first_limit_up"], r["symbol"]))

    data = {"days": used, "rows": out_rows, "ts": now_iso()}
    cache_set(cache_key, data)
    return data


@app.route("/api/ladder")
def ladder_api():
    """连板天梯（涨停池历史聚合，仅 >=2 连板）
    参数：days=N（最近N个交易日）或 start+end（YYYY-MM-DD 闭区间，跨度上限一年）
    """
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30
    return jsonify(
        get_ladder(days, start=request.args.get("start"), end=request.args.get("end"))
    )


# ======================  /newsflash  ======================
@app.route("/api/newsflash")
def newsflash():
    limit = int(request.args.get("limit", 50))
    return jsonify(get_newsflash(limit))


def get_newsflash(limit=50):
    """快讯：上游仅回最近 50 条 → 按 id 增量入库（保留 7 天）→ 读库返回（历史不丢）。"""
    key = f"newsflash:{limit}"
    data, stale = cached_fetch(key, 60, lambda: _fetch_newsflash(limit))
    if stale and isinstance(data, list):
        data = [{**item, "_stale": True} for item in data]
    return data


def _fetch_newsflash(limit=50) -> list:
    if not TOKEN:
        log.warning("token missing, newsflash likely fails")
    url = (
        f"https://baoer-api.xuangubao.com.cn/api/v6/message/newsflash"
        f"?subj_ids=10&limit={limit}&platform=pcweb&has_explain=false"
    )
    j = http_get(url, with_token=True).json()
    msgs = (j.get("data") or {}).get("messages") or []

    norm = []
    for m in msgs:
        bk = m.get("bkj_infos") or []
        norm.append({
            "id": m.get("id"),
            "title": m.get("title") or "",
            "summary": m.get("summary"),
            "stocks": m.get("stocks") or [],
            "plates": bk,
            "category": "盘中异动" if bk else "要闻",
            "published_at": str(m.get("created_at") or ""),
            "is_premium": m.get("is_premium", False),
            "impact": m.get("impact", 0),
            "subj_ids": m.get("subj_ids") or [],
        })
    try:
        dbm.save_news(norm)  # 增量去重入库；返回值仅日志观察
    except Exception:  # noqa: BLE001
        log.exception("newsflash 入库失败")
    return dbm.list_news(limit)


# ======================  /themes  ======================
@app.route("/api/themes")
def themes():
    return jsonify(get_themes())


def get_themes():
    data, stale = cached_fetch("themes", 300, _fetch_themes)
    if stale and isinstance(data, list):
        data = [{**item, "_stale": True} for item in data]
    return data


def _fetch_themes() -> list:
    plates_j = http_get("https://flash-api.xuangubao.com.cn/api/surge_stock/plates").json()
    stocks_j = http_get(
        "https://flash-api.xuangubao.com.cn/api/surge_stock/stocks?normal=true&uplimit=true"
    ).json()

    plate_items = (plates_j.get("data") or {}).get("items") or []
    manual_updated_at = (plates_j.get("data") or {}).get("manual_updated_at", 0)
    timestamp = (plates_j.get("data") or {}).get("timestamp", 0)

    fields = (stocks_j.get("data") or {}).get("fields") or []
    stock_rows = (stocks_j.get("data") or {}).get("items") or []
    decoded_stocks = []
    for row in stock_rows:
        if isinstance(row, list) and len(row) == len(fields):
            decoded_stocks.append(dict(zip(fields, row)))

    plate_ids = [p.get("id") for p in plate_items[:13] if p.get("id")]
    plate_data = {}
    if plate_ids:
        try:
            pj = http_get(
                "https://flash-api.xuangubao.com.cn/api/plate/data"
                f"?fields=core_avg_pcp,plate_name&plates={','.join(map(str, plate_ids))}"
            ).json()
            plate_data = pj.get("data") or {}
        except Exception as e:
            log.warning("plate/data failed: %s", e)

    out = []
    for idx, item in enumerate(plate_items):
        pid = item.get("id")
        stats = plate_data.get(str(pid), {})
        theme_stocks = [
            s for s in decoded_stocks
            if any(p.get("id") == pid for p in (s.get("plates") or []))
        ]  # 全量展示（2026-09-08 用户要求，原截断前 6 只）
        norm = []
        for s in theme_stocks:
            norm.append({
                "code": s.get("code") or s.get("symbol") or "",
                "prod_name": s.get("prod_name") or s.get("stock_chi_name") or "",
                "cur_price": s.get("cur_price") or s.get("price") or 0,
                "px_change_rate": s.get("px_change_rate") or s.get("change_percent") or 0,
                "circulation_value": s.get("circulation_value") or 0,
                "description": s.get("description") or "",
                "enter_time": s.get("enter_time") or 0,
                "up_limit": bool(s.get("up_limit") or s.get("is_limit_up")),
                "plates": s.get("plates") or [],
                "turnover_ratio": s.get("turnover_ratio") or 0,
                "m_days_n_boards": str(s.get("m_days_n_boards") or ""),
            })
        out.append({
            "id": pid,
            "name": item.get("name") or "",
            "description": item.get("description"),
            "rank": idx + 1,
            "core_avg_pcp": stats.get("core_avg_pcp"),
            "manual_updated_at": manual_updated_at,
            "timestamp": timestamp,
            "stocks": norm,
        })
    # 主题每日快照入库（当日覆盖，保留 7 天供前端对比）
    try:
        dbm.save_theme_snapshot(datetime.now().strftime("%Y-%m-%d"), out)
    except Exception:  # noqa: BLE001
        log.exception("主题快照入库失败")
    return out


@app.route("/api/themes/history/<date>")
def themes_history(date):
    """历史某天主题快照（保留最近 7 天）。"""
    snap = dbm.get_theme_snapshot(date)
    if snap is None:
        return jsonify({"error": f"no snapshot for {date}"}), 404
    return jsonify(snap)


@app.route("/api/themes/dates")
def themes_dates():
    """可对比的主题快照日期列表（降序，今天在前）。"""
    return jsonify(dbm.list_theme_dates())


# ======================  /monitor（东财监管名单）  ======================
# 重点监控证券 + 严重异常波动，接口口径对齐 quant-system EastmoneySource 适配器：
# - 重点监控证券：mobappconfig.securities.eastmoney.com/emcfg/stock_monitor.json（最新名单，无历史）
# - 严重异常波动：datacenter RPT_APP_UNUSUALBASIC filter=(UNUSUAL_TYPE="002")
# 约束：未声明商业授权，仅低频研究用途；需移动端 UA/Referer。
EM_MOBCONFIG = "https://mobappconfig.securities.eastmoney.com"
EM_DATACENTER = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
EM_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"
EM_REFERER = (
    "https://vipmoney.eastmoney.com/collect/min_data/point_stock_monitor/index.html"
)
EM_HEADERS = {"User-Agent": EM_UA, "Referer": EM_REFERER}
EM_UNUSUAL_COLUMNS = (
    "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,UNUSUAL_TYPE,START_DATE,END_DATE,"
    "INFO_CODE,NOTICE_DATE,UNUSUAL_REASON,UNUSUAL_REASON_TYPE,MRAKET_TYPE,"
    "PREDICT_START_DATE,PREDICT_END_DATE,IS_HIS"
)


def _em_thscode(code: str, market: str) -> str:
    """6 位代码 + 市场号 → thscode（1=SH / 0=SZ / B=BJ）"""
    if len(code) != 6:
        return ""
    return {"1": code + ".SH", "0": code + ".SZ", "B": code + ".BJ"}.get(market, "")


@app.route("/api/monitor")
def monitor():
    return jsonify(get_monitor())


def get_monitor() -> dict:
    """监管名单：restricted=重点监控证券（最新）+ severe=严重异常波动（最近 50 条公告）。"""
    data, stale = cached_fetch("monitor", 300, _fetch_monitor)
    if stale:
        data = {**data, "_stale": True}
    return data


def _fetch_monitor() -> dict:
    errors = []

    # ---- 重点监控证券（最新名单，无历史分页） ----
    restricted = []
    try:
        rows = http_get(
            EM_MOBCONFIG + "/emcfg/stock_monitor.json", timeout=20, headers=EM_HEADERS
        ).json()
        if not isinstance(rows, list):
            raise ValueError("重点监控返回非数组")
        for r in rows:
            code = str(r.get("STKCODE", ""))
            market = str(r.get("MARKET", ""))
            restricted.append({
                "thscode": _em_thscode(code, market),
                "code": code,
                "name": str(r.get("STKNAME", "")),
                "market": market,
                "start_date": str(r.get("VALIDATESTARTDATE") or ""),
                "end_date": str(r.get("VALIDATEENDDATE") or ""),
            })
    except Exception as e:
        errors.append(f"restricted: {e}")
        _note_upstream_error("monitor", e)
        log.warning("monitor restricted failed: %s", e)

    # ---- 严重异常波动（002，按公告日倒序前 50 条） ----
    severe = []
    try:
        params = {
            "reportName": "RPT_APP_UNUSUALBASIC",
            "columns": EM_UNUSUAL_COLUMNS,
            "filter": '(UNUSUAL_TYPE="002")',
            "sortColumns": "NOTICE_DATE,END_DATE",
            "sortTypes": "-1,-1",
            "pageNumber": 1,
            "pageSize": 50,
            "source": "SECURITIES",
            "client": "APP",
        }
        body = http_get(
            EM_DATACENTER, timeout=20, headers=EM_HEADERS, params=params
        ).json()
        rows = (body.get("result") or {}).get("data") or []
        for r in rows:
            severe.append({
                "thscode": str(r.get("SECUCODE") or ""),
                "code": str(r.get("SECURITY_CODE", "")),
                "name": str(r.get("SECURITY_NAME_ABBR", "")),
                "start_date": str(r.get("START_DATE") or ""),
                "end_date": str(r.get("END_DATE") or ""),
                "notice_date": str(r.get("NOTICE_DATE") or ""),
                "reason": str(r.get("UNUSUAL_REASON") or ""),
            })
    except Exception as e:
        errors.append(f"severe: {e}")
        log.warning("monitor severe failed: %s", e)

    data = {"restricted": restricted, "severe": severe, "errors": errors, "ts": now_iso()}
    return data


# ======================  /api/config（量化策略参数，admin）  ======================
# 读写分离：quant-system 调度器启动时导出 schema.json，且只读 active.json 热生效；
# backend 是唯一写方（配置页保存/回滚），文件格式契约见 quant-system/config_registry.py
CONFIG_DIR = Path(
    os.environ.get("QUANT_CONFIG_DIR")
    or (Path(__file__).resolve().parents[2] / "quant-system" / "data" / "config")
)


def _load_schema_doc() -> dict:
    f = CONFIG_DIR / "schema.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("schema.json 读取失败: %s", e)
        return {}


def _load_active_doc() -> dict:
    f = CONFIG_DIR / "active.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"version": 0, "saved_at": "", "actor": "", "strategies": {}}


def _coerce_param(pdef: dict, value):
    """按 schema 校验/转换参数值（percent/float/int/bool + min/max）。"""
    t = pdef.get("type")
    try:
        if t == "int":
            v = int(value)
        elif t in ("percent", "float"):
            v = float(value)
        elif t == "bool":
            v = bool(value)
        else:
            v = value
    except (TypeError, ValueError):
        raise ValueError(f"参数 {pdef['key']} 类型错误（期望 {t}）")
    if t in ("percent", "float", "int"):
        if "min" in pdef and v < pdef["min"]:
            raise ValueError(f"参数 {pdef['key']} 低于下限 {pdef['min']}")
        if "max" in pdef and v > pdef["max"]:
            raise ValueError(f"参数 {pdef['key']} 超过上限 {pdef['max']}")
    return v


def _write_active(doc: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_DIR / "active.json.tmp"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_DIR / "active.json")


def _append_history(doc: dict) -> None:
    hist = CONFIG_DIR / "history"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"v{doc['version']}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@app.route("/api/config/strategies")
def config_strategies():
    """策略参数列表：schema（来自 quant-system 导出）+ 当前生效值。"""
    schema_doc = _load_schema_doc()
    if not schema_doc.get("strategies"):
        return jsonify({"error": "策略参数 schema 不可用（quant-system 调度器尚未启动过）"}), 404
    active = _load_active_doc()
    out = []
    for sid, s in schema_doc["strategies"].items():
        overrides = active.get("strategies", {}).get(sid, {})
        params = s.get("params", [])
        out.append({
            "id": sid,
            "label": s.get("label", sid),
            "params": params,
            "values": {p["key"]: overrides.get(p["key"], p["default"]) for p in params},
        })
    return jsonify({
        "strategies": out,
        "version": active.get("version", 0),
        "saved_at": active.get("saved_at", ""),
        "actor": active.get("actor", ""),
    })


@app.route("/api/config/strategies/<sid>", methods=["POST"])
def config_strategy_save(sid: str):
    """保存并启用某策略参数（整包写入；每次保存产生新版本，quant-system 下一 tick 热生效）。"""
    schema_doc = _load_schema_doc()
    sdef = schema_doc.get("strategies", {}).get(sid)
    if sdef is None:
        return jsonify({"error": "未知策略或 schema 不可用"}), 404
    body = request.get_json(silent=True) or {}
    values = body.get("values")
    if not isinstance(values, dict):
        return jsonify({"error": "缺少 values"}), 400
    valid = {p["key"]: p for p in sdef.get("params", [])}
    clean = {}
    try:
        for k, v in values.items():
            if k not in valid:
                return jsonify({"error": f"未知参数: {k}"}), 400
            clean[k] = _coerce_param(valid[k], v)
        # 未提交的参数补默认值（整包语义，避免半份配置）
        for k, p in valid.items():
            if k not in clean:
                clean[k] = _coerce_param(p, p["default"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    active = _load_active_doc()
    strategies = active.get("strategies", {})
    strategies[sid] = clean
    doc = {
        "version": int(active.get("version", 0)) + 1,
        "saved_at": now_iso(),
        "actor": current_user().get("username", ""),
        "strategies": strategies,
    }
    _write_active(doc)
    _append_history(doc)
    log.info("策略参数已启用: %s v%s by %s: %s", sid, doc["version"], doc["actor"], clean)
    return jsonify({"ok": True, "version": doc["version"]})


@app.route("/api/config/history")
def config_history():
    """参数版本历史（倒序，最多 50 条）。"""
    hist = CONFIG_DIR / "history"
    docs = []
    if hist.exists():
        for p in sorted(hist.glob("v*.json"), key=lambda x: int(x.stem[1:]), reverse=True):
            try:
                docs.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                continue
    return jsonify({"items": docs[:50]})


@app.route("/api/config/rollback/<int:version>", methods=["POST"])
def config_rollback(version: int):
    """回滚 = 将历史版本参数作为新版本重新启用（版本链单调递增，可审计）。"""
    src = CONFIG_DIR / "history" / f"v{version}.json"
    try:
        old = json.loads(src.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return jsonify({"error": f"版本不存在: v{version}"}), 404
    schema_doc = _load_schema_doc()
    strategies = {}
    # 回滚值也过一遍 schema 校验（schema 可能已演进），非法键剔除
    for sid, vals in old.get("strategies", {}).items():
        valid = {p["key"]: p for p in schema_doc.get("strategies", {}).get(sid, {}).get("params", [])}
        kept = {}
        for k, v in vals.items():
            if k in valid:
                try:
                    kept[k] = _coerce_param(valid[k], v)
                except ValueError:
                    continue
        if kept:
            strategies[sid] = kept
    active = _load_active_doc()
    doc = {
        "version": int(active.get("version", 0)) + 1,
        "saved_at": now_iso(),
        "actor": f"{current_user().get('username', '')}（回滚自 v{version}）",
        "strategies": strategies,
    }
    _write_active(doc)
    _append_history(doc)
    log.info("配置回滚: v%d → 新版本 v%s", version, doc["version"])
    return jsonify({"ok": True, "version": doc["version"]})


# ======================  /api/datasources + /api/strategy/test（量化沙箱，admin）  ======================
# 与 quant-system 的契约：backend 不 import，仅以子进程调用
# `quant-system/.venv/bin/python -m quant_system.sandbox {ping|test}`（stdout 单行 JSON）。
QS_ROOT = CONFIG_DIR.parent.parent  # .../quant-system
QS_PYTHON = Path(
    os.environ.get("QUANT_SYSTEM_PYTHON") or (QS_ROOT / ".venv" / "bin" / "python")
)
_SANDBOX_LOCK = threading.Lock()  # 沙箱子进程较重（拉行情），全局串行


def _run_sandbox(arglist: list[str], timeout: int, module: str = "quant_system.sandbox") -> tuple[dict | None, str]:
    """执行 quant-system 子进程（sandbox/replay），返回 (json, err)。stdout 最后一行为 JSON。"""
    if not QS_PYTHON.exists():
        return None, f"quant-system 解释器不存在: {QS_PYTHON}"
    try:
        proc = subprocess.run(
            [str(QS_PYTHON), "-m", module, *arglist],
            cwd=str(QS_ROOT), capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONPATH": str(QS_ROOT / "src")},
        )
    except subprocess.TimeoutExpired:
        return None, f"子进程执行超时（>{timeout}s）"
    except Exception as e:  # noqa: BLE001
        return None, f"子进程启动失败: {e}"
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 and not out:
        return None, f"沙箱退出码 {proc.returncode}；stderr 尾部: {(proc.stderr or '')[-400:]}"
    if not out:
        return None, f"沙箱无输出；stderr 尾部: {(proc.stderr or '')[-400:]}"
    try:
        data = json.loads(out.splitlines()[-1])
    except ValueError:
        return None, f"沙箱输出解析失败: {out[:300]}"
    if proc.returncode != 0 and isinstance(data, dict):
        data.setdefault("failed", True)
    return data, ""


def _load_datasource_doc() -> dict:
    f = CONFIG_DIR / "datasources.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _load_datasource_health() -> dict:
    f = CONFIG_DIR / "datasource_health.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


@app.route("/api/datasources")
def datasources_list():
    """数据源注册表 + 能力提供方 + 源偏好 + 最近探测结果。"""
    doc = _load_datasource_doc()
    if not doc.get("datasources"):
        return jsonify({"error": "数据源注册表不可用（quant-system 调度器启动后自动生成）"}), 404
    health = _load_datasource_health()
    f = CONFIG_DIR / "datasource_prefs.json"
    try:
        prefs = json.loads(f.read_text(encoding="utf-8")).get("prefs", {})
    except Exception:  # noqa: BLE001
        prefs = {}
    return jsonify({
        "datasources": [{**d, "health": health.get(d["id"])} for d in doc["datasources"]],
        "capability_providers": doc.get("capability_providers", {}),
        "prefs": prefs,
    })


@app.route("/api/datasources/prefs", methods=["POST"])
def datasources_prefs_save():
    """保存能力源偏好：body {capability, primary, fallback?}（fallback 可为 null=不设备源）。

    写 datasource_prefs.json，quant-system resolve 层每次现读 → 下一 tick 热生效。
    """
    body = request.get_json(silent=True) or {}
    cap = body.get("capability")
    primary, fallback = body.get("primary"), body.get("fallback")
    doc = _load_datasource_doc()
    providers = doc.get("capability_providers", {}).get(cap)
    if providers is None:
        return jsonify({"error": f"未知能力: {cap}"}), 404
    if primary not in providers:
        return jsonify({"error": f"primary 须为该能力的可用源之一: {providers}"}), 400
    if fallback is not None and fallback not in providers:
        return jsonify({"error": f"fallback 须为该能力的可用源之一: {providers}"}), 400
    if fallback is not None and fallback == primary:
        return jsonify({"error": "fallback 不能与 primary 相同"}), 400

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    f = CONFIG_DIR / "datasource_prefs.json"
    try:
        all_prefs = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        all_prefs = {"version": 1, "prefs": {}}
    prefs = all_prefs.setdefault("prefs", {})
    prefs[cap] = {"primary": primary, "fallback": fallback}
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)
    log.info("源偏好已保存: %s primary=%s fallback=%s by %s",
             cap, primary, fallback, current_user().get("username", ""))
    return jsonify({"ok": True, "prefs": prefs})


@app.route("/api/datasources/ping", methods=["POST"])
def datasources_ping():
    """连通性探测：body {id?: str}，缺省探测全部。结果同时记录到 datasource_health.json。"""
    body = request.get_json(silent=True) or {}
    ds_id = body.get("id")
    known = {d["id"] for d in _load_datasource_doc().get("datasources", [])}
    if ds_id is not None and known and ds_id not in known:
        return jsonify({"error": f"未知数据源: {ds_id}"}), 404
    if not _SANDBOX_LOCK.acquire(blocking=False):
        return jsonify({"error": "另一个沙箱任务正在执行，请稍候"}), 409
    try:
        arglist = ["ping"] + ([ds_id] if ds_id else [])
        result, err = _run_sandbox(arglist, timeout=90)
    finally:
        _SANDBOX_LOCK.release()
    if err:
        return jsonify({"error": err}), 500
    return jsonify(result)


@app.route("/api/strategy/test", methods=["POST"])
def strategy_test():
    """在线沙箱测试：body {strategy, date, params?}。

    在 quant-system 子进程中以注入参数重跑策略（不落盘、不推 WS），
    返回与生产一致的报告 JSON + sandbox 元信息。
    """
    body = request.get_json(silent=True) or {}
    sid = body.get("strategy")
    schema_doc = _load_schema_doc()
    sdef = schema_doc.get("strategies", {}).get(sid)
    if sdef is None:
        return jsonify({"error": "未知策略或 schema 不可用"}), 404
    date = body.get("date") or ""
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify({"error": "date 格式须为 YYYY-MM-DD"}), 400
    params = body.get("params") or {}
    if not isinstance(params, dict):
        return jsonify({"error": "params 须为对象"}), 400
    valid = {p["key"]: p for p in sdef.get("params", [])}
    clean = {}
    try:
        for k, v in params.items():
            if k not in valid:
                return jsonify({"error": f"未知参数: {k}"}), 400
            clean[k] = _coerce_param(valid[k], v)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not _SANDBOX_LOCK.acquire(blocking=False):
        return jsonify({"error": "另一个沙箱任务正在执行，请稍候"}), 409
    try:
        arglist = ["test", "--strategy", sid, "--date", date]
        if clean:
            arglist += ["--params", json.dumps(clean)]
        result, err = _run_sandbox(arglist, timeout=300)
    finally:
        _SANDBOX_LOCK.release()
    if err:
        return jsonify({"error": err}), 500
    if result.get("error"):
        return jsonify(result), 400
    log.info("沙箱测试: %s @ %s params=%s by %s（%.1fs）",
             sid, date, clean or "{}", current_user().get("username", ""),
             result.get("duration_ms", 0) / 1000)
    return jsonify(result)


@app.route("/api/strategy/replay", methods=["POST"])
def strategy_replay():
    """回放测试：body {strategy, date, params?}。

    对 data/std/<date>/ 标准化快照重跑策略（不打真实数据源 API），
    分钟级验证参数改动。结果同时落 data/replay/<date>/（留档可对比）。
    """
    body = request.get_json(silent=True) or {}
    sid = body.get("strategy")
    schema_doc = _load_schema_doc()
    sdef = schema_doc.get("strategies", {}).get(sid)
    if sdef is None:
        return jsonify({"error": "未知策略或 schema 不可用"}), 404
    date = body.get("date") or ""
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return jsonify({"error": "date 格式须为 YYYY-MM-DD"}), 400
    params = body.get("params") or {}
    if not isinstance(params, dict):
        return jsonify({"error": "params 须为对象"}), 400
    valid = {p["key"]: p for p in sdef.get("params", [])}
    clean = {}
    try:
        for k, v in params.items():
            if k not in valid:
                return jsonify({"error": f"未知参数: {k}"}), 400
            clean[k] = _coerce_param(valid[k], v)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not _SANDBOX_LOCK.acquire(blocking=False):
        return jsonify({"error": "另一个沙箱任务正在执行，请稍候"}), 409
    try:
        arglist = ["--date", date, "--strategy", sid]
        if clean:
            arglist += ["--params", json.dumps({sid: clean})]
        result, err = _run_sandbox(arglist, timeout=300, module="quant_system.replay")
    finally:
        _SANDBOX_LOCK.release()
    if err:
        return jsonify({"error": err}), 500
    if result.get("error"):
        return jsonify(result), 400
    log.info("回放测试: %s @ %s params=%s by %s（%.1fs）",
             sid, date, clean or "{}", current_user().get("username", ""),
             result.get("duration_ms", 0) / 1000)
    return jsonify(result)


# ======================  /api/config/perf + /api/backtest（M1 闭环 / M2 回测，admin）  ======================

BACKTEST_DIR = QS_ROOT / "data" / "backtest"


@app.route("/api/config/perf")
def config_perf():
    """参数版本绩效聚合（quant-system 盘后 report.export_perf 产出 perf.json）。"""
    f = CONFIG_DIR / "perf.json"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return jsonify({"error": "perf.json 不可用（盘后任务未产出或为空）"}), 404
    return jsonify(doc)


@app.route("/api/backtest/run", methods=["POST"])
def backtest_run():
    """批量回测：body {start, end, strategies?, params?}。子进程执行（重任务，全局串行）。"""
    body = request.get_json(silent=True) or {}
    start, end = body.get("start") or "", body.get("end") or ""
    date_pat = r"\d{4}-\d{2}-\d{2}"
    if not re.fullmatch(date_pat, start) or not re.fullmatch(date_pat, end) or start > end:
        return jsonify({"error": "start/end 须为 YYYY-MM-DD 且 start ≤ end"}), 400
    strategies = body.get("strategies") or ["lianban", "dragon", "tailpan"]
    if not isinstance(strategies, list) or not strategies:
        return jsonify({"error": "strategies 须为非空数组"}), 400
    allowed = {"lianban", "dragon", "tailpan"}  # auction_grab 无历史竞价排行
    bad = set(strategies) - allowed
    if bad:
        return jsonify({"error": f"不可回测的策略: {sorted(bad)}"}), 400
    params = body.get("params") or {}
    if not isinstance(params, dict):
        return jsonify({"error": "params 须为对象"}), 400
    schema_doc = _load_schema_doc()
    for sid, vals in params.items():
        valid = {p["key"]: p for p in schema_doc.get("strategies", {}).get(sid, {}).get("params", [])}
        for k, v in (vals or {}).items():
            if k not in valid:
                return jsonify({"error": f"未知参数: {sid}.{k}"}), 400
            try:
                _coerce_param(valid[k], v)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

    if not _SANDBOX_LOCK.acquire(blocking=False):
        return jsonify({"error": "另一个沙箱/回测任务正在执行，请稍候"}), 409
    try:
        arglist = ["--start", start, "--end", end,
                   "--strategies", ",".join(strategies), "--throttle", "0.5"]
        if params:
            arglist += ["--params", json.dumps(params)]
        result, err = _run_sandbox(arglist, timeout=3600, module="quant_system.backtest")
    finally:
        _SANDBOX_LOCK.release()
    if err:
        return jsonify({"error": err}), 500
    if result.get("error"):
        return jsonify(result), 400
    log.info("批量回测: %s~%s %s by %s → %s 条建议",
             start, end, strategies, current_user().get("username", ""),
             result.get("entries", 0))
    return jsonify(result)


@app.route("/api/backtest/list")
def backtest_list():
    """历史回测 run 列表（摘要，倒序，最多 30 条）。"""
    out = []
    if BACKTEST_DIR.exists():
        runs = sorted((p for p in BACKTEST_DIR.iterdir() if p.is_dir()), reverse=True)[:30]
        for d in runs:
            rep_f = d / "report.json"
            if not rep_f.exists():
                continue
            try:
                doc = json.loads(rep_f.read_text(encoding="utf-8"))
                out.append({
                    "run_id": doc.get("run_id"), "start": doc.get("start"),
                    "end": doc.get("end"), "strategies": doc.get("strategies"),
                    "trading_days": doc.get("trading_days"),
                    "aggregate": doc.get("aggregate"),
                    "ran_at": doc.get("ran_at"),
                })
            except Exception:  # noqa: BLE001
                continue
    return jsonify({"items": out})


@app.route("/api/backtest/report/<run_id>")
def backtest_report(run_id: str):
    """单次回测完整报告（entries 最多 500 条防超大响应）。"""
    if not re.fullmatch(r"[A-Za-z0-9_]+", run_id):
        return jsonify({"error": "非法 run_id"}), 400
    f = BACKTEST_DIR / run_id / "report.json"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return jsonify({"error": f"报告不存在: {run_id}"}), 404
    if len(doc.get("entries") or []) > 500:
        doc["entries"] = doc["entries"][:500]
        doc["entries_truncated"] = True
    return jsonify(doc)


@app.route("/api/review")
def review_history():
    """复盘历史：最近 N 天的 review 报告（quant-system 盘后产出，advice 目录落盘）。"""
    days = min(max(request.args.get("days", 14, type=int) or 14, 1), 60)
    if not ADVICE_DIR:
        return jsonify({"items": [], "warning": "QUANT_ADVICE_DIR 未设置"})
    base = Path(ADVICE_DIR)
    today = datetime.now().strftime("%Y-%m-%d")
    items = []
    seen_dates = 0
    # 日期目录倒序扫描，取到 days 个"有复盘报告的交易日"为止
    for d in sorted(base.iterdir(), reverse=True):
        if not d.is_dir() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name):
            continue
        if d.name > today:
            continue
        reps = []
        for p in sorted(d.glob("review_*.json")):
            j = _read_json_file(p)
            if j is not None:
                reps.append(j)
        # 同日多份（重跑）按 ran_at 去重保最新：内容指纹同 advice 流
        dedup: dict = {}
        for j in reps:
            dedup[_advice_content_key(j)] = j
        if not dedup:
            continue
        items.extend(sorted(dedup.values(), key=lambda x: x.get("ran_at") or ""))
        seen_dates += 1
        if seen_dates >= days:
            break
    items.sort(key=lambda x: (x.get("advice_date") or x.get("date") or ""), reverse=True)
    return jsonify({"items": items})


# ======================  /advice（量化系统选股建议）  ======================
# 零侵入对接：quant-system 每次策略运行把建议落盘为
#   $QUANT_ADVICE_DIR/YYYY-MM-DD/<strategy>_<HHMMSS>.json
# 后端监听该目录，新文件出现 → 广播 WS + 提供 REST 查询。
ADVICE_DIR = os.environ.get("QUANT_ADVICE_DIR", "").rstrip("/")

_advice_seen = {}  # path -> mtime
_advice_content_seen = {}  # 内容指纹 -> path（同内容重跑只广播第一份）
_advice_seen_lock = threading.Lock()


def _read_json_file(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("file", path.name)
        # 候选池/周期判定等文件没有 ran_at → 用文件 mtime 兜底，前端统一按时间排序
        if not data.get("ran_at"):
            data["ran_at"] = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        return data
    except Exception as e:
        log.warning("advice 读取失败 %s: %s", path, e)
        return None


def _advice_content_key(j: dict) -> str:
    """内容指纹：剔除 file/ran_at 后哈希。

    调度器重跑会产出内容完全相同、仅文件名/时间戳不同的报告
    （如手动 --once postmarket 跑两遍），按内容去重只保留最新一份。
    """
    payload = {k: v for k, v in j.items() if k not in ("file", "ran_at")}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def advice_by_date(date_str: str) -> list:
    if not ADVICE_DIR:
        return []
    d = Path(ADVICE_DIR) / date_str
    if not d.is_dir():
        return []
    items = []
    for p in sorted(d.glob("*.json")):
        j = _read_json_file(p)
        # task_error 是引擎故障告警，不属于建议流（故障经 WS alert 提示）
        if j is not None and j.get("type") != "task_error":
            items.append(j)
    items.sort(key=lambda x: x.get("ran_at") or "")
    # 同内容去重：ran_at 升序遍历，同指纹保留最新一份
    dedup: dict = {}
    for j in items:
        dedup[_advice_content_key(j)] = j
    out = list(dedup.values())
    out.sort(key=lambda x: x.get("ran_at") or "")
    return out


def advice_watch_loop(interval=2.0, warmup_first=True):
    """监听 advice 目录：新文件/内容变化 → WS 广播 advice 频道"""
    if not ADVICE_DIR:
        log.info("QUANT_ADVICE_DIR 未设置 → advice 实时推送关闭（REST 仍可用需设置目录）")
        return
    log.info("advice 监听目录: %s", ADVICE_DIR)
    first_scan = True
    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            d = Path(ADVICE_DIR) / today
            if d.is_dir():
                for p in d.glob("*.json"):
                    try:
                        mtime = p.stat().st_mtime
                    except OSError:
                        continue
                    key = str(p)
                    with _advice_seen_lock:
                        known = _advice_seen.get(key)
                    if known == mtime:
                        continue
                    j = _read_json_file(p)
                    if j is None:
                        continue
                    ckey = _advice_content_key(j)
                    with _advice_seen_lock:
                        _advice_seen[key] = mtime
                        owner = _advice_content_seen.get(ckey)
                        dup = owner is not None and owner != key
                        if owner is None or owner == key:
                            _advice_content_seen[ckey] = key
                    # 引擎任务失败报告 → 全员告警（不进建议流，REST 列表同样排除）
                    if j.get("type") == "task_error":
                        if not (first_scan and warmup_first):
                            alert = engine_task_error_to_alert(j)
                            log.warning("引擎任务失败 → 告警广播: %s %s", alert["source"], alert["message"])
                            ws_broadcast(alert)
                        continue
                    # 首轮扫描只建基线，不广播（初始数据前端走 REST 拉）
                    if first_scan and warmup_first:
                        continue
                    if dup:
                        log.info("advice 重复内容跳过广播: %s（同 %s）", p.name, Path(owner).name)
                        continue
                    log.info("advice 更新 → 广播: %s", p.name)
                    ws_broadcast({"type": "advice", "data": j}, channel="advice")
            first_scan = False
        except Exception as e:
            log.warning("advice watch error: %s", e)
        time.sleep(interval)


POOL_NAMES = [
    "limit_up",
    "limit_up_broken",
    "yesterday_limit_up",
    "super_stock",
    "limit_down",
    "new_stock",
    "nearly_new",
]


def data_refresh_loop(interval=30):
    """行情快照定时广播：情绪/情绪历史/7池/快讯/主题/监管名单。

    前端为纯 WS 长连接模式：REST 只在连接建立时做一次初始加载，
    之后所有页面数据都靠本循环定时推送保持新鲜。
    advice（量化系统建议）由 advice_watch_loop 单独实时推送，不在此列。
    各 getter 受 20 次/分钟上游限频约束（TTL 合计 ≈11 次/分），
    超限或失败时自动返回旧值（stale），上游请求量与用户数无关。
    """
    time.sleep(3)  # 等服务起来
    _finalized_dates: set[str] = set()
    while True:
        try:
            ws_broadcast({"type": "sentiment", "data": get_sentiment()}, channel="sentiment")
            ws_broadcast(
                {"type": "sentiment_history", "data": get_sentiment_history(20)},
                channel="sentiment",
            )
            for name in POOL_NAMES:
                ws_broadcast(
                    {"type": "pool", "pool_name": name, "data": get_pool(name)},
                    channel="pool",
                )
            ws_broadcast({"type": "newsflash", "data": get_newsflash(50)}, channel="newsflash")
            ws_broadcast({"type": "theme", "data": get_themes()}, channel="themes")
            ws_broadcast({"type": "monitor", "data": get_monitor()}, channel="monitor")
            # 连板天梯：先落盘当日涨停池快照（数据源），再聚合广播
            persist_limit_up_snapshot()
            ws_broadcast({"type": "ladder", "data": get_ladder(30)}, channel="ladder")

            # 15:30 收盘后：当日情绪日结定稿（终态，此后不再被覆盖）
            today = datetime.now().strftime("%Y-%m-%d")
            if today not in _finalized_dates and datetime.now().strftime("%H:%M") >= "15:30":
                dbm.save_daily_snapshot(today, {}, finalized=True)
                _finalized_dates.add(today)
                log.info("当日情绪日结已定稿: %s", today)
        except Exception as e:
            log.warning("data refresh error: %s", e)
        # 上游接口故障 → 全员告警（引擎 task_error 由 advice_watch_loop 单独广播）
        for alert in _drain_upstream_alerts():
            log.warning("广播上游故障告警: %s %s", alert["source"], alert["message"])
            ws_broadcast(alert)
        time.sleep(interval)


@app.route("/api/advice")
def advice_api():
    """当日（或指定日期）全部建议，按 ran_at 升序"""
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    if not ADVICE_DIR:
        return jsonify({"date": date, "items": [], "warning": "QUANT_ADVICE_DIR 未设置"})
    return jsonify({"date": date, "items": advice_by_date(date)})


@app.route("/api/advice/latest")
def advice_latest_api():
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    items = advice_by_date(date)
    return jsonify(items[-1] if items else None)


# ======================  静态托管前端 build（生产模式）  ======================
# 设置 QUANT_WEB_DIST=<dist 目录> 后，同一端口 serve 前端 + REST + WS
DIST_DIR = os.environ.get("QUANT_WEB_DIST", "").rstrip("/")

if DIST_DIR:
    @app.route("/")
    def spa_index():
        return send_from_directory(DIST_DIR, "index.html")

    @app.route("/<path:path>")
    def spa_assets(path):
        full = Path(DIST_DIR) / path
        if full.is_file():
            return send_from_directory(DIST_DIR, path)
        # SPA 兜底：非文件路径全部回 index.html
        return send_from_directory(DIST_DIR, "index.html")


# ======================  /health  ======================
@app.route("/health")
@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "token_loaded": bool(TOKEN),
        "cache_keys": list(_cache.keys()),
        "ts": now_iso(),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))

    # 冷启动：从 SQLite 装载上次快照进内存缓存（ts=0 → 视为过期，
    # 首次请求照常触发刷新；刷新失败/限频时立即回这份旧值而非报错）
    try:
        for _key, _payload in dbm.load_all_snapshots().items():
            _cache[_key] = {"data": _payload, "ts": 0.0}
        if _cache:
            log.info("冷启动装载快照 %d 个 key", len(_cache))
    except Exception:  # noqa: BLE001
        log.exception("冷启动装载快照失败")

    log.info("上游限频: %d 次/分钟", UPSTREAM_RPM)
    log.info("启动选股通看板后端，端口 %d", port)
    log.info("token: %s", "已加载" if TOKEN else "❌ 未设置 XUANGUTONG_IVANKA_TOKEN")
    log.info("advice 目录: %s", ADVICE_DIR or "未设置（WS 不推送建议）")
    if DIST_DIR:
        log.info("前端静态托管: %s", DIST_DIR)

    # 后台线程：WS 心跳 + advice 目录监听 + 行情快照广播
    threading.Thread(target=ws_heartbeat_loop, daemon=True).start()
    threading.Thread(target=advice_watch_loop, daemon=True).start()
    threading.Thread(target=data_refresh_loop, daemon=True).start()

    # Funnel 模式下只监听本地（Funnel 在边缘节点终结 HTTPS 再隧道转进来）；
    # Docker 部署设 HOST=0.0.0.0（容器端口映射仍可绑宿主机 127.0.0.1）
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False)