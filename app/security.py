"""密码哈希工具。直接用 bcrypt，避免引入 passlib。"""

from __future__ import annotations

import bcrypt

PASSWORD_MIN = 6
PASSWORD_MAX = 128
USERNAME_MIN = 3
USERNAME_MAX = 32


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 哈希；返回字符串以便存数据库。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """验证明文密码是否匹配；密码或哈希异常一律返回 False。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
