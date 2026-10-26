"""凭据落库加密工具(设计 + 工具函数,默认不启用)。

- 算法: Fernet(AES-128-CBC + HMAC-SHA256),依赖 `cryptography` 包;当前环境未安装,
  故本模块在缺依赖时只做识别/统计,不加密、不改库。
- 密钥: 数据目录 secret.key(600),不入库不入 git。
- 密文前缀 "enc:v1:",读取时自动识别;无前缀视为历史明文,兼容读取。
"""
from __future__ import annotations

import os
from pathlib import Path

PREFIX = "enc:v1:"
FIELDS = ("cookie", "storage_state", "creator_storage_state", "proxy")

try:  # 可选依赖
    from cryptography.fernet import Fernet  # type: ignore
except ImportError:  # pragma: no cover
    Fernet = None


def available() -> bool:
    return Fernet is not None


def load_key(data_dir: str | Path, create: bool = False) -> bytes | None:
    path = Path(data_dir) / "secret.key"
    if path.exists():
        return path.read_bytes().strip()
    if not create or Fernet is None:
        return None
    key = Fernet.generate_key()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    return key


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(value: str, key: bytes) -> str:
    if not value or is_encrypted(value):
        return value
    if Fernet is None:
        raise RuntimeError("未安装 cryptography,无法加密")
    return PREFIX + Fernet(key).encrypt(value.encode()).decode()


def decrypt(value: str, key: bytes | None) -> str:
    """透明解密:明文原样返回(兼容历史数据)。"""
    if not is_encrypted(value):
        return value
    if Fernet is None or not key:
        raise RuntimeError("数据已加密,但缺少 cryptography 或 secret.key")
    return Fernet(key).decrypt(value[len(PREFIX):].encode()).decode()
