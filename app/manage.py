"""运维命令。用法:
  python -m app.manage create-admin [--username admin]      交互输入密码(不回显、不写日志)
  python -m app.manage create-user --username u --role operator --display-name 名 [--owner-name 归属人] --password-file f
  python -m app.manage encrypt-credentials --dry-run        只统计明文凭据条数,不改库
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path


def _boot():
    from .config import load_config
    from .db import init_db
    from . import auth
    cfg = load_config()
    init_db(cfg.db_path)
    data_dir = Path(cfg.db_path).expanduser().resolve().parent
    auth._state["secret"] = b"cli"  # CLI 不签发会话
    return cfg, data_dir


def _read_password(args) -> str:
    if getattr(args, "password_file", None):
        return Path(args.password_file).read_text().strip()
    p1 = getpass.getpass("新密码(至少 8 位): ")
    p2 = getpass.getpass("再输入一次: ")
    if p1 != p2:
        sys.exit("两次输入不一致")
    return p1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.manage")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--username", default="admin")
    a.add_argument("--password-file")
    u = sub.add_parser("create-user")
    u.add_argument("--username", required=True)
    u.add_argument("--role", required=True, choices=["admin", "manager", "operator", "viewer"])
    u.add_argument("--display-name", default="")
    u.add_argument("--owner-name")
    u.add_argument("--password-file")
    e = sub.add_parser("encrypt-credentials")
    e.add_argument("--dry-run", action="store_true", default=True)
    e.add_argument("--apply", action="store_true", help="(未实现)真正加密写库")
    args = ap.parse_args(argv)
    _cfg, data_dir = _boot()
    from . import auth
    if args.cmd == "create-admin":
        user = auth.create_user(args.username, _read_password(args), "admin", "管理员", "")
        print(f"已创建管理员 {user.username}")
    elif args.cmd == "create-user":
        user = auth.create_user(args.username, _read_password(args), args.role,
                                args.display_name, args.owner_name)
        print(f"已创建用户 {user.username}({user.role},归属人={user.owner_name or '—'})")
    elif args.cmd == "encrypt-credentials":
        from sqlmodel import select
        from .db import get_session
        from .models import DouyinAccount
        from . import credentials_crypto as cc
        stats = {f: {"plain": 0, "encrypted": 0} for f in cc.FIELDS}
        with get_session() as s:
            for acc in s.exec(select(DouyinAccount)).all():
                for f in cc.FIELDS:
                    v = getattr(acc, f, "") or ""
                    if f == "proxy" and "@" not in v:
                        continue  # 无密码的代理不算凭据
                    if v:
                        stats[f]["encrypted" if cc.is_encrypted(v) else "plain"] += 1
        print("凭据字段统计(只计数,不输出内容):")
        for f, v in stats.items():
            print(f"  {f}: 明文 {v['plain']} 条,已加密 {v['encrypted']} 条")
        print(f"cryptography 可用: {cc.available()};密钥文件: {'存在' if cc.load_key(data_dir) else '不存在'}")
        if args.apply:
            print("未执行:落库加密需同时改造 main.py/engine 中所有读写凭据处,当前版本只提供 dry-run。")
        else:
            print("dry-run:未修改数据库。")


if __name__ == "__main__":
    main()
