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
