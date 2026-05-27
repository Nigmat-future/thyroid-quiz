"""创建初始 admin 账号。

使用：
    python -m scripts.init_admin

读取 .env 中：
    INIT_ADMIN_USERNAME / INIT_ADMIN_PASSWORD / INIT_ADMIN_DISPLAY_NAME

如果该用户名已存在：
    - 已是 admin → 不做任何修改
    - 不是 admin → 升级为 admin（不重置密码）
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import ROLE_ADMIN, User
from app.security import hash_password


def main() -> int:
    username = settings.init_admin_username.strip()
    password = settings.init_admin_password
    display = settings.init_admin_display_name.strip() or None

    if not username or not password:
        print("[init_admin] 用户名或密码为空，已跳过。", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing is not None:
            if existing.role == ROLE_ADMIN:
                print(f"[init_admin] '{username}' 已存在且是 admin，未做修改。")
                return 0
            existing.role = ROLE_ADMIN
            existing.is_active = 1
            db.commit()
            print(f"[init_admin] '{username}' 已升级为 admin（密码未改）。")
            return 0

        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=display,
            role=ROLE_ADMIN,
            is_active=1,
        )
        db.add(user)
        db.commit()
        print(f"[init_admin] 已创建 admin 账号 '{username}'。请登录后立即修改密码。")
        return 0


if __name__ == "__main__":
    sys.exit(main())
