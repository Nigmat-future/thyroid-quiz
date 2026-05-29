"""密码哈希工具。直接用 bcrypt，避免引入 passlib。"""

from __future__ import annotations

import bcrypt

PASSWORD_MIN = 6
PASSWORD_MAX = 128
USERNAME_MIN = 3
USERNAME_MAX = 32

# bcrypt 只认前 72 字节，更长会直接抛 ValueError（bcrypt>=4）。
# 统一在哈希/校验两端按 UTF-8 截断到 72 字节，避免长密码（尤其中文）触发 500。
BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 哈希；返回字符串以便存数据库。"""
    return bcrypt.hashpw(_to_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """验证明文密码是否匹配；密码或哈希异常一律返回 False。"""
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
