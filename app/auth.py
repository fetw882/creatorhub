"""运营部团队版:多人登录、角色权限、归属过滤、敏感字段脱敏。

设计要点
- 密码: hashlib.pbkdf2_hmac(sha256, 随机盐, 260000 轮),不引入新依赖。
- 会话: 随机 token 放 HttpOnly + SameSite=Lax Cookie;库里只存 HMAC(secret, token),
  secret 首次启动生成在数据目录 auth-secret.key (600),不入库不入 git。
- 权限: 纯 ASGI 中间件按「方法 + 路由」归类;未归类的 /api 路由默认仅 admin。
- 归属: operator 只能访问 owner == 自己 owner_name 的账号;列表接口按 account_id 过滤响应。
- 脱敏: 所有 JSON 响应递归去掉 cookie / storage_state / creator_storage_state / 密码类字段,
  代理 URL 中的密码替换为 ***。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import select

from .db import get_session
from .models import DouyinAccount, TeamSession, TeamUser

log = logging.getLogger("creatorhub.auth")

ROLES = ("admin", "manager", "operator", "viewer")
ROLE_LABELS = {"admin": "管理员", "manager": "部门主管", "operator": "运营", "viewer": "只读观察者"}
COOKIE_NAME = "ch_session"
SESSION_HOURS = 12
PBKDF2_ROUNDS = 260_000
LOCK_FAILS, LOCK_SECONDS = 5, 300

_state: dict[str, Any] = {"secret": b"", "data_dir": None}

# ─────────── 密钥 / 密码 ───────────

def init_auth(data_dir: str | Path) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / "auth-secret.key"
    if not key_file.exists():
        fd = os.open(str(key_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(secrets.token_hex(32))
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    _state["secret"] = key_file.read_text().strip().encode()
    _state["data_dir"] = data_dir
    bootstrap_admin()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(calc.hex(), digest)
    except (ValueError, AttributeError):
        return False


def _token_hash(token: str) -> str:
    return hmac.new(_state["secret"], token.encode(), hashlib.sha256).hexdigest()


def validate_password(password: str) -> None:
    if len(password or "") < 8:
        raise HTTPException(422, "密码至少 8 位")


def create_user(username: str, password: str, role: str, display_name: str = "",
                owner_name: str | None = None) -> TeamUser:
    username = (username or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{2,32}", username):
        raise HTTPException(422, "用户名需为 2-32 位字母、数字、下划线、点或横线")
    if role not in ROLES:
        raise HTTPException(422, "角色无效")
    validate_password(password)
    display_name = (display_name or "").strip()[:40] or username
    with get_session() as s:
        if s.exec(select(TeamUser).where(TeamUser.username == username)).first():
            raise HTTPException(409, "用户名已存在")
        user = TeamUser(username=username, display_name=display_name,
                        owner_name=(owner_name if owner_name is not None else display_name).strip()[:40],
                        password_hash=hash_password(password), role=role)
        s.add(user)
        s.commit()
        s.refresh(user)
        return user


def bootstrap_admin() -> None:
    with get_session() as s:
        if s.exec(select(TeamUser.id)).first():
            return
    password = os.environ.get("CREATORHUB_ADMIN_PASSWORD", "")
    if password:
        create_user(os.environ.get("CREATORHUB_ADMIN_USERNAME", "admin"), password, "admin", "管理员", "")
        log.warning("已根据环境变量 CREATORHUB_ADMIN_PASSWORD 创建首个管理员(密码不写日志)")
    else:
        log.warning("尚无任何登录用户:请运行 `python -m app.manage create-admin` 创建管理员,"
                    "或设置环境变量 CREATORHUB_ADMIN_PASSWORD 后重启")


def public_user(u: TeamUser) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "owner_name": u.owner_name, "role": u.role, "role_label": ROLE_LABELS.get(u.role, u.role),
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() + "Z" if u.created_at else None,
            "last_login_at": u.last_login_at.isoformat() + "Z" if u.last_login_at else None}


def user_from_token(token: str) -> Optional[TeamUser]:
    if not token or not _state["secret"]:
        return None
    with get_session() as s:
        sess = s.exec(select(TeamSession).where(TeamSession.token_hash == _token_hash(token))).first()
        if not sess or sess.expires_at < datetime.utcnow():
            return None
        user = s.get(TeamUser, sess.user_id)
        if not user or not user.is_active:
            return None
        s.expunge(user)
        return user


def visible_account_ids(user: TeamUser) -> Optional[set[int]]:
    """None = 全部可见;否则为可见账号 id 集合。"""
    if user.role in ("admin", "manager", "viewer"):
        return None
    owner = (user.owner_name or "").strip()
    if not owner:
        return set()
    with get_session() as s:
        return {i for i in s.exec(select(DouyinAccount.id).where(DouyinAccount.owner == owner)).all()}


# ─────────── 登录限流 ───────────
_fails: dict[str, list[float]] = {}


def _locked(key: str) -> float:
    now = time.time()
    items = [t for t in _fails.get(key, []) if now - t < LOCK_SECONDS]
    _fails[key] = items
    if len(items) >= LOCK_FAILS:
        return LOCK_SECONDS - (now - items[-1])
    return 0


def _fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.time())


# ─────────── 路由 ───────────
router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/api/auth/login")
async def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    keys = [f"u:{body.username.strip().lower()}", f"ip:{ip}"]
    wait = max(_locked(k) for k in keys)
    if wait > 0:
        raise HTTPException(429, f"登录失败次数过多,请 {int(wait) + 1} 秒后再试")
    with get_session() as s:
        user = s.exec(select(TeamUser).where(TeamUser.username == body.username.strip())).first()
        ok = bool(user and user.is_active and verify_password(body.password, user.password_hash))
        if not ok:
            for k in keys:
                _fail(k)
            raise HTTPException(401, "用户名或密码错误,或账号已停用")
        for k in keys:
            _fails.pop(k, None)
        token = secrets.token_urlsafe(32)
        now = datetime.utcnow()
        s.add(TeamSession(token_hash=_token_hash(token), user_id=user.id,
                          expires_at=now + timedelta(hours=SESSION_HOURS)))
        user.last_login_at = now
        s.add(user)
        # 顺手清理过期会话
        for old in s.exec(select(TeamSession).where(TeamSession.expires_at < now)).all():
            s.delete(old)
        s.commit()
        s.refresh(user)
        data = public_user(user)
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_HOURS * 3600, httponly=True,
                        samesite="lax", path="/",
                        secure=os.environ.get("CREATORHUB_COOKIE_SECURE") == "1")
    return {"ok": True, "user": data}


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        with get_session() as s:
            for sess in s.exec(select(TeamSession).where(TeamSession.token_hash == _token_hash(token))).all():
                s.delete(sess)
            s.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
async def me(request: Request):
    user = user_from_token(request.cookies.get(COOKIE_NAME, ""))
    if not user:
        raise HTTPException(401, "未登录")
    return {"user": public_user(user)}


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "viewer"
    display_name: str = ""
    owner_name: Optional[str] = None


class UserPatch(BaseModel):
    role: Optional[str] = None
    display_name: Optional[str] = None
    owner_name: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


@router.get("/api/auth/users")
async def list_users():
    with get_session() as s:
        users = s.exec(select(TeamUser).order_by(TeamUser.id)).all()
        owners = sorted({o for o in s.exec(select(DouyinAccount.owner)).all() if o})
        return {"users": [public_user(u) for u in users], "roles": ROLE_LABELS, "owners": owners}


@router.post("/api/auth/users")
async def add_user(body: UserIn):
    return {"user": public_user(create_user(body.username, body.password, body.role,
                                            body.display_name, body.owner_name))}


def _admin_count(s) -> int:
    return len(s.exec(select(TeamUser.id).where(TeamUser.role == "admin", TeamUser.is_active == True)).all())  # noqa: E712


@router.patch("/api/auth/users/{user_id}")
async def update_user(user_id: int, body: UserPatch, request: Request):
    me_user = request.scope.get("team_user")
    with get_session() as s:
        u = s.get(TeamUser, user_id)
        if not u:
            raise HTTPException(404, "用户不存在")
        losing_admin = u.role == "admin" and ((body.role and body.role != "admin") or body.is_active is False)
        if losing_admin and _admin_count(s) <= 1:
            raise HTTPException(409, "至少要保留一个启用的管理员")
        if me_user and me_user.id == u.id and body.is_active is False:
            raise HTTPException(409, "不能停用自己")
        if body.role is not None:
            if body.role not in ROLES:
                raise HTTPException(422, "角色无效")
            u.role = body.role
        if body.display_name is not None:
            u.display_name = body.display_name.strip()[:40] or u.username
        if body.owner_name is not None:
            u.owner_name = body.owner_name.strip()[:40]
        if body.password:
            validate_password(body.password)
            u.password_hash = hash_password(body.password)
        if body.is_active is not None:
            u.is_active = body.is_active
        if body.password or body.is_active is False or body.role is not None:
            # 改密/停用/改角色后让该用户已有会话全部失效
            for sess in s.exec(select(TeamSession).where(TeamSession.user_id == u.id)).all():
                s.delete(sess)
        s.add(u)
        s.commit()
        s.refresh(u)
        return {"user": public_user(u)}


@router.delete("/api/auth/users/{user_id}")
async def delete_user(user_id: int, request: Request):
    me_user = request.scope.get("team_user")
    with get_session() as s:
        u = s.get(TeamUser, user_id)
        if not u:
            raise HTTPException(404, "用户不存在")
        if me_user and me_user.id == u.id:
            raise HTTPException(409, "不能删除自己")
        if u.role == "admin" and _admin_count(s) <= 1:
            raise HTTPException(409, "至少要保留一个启用的管理员")
        for sess in s.exec(select(TeamSession).where(TeamSession.user_id == u.id)).all():
            s.delete(sess)
        s.delete(u)
        s.commit()
    return {"ok": True}


# ─────────── 路由权限表 ───────────
# 级别: public | any | scoped_list | manager | acct_read | acct_write | admin
_ACC = r"(?P<aid>\d+)"
RULES: list[tuple[str, str, str]] = [
    ("*", r"/api/auth/(login|logout|me)", "public"),
    ("*", r"/api/auth/users(/\d+)?", "admin"),
    ("GET", r"/api/dashboard", "any"),
    # 账号列表/总览:operator 只看到自己的号(响应过滤)
    ("GET", r"/api/accounts", "scoped_list"),
    ("GET", r"/api/accounts/workbench", "scoped_list"),
    ("GET", r"/api/overview/owners", "scoped_list"),
    ("GET", r"/api/dm/inbox", "scoped_list"),
    # 单账号只读(需带 account_id)
    ("GET", r"/api/account-works", "acct_read"),
    ("GET", r"/api/dm/conversations", "acct_read"),
    ("GET", r"/api/dm/messages", "acct_read"),
    ("GET", rf"/api/account-stats/{_ACC}", "acct_read"),
    ("GET", rf"/api/accounts/{_ACC}/dm/automation/status", "acct_read"),
    # 单账号写:admin + 归属 operator
    ("PATCH", rf"/api/accounts/{_ACC}", "acct_write"),
    ("POST", rf"/api/accounts/{_ACC}/works/sync", "acct_write"),
    ("POST", rf"/api/accounts/{_ACC}/dm/sync", "acct_write"),
    ("POST", rf"/api/accounts/{_ACC}/refresh-profile", "acct_write"),
    # 全局只读汇总:admin + manager
    ("GET", r"/api/overview/summary", "manager"),
    ("GET", r"/api/stats/series", "manager"),
    ("GET", r"/api/hub/summary", "manager"),
    ("GET", r"/api/task-queue", "manager"),
    ("GET", r"/api/risk-control/summary", "manager"),
    ("GET", r"/api/risk-control/accounts", "manager"),
    ("GET", r"/api/account-operations", "manager"),
    ("GET", r"/api/account-actions", "manager"),
    ("GET", r"/api/publish", "manager"),
    ("GET", r"/api/publish/published", "manager"),
    ("GET", r"/api/browser-backends", "manager"),
    ("GET", r"/api/settings/transport-matrix", "manager"),
]
_COMPILED = [(m, re.compile(p + r"/?"), lvl) for m, p, lvl in RULES]


def classify(method: str, path: str) -> tuple[str, Optional[int]]:
    for m, rx, lvl in _COMPILED:
        if m not in ("*", method):
            continue
        hit = rx.fullmatch(path)
        if hit:
            aid = hit.groupdict().get("aid")
            return lvl, int(aid) if aid else None
    return "admin", None  # 未归类 → 默认仅管理员


def is_allowed(level: str, user: TeamUser, account_id: Optional[int]) -> bool:
    role = user.role
    if role == "admin" or level in ("public", "any"):
        return True
    if level == "manager":
        return role == "manager"
    if level == "scoped_list":
        return role in ("manager", "operator")
    if level == "acct_read":
        if role == "manager":
            return True
        if role == "operator" and account_id is not None:
            ids = visible_account_ids(user)
            return ids is not None and account_id in ids
        return False
    if level == "acct_write":
        if role == "operator" and account_id is not None:
            ids = visible_account_ids(user)
            return ids is not None and account_id in ids
        return False
    return False


# ─────────── 脱敏 ───────────
SENSITIVE_KEYS = {"cookie", "cookies", "storage_state", "creator_storage_state",
                  "password_hash", "proxy_password", "token_hash"}
_PROXY_CRED = re.compile(r"(?P<scheme>[a-zA-Z0-9+.\-]+://)(?P<user>[^:@/\s]*):(?P<pw>[^@/\s]+)@")


def scrub(value: Any, mask_urls: bool = True) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in SENSITIVE_KEYS:
                continue
            out[k] = scrub(v, mask_urls)
        return out
    if isinstance(value, list):
        return [scrub(v, mask_urls) for v in value]
    if mask_urls and isinstance(value, str) and "@" in value and "://" in value:
        return _PROXY_CRED.sub(lambda m: f"{m['scheme']}{m['user']}:***@", value)
    return value


def scope_filter(path: str, data: Any, user: TeamUser) -> Any:
    ids = visible_account_ids(user)
    if ids is None:
        return data
    if path.rstrip("/") == "/api/overview/owners" and isinstance(data, dict):
        owners = [g for g in data.get("owners", []) if g.get("owner") == user.owner_name]
        for g in owners:
            g["account_items"] = [i for i in g.get("account_items", []) if i.get("id") in ids]
        data["owners"] = owners
        data["total_accounts"] = sum(len(g["account_items"]) for g in owners)
        return data
    is_account_list = path.rstrip("/") in ("/api/accounts", "/api/accounts/workbench")

    def keep(item: Any) -> bool:
        if not isinstance(item, dict):
            return True
        if "account_id" in item and isinstance(item["account_id"], int):
            return item["account_id"] in ids
        if is_account_list and "id" in item and "platform" in item:
            return item["id"] in ids
        return True

    def walk(v: Any) -> Any:
        if isinstance(v, list):
            return [walk(i) for i in v if keep(i)]
        if isinstance(v, dict):
            return {k: walk(i) for k, i in v.items()}
        return v
    return walk(data)


# ─────────── 中间件 ───────────
def _cookie(scope) -> str:
    for k, v in scope.get("headers", []):
        if k == b"cookie":
            for part in v.decode("latin-1").split(";"):
                name, _, val = part.strip().partition("=")
                if name == COOKIE_NAME:
                    return val
    return ""


class TeamAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if scope["type"] != "http" or not (path == "/api" or path.startswith("/api/")):
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        level, aid = classify(method, path)
        user = None
        if level != "public":
            user = user_from_token(_cookie(scope))
            if not user:
                await JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)(scope, receive, send)
                return
            scope["team_user"] = user
            if aid is None and level in ("acct_read", "acct_write"):
                qs = parse_qs(scope.get("query_string", b"").decode())
                try:
                    aid = int((qs.get("account_id") or [""])[0])
                except ValueError:
                    aid = None
            if not is_allowed(level, user, aid):
                await JSONResponse({"detail": "当前角色无权访问该账号或执行该操作"},
                                   status_code=403)(scope, receive, send)
                return
            # operator 改自己的号:只允许改标签
            if level == "acct_write" and method == "PATCH" and user.role == "operator":
                body = b""
                while True:
                    msg = await receive()
                    body += msg.get("body", b"")
                    if not msg.get("more_body"):
                        break
                try:
                    payload = json.loads(body or b"{}")
                except ValueError:
                    payload = None
                if not isinstance(payload, dict) or set(payload) - {"tags"}:
                    await JSONResponse({"detail": "运营只能修改自己账号的标签"},
                                       status_code=403)(scope, receive, send)
                    return
                sent = {"done": False}

                async def replay():
                    if not sent["done"]:
                        sent["done"] = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()
                receive = replay

        # 缓冲 JSON 响应以便脱敏/过滤;流式、文件、SSE 原样透传
        start: dict = {}
        chunks: list[bytes] = []
        buffering = {"on": False}

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                ctype = b""
                for k, v in message.get("headers", []):
                    if k.lower() == b"content-type":
                        ctype = v
                if ctype.startswith(b"application/json"):
                    buffering["on"] = True
                    start.update(message)
                    return
                await send(message)
                return
            if message["type"] == "http.response.body" and buffering["on"]:
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                raw = b"".join(chunks)
                try:
                    data = json.loads(raw) if raw else None
                    # 管理员在代理池页需要原始代理 URL 才能编辑/分配,其余处一律打码
                    admin_proxy_page = bool(user and user.role == "admin" and path.startswith("/api/proxies"))
                    data = scrub(data, mask_urls=not admin_proxy_page)
                    if user is not None and level == "scoped_list" and start.get("status", 200) < 400:
                        data = scope_filter(path, data, user)
                    raw = json.dumps(data, ensure_ascii=False).encode()
                except ValueError:
                    pass
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(raw)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": raw})
                return
            await send(message)

        await self.app(scope, receive, wrapped_send)
