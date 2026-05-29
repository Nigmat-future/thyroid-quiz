"""M1 鉴权系统测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _register(client: TestClient, username: str = "drwang", password: str = "secret123",
              display: str | None = "王医生"):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "display_name": display},
    )


def test_register_creates_doctor_and_logs_in(client: TestClient) -> None:
    resp = _register(client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "drwang"
    assert body["display_name"] == "王医生"
    assert body["role"] == "doctor"
    assert body["is_active"] == 1
    assert "password_hash" not in body

    # 注册后已登录，/api/me 直接可用
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["username"] == "drwang"


def test_register_dup_username_returns_409(client: TestClient) -> None:
    assert _register(client, username="alice").status_code == 201
    other = TestClient(client.app)
    resp = _register(other, username="alice", password="anothersecret")
    assert resp.status_code == 409


def test_register_duplicate_race_returns_409(client: TestClient) -> None:
    """查重与提交之间若发生同名插入，数据库唯一约束也应映射为 409。"""
    from app.db import SessionLocal, get_db
    from app.main import app as fastapi_app
    from app.models import ROLE_DOCTOR, User
    from app.security import hash_password

    with SessionLocal() as db:
        db.add(
            User(
                username="racer",
                password_hash=hash_password("secret123"),
                role=ROLE_DOCTOR,
                is_active=1,
            )
        )
        db.commit()

    class RaceSession:
        def __init__(self) -> None:
            self._db = SessionLocal()
            self._scalar_calls = 0

        def scalar(self, statement):
            self._scalar_calls += 1
            if self._scalar_calls == 1:
                return None
            return self._db.scalar(statement)

        def __getattr__(self, name: str):
            return getattr(self._db, name)

        def close(self) -> None:
            self._db.close()

    def override_db():
        db = RaceSession()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_db
    try:
        other = TestClient(fastapi_app)
        resp = _register(other, username="racer", password="anothersecret")
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 409, resp.text


def test_register_invalid_username(client: TestClient) -> None:
    # 太短
    assert _register(client, username="ab").status_code == 422
    # 含非法字符
    resp = client.post(
        "/api/auth/register",
        json={"username": "bad name!", "password": "secret123"},
    )
    assert resp.status_code in (400, 422)


def test_register_short_password(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/register",
        json={"username": "carol", "password": "123"},
    )
    assert resp.status_code == 422


def test_long_password_does_not_500_and_can_login(client: TestClient) -> None:
    """>72 字节的密码（含中文）注册不应 500，且能正常登录。

    回归 bcrypt>=4 对超 72 字节密码抛 ValueError 的问题。
    """
    long_pw = "密码" * 20  # 40 字 → 120 字节 UTF-8，远超 72
    resp = _register(client, username="longpw", password=long_pw, display=None)
    assert resp.status_code == 201, resp.text

    other = TestClient(client.app)
    ok = other.post("/api/auth/login", json={"username": "longpw", "password": long_pw})
    assert ok.status_code == 200, ok.text


def test_passwords_differing_only_after_72_bytes_treated_equal(client: TestClient) -> None:
    """与 bcrypt 一致：仅在 72 字节之后不同的密码视为同一密码。"""
    base = "a" * 72
    _register(client, username="trunc", password=base + "XXXX", display=None)
    other = TestClient(client.app)
    r = other.post("/api/auth/login", json={"username": "trunc", "password": base + "ZZZZ"})
    assert r.status_code == 200, r.text


def test_login_logout_flow(client: TestClient) -> None:
    _register(client, username="bob", password="abc12345")
    # 登出
    assert client.post("/api/auth/logout").status_code == 200
    # 登出后 /api/me 401
    assert client.get("/api/me").status_code == 401
    # 用错密码 → 401
    bad = client.post("/api/auth/login", json={"username": "bob", "password": "wrong"})
    assert bad.status_code == 401
    # 正确密码 → 200
    ok = client.post("/api/auth/login", json={"username": "bob", "password": "abc12345"})
    assert ok.status_code == 200
    assert ok.json()["username"] == "bob"
    # 登录后 /api/me 200
    assert client.get("/api/me").status_code == 200


def test_unknown_user_login_returns_401(client: TestClient) -> None:
    resp = client.post("/api/auth/login", json={"username": "ghost", "password": "whatever"})
    assert resp.status_code == 401


def test_me_unauthenticated_returns_401(client: TestClient) -> None:
    resp = client.get("/api/me")
    assert resp.status_code == 401


def test_password_hash_is_stored_not_plaintext(client: TestClient) -> None:
    """安全冒烟：DB 里不能直接存明文密码。"""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import User

    _register(client, username="dave", password="plaintext-should-not-be-stored")
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == "dave"))
        assert u is not None
        assert u.password_hash != "plaintext-should-not-be-stored"
        # bcrypt 哈希一律以 $2 开头
        assert u.password_hash.startswith("$2")


def test_init_admin_creates_admin(client: TestClient) -> None:
    """init_admin 脚本能正确建出 admin。"""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import ROLE_ADMIN, User
    from scripts.init_admin import main as init_admin_main

    rc = init_admin_main()
    assert rc == 0

    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.role == ROLE_ADMIN))
        assert u is not None
        assert u.role == ROLE_ADMIN


def test_init_admin_rejects_default_password_in_production(client: TestClient) -> None:
    """生产环境不能用默认 admin123456 自动创建管理员。

    关键：跳过创建但仍返回 0（启动链不被 && 截断、不崩溃循环）。
    """
    from sqlalchemy import select

    from app.config import settings
    from app.db import SessionLocal
    from app.models import ROLE_ADMIN, User
    from scripts.init_admin import main as init_admin_main

    old_env = settings.app_env
    old_password = settings.init_admin_password
    try:
        settings.app_env = "production"
        settings.init_admin_password = "admin123456"

        rc = init_admin_main()
        assert rc == 0  # 不阻断启动

        with SessionLocal() as db:
            # 但绝不能用默认密码建出管理员
            assert db.scalar(select(User).where(User.role == ROLE_ADMIN)) is None
    finally:
        settings.app_env = old_env
        settings.init_admin_password = old_password


def test_init_admin_keeps_existing_admin_even_with_default_password(
    client: TestClient,
) -> None:
    """已有 admin 时，即使 env 仍是默认密码，也不应被拦（你的线上场景）。"""
    from sqlalchemy import select

    from app.config import settings
    from app.db import SessionLocal
    from app.models import ROLE_ADMIN, User
    from app.security import hash_password
    from scripts.init_admin import main as init_admin_main

    old_env = settings.app_env
    old_password = settings.init_admin_password
    try:
        # 预置一个强密码 admin
        with SessionLocal() as db:
            db.add(
                User(
                    username=settings.init_admin_username.strip(),
                    password_hash=hash_password("a-strong-password"),
                    role=ROLE_ADMIN,
                    is_active=1,
                )
            )
            db.commit()

        settings.app_env = "production"
        settings.init_admin_password = "admin123456"
        assert init_admin_main() == 0

        with SessionLocal() as db:
            admins = db.scalars(select(User).where(User.role == ROLE_ADMIN)).all()
            assert len(admins) == 1  # 未新建、未改动
    finally:
        settings.app_env = old_env
        settings.init_admin_password = old_password


def test_role_guard_rejects_doctor(client: TestClient) -> None:
    """role 守卫工厂能拦住非允许角色。"""
    from fastapi import Depends

    from app.auth import require_role
    from app.main import app as fastapi_app
    from app.models import ROLE_ADMIN, User

    # 临时挂一个仅 admin 能访问的路由
    @fastapi_app.get("/api/_test_admin_only", include_in_schema=False)
    def _admin_only(u: User = Depends(require_role(ROLE_ADMIN))):
        return {"user": u.username}

    _register(client, username="eve", password="secret123")
    # eve 是 doctor，应该 403
    resp = client.get("/api/_test_admin_only")
    assert resp.status_code == 403


def test_health_still_ok(client: TestClient) -> None:
    """M0 端点别因为 M1 改动出问题。"""
    assert client.get("/api/health").status_code == 200


def test_create_app_rejects_default_secret_key_in_production() -> None:
    """生产环境若仍用默认占位 SECRET_KEY，create_app 必须拒绝启动。"""
    import pytest

    from app.config import DEFAULT_SECRET_KEY, settings
    from app.main import create_app

    old_env = settings.app_env
    old_key = settings.secret_key
    try:
        settings.app_env = "production"
        settings.secret_key = DEFAULT_SECRET_KEY
        assert settings.has_insecure_secret_key is True
        with pytest.raises(RuntimeError):
            create_app()
        # 设了强密钥后应当放行
        settings.secret_key = "a-strong-random-secret-key-32bytes+"
        assert settings.has_insecure_secret_key is False
        create_app()
    finally:
        settings.app_env = old_env
        settings.secret_key = old_key
