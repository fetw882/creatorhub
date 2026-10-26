"""运营看板 GET /api/dashboard:按当前登录用户的可见账号范围汇总。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlmodel import func, select

from .auth import visible_account_ids
from .db import get_session
from .models import (AccountActionTask, AccountWork, CommentTask, DmConversation, DouyinAccount,
                     KeywordCollectionJob, PublishTask)

router = APIRouter()
UNASSIGNED = "未分配"
FAILED = {"failed", "partial", "uncertain"}
TASKS = ((KeywordCollectionJob, {"pending", "running"}),
         (PublishTask, {"draft", "pending", "publishing"}),
         (CommentTask, {"draft", "pending", "doing"}),
         (AccountActionTask, {"draft", "pending", "doing"}))
CST = timezone(timedelta(hours=8))


def _tags(raw: str) -> list[str]:
    try:
        v = json.loads(raw or "[]")
        return [str(t) for t in v if str(t).strip()] if isinstance(v, list) else []
    except ValueError:
        return []


def _iso(dt):
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


@router.get("/api/dashboard")
async def dashboard(request: Request, days: int = 7):
    user = request.scope.get("team_user")
    days = 30 if days >= 30 else 7
    ids_scope = visible_account_ids(user) if user else set()
    detail = user is None or user.role != "viewer"   # viewer 只看汇总,不给逐号明细中的私信等
    with get_session() as s:
        stmt = select(DouyinAccount).order_by(DouyinAccount.id)
        accounts = [a for a in s.exec(stmt).all() if ids_scope is None or a.id in ids_scope]
        ids = [a.id for a in accounts]
        works, synced, unread = {}, {}, {}
        tasks = {i: {"total": 0, "failed": 0} for i in ids}
        trend_raw: list[tuple[int, int]] = []
        if ids:
            for aid, cnt, last in s.exec(select(AccountWork.account_id, func.count(AccountWork.id),
                                                func.max(AccountWork.fetched_at))
                                         .where(AccountWork.account_id.in_(ids))
                                         .group_by(AccountWork.account_id)).all():
                works[aid], synced[aid] = int(cnt or 0), last
            for aid, total in s.exec(select(DmConversation.account_id, func.sum(DmConversation.unread_count))
                                     .where(DmConversation.account_id.in_(ids))
                                     .group_by(DmConversation.account_id)).all():
                unread[aid] = int(total or 0)
            for model, states in TASKS:
                for aid, st in s.exec(select(model.account_id, model.status).where(
                        model.account_id.in_(ids), model.status.in_(list(states | FAILED)))).all():
                    tasks[aid]["total"] += 1
                    tasks[aid]["failed"] += 1 if st in FAILED else 0
            trend_raw = list(s.exec(select(AccountWork.account_id, AccountWork.create_time)
                                    .where(AccountWork.account_id.in_(ids))).all())
    now = datetime.utcnow()
    stale_before = now - timedelta(hours=24)
    rows, owners, platforms, status_count = [], {}, {}, {}
    for a in accounts:
        owner = (a.owner or "").strip() or UNASSIGNED
        last = synced.get(a.id)
        t = tasks.get(a.id, {"total": 0, "failed": 0})
        row = {"id": a.id, "platform": a.platform, "nickname": a.nickname, "owner": owner,
               "status": a.status or "", "tags": _tags(a.tags),
               "follower_count": int(a.follower_count or 0), "works": works.get(a.id, 0),
               "unread_dm": unread.get(a.id, 0) if detail else None, "tasks": t,
               "last_synced": _iso(last), "stale": (last is None) or last < stale_before}
        rows.append(row)
        g = owners.setdefault(owner, {"owner": owner, "accounts": 0, "active_accounts": 0, "works": 0,
                                      "followers": 0, "unread_dm": 0, "tasks": 0, "failed_tasks": 0})
        g["accounts"] += 1
        g["active_accounts"] += 1 if (a.status or "") == "active" else 0
        g["works"] += row["works"]
        g["followers"] += row["follower_count"]
        g["unread_dm"] += unread.get(a.id, 0)
        g["tasks"] += t["total"]
        g["failed_tasks"] += t["failed"]
        platforms[a.platform] = platforms.get(a.platform, 0) + 1
        status_count[row["status"] or "unknown"] = status_count.get(row["status"] or "unknown", 0) + 1
    if not detail:
        # viewer:去掉逐号的私信字段,只保留汇总值
        for r in rows:
            r.pop("unread_dm", None)
    today = datetime.now(CST).date()
    labels = [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    index = {d: i for i, d in enumerate(labels)}
    counts = [0] * days
    for _aid, ts in trend_raw:
        if ts:
            i = index.get(datetime.fromtimestamp(int(ts), CST).date().isoformat())
            if i is not None:
                counts[i] += 1
    synced_all = [v for v in synced.values() if v]
    newest = max(synced_all) if synced_all else None
    return {
        "role": user.role if user else None,
        "scope": "own" if ids_scope is not None else "all",
        "cards": {
            "accounts": len(accounts),
            "active_accounts": sum(1 for a in accounts if (a.status or "") == "active"),
            "works": sum(works.values()),
            "followers": sum(int(a.follower_count or 0) for a in accounts),
            "unread_dm": sum(unread.values()),
            "tasks": sum(t["total"] for t in tasks.values()),
            "failed_tasks": sum(t["failed"] for t in tasks.values()),
        },
        "owners": sorted(owners.values(), key=lambda g: (g["owner"] == UNASSIGNED, -g["works"], g["owner"])),
        "platforms": [{"platform": k, "accounts": v} for k, v in sorted(platforms.items())],
        "statuses": status_count,
        "accounts": rows,
        "trend": {"days": labels, "works": counts,
                  "basis": "已同步作品的发布时间(AccountWork.create_time,东八区)"},
        "last_synced": _iso(newest),
        "stale": newest is None or newest < stale_before,
        "generated_at": _iso(now),
    }
