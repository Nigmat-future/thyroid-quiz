"""M5 admin 后台测试。"""

from __future__ import annotations

import csv
import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ROLE_ADMIN, ROLE_AUTHOR, ROLE_DOCTOR, User
from tests.conftest import register_user


def _png(seed: int) -> bytes:
    img = Image.new(
        "RGB", (16, 16), color=(seed % 255, (seed * 5) % 255, (seed * 11) % 255)
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_user(client: TestClient, username: str, role: str = ROLE_DOCTOR) -> int:
    r = register_user(client, username, display_name=username)
    assert r.status_code == 201
    if role != ROLE_DOCTOR:
        with SessionLocal() as db:
            u = db.scalar(select(User).where(User.username == username))
            u.role = role
            db.commit()
            return u.id
    return r.json()["id"]


def _login(client: TestClient, username: str, password: str = "secret123") -> None:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _seed_attempt(author: TestClient, doctor: TestClient, task_code: str = "tt") -> int:
    """快速制造 1 个已提交 attempt，返回 attempt_id。"""
    author.post("/api/tasks", json={
        "code": task_code, "name": "T", "answer_options": ["良性", "恶性"], "is_published": True
    })
    files = [
        ("files", ("a.png", _png(1), "image/png")),
        ("files", ("b.png", _png(2), "image/png")),
    ]
    author.post(f"/api/tasks/{task_code}/questions/upload",
                data={"ground_truths": json.dumps(["良性", "恶性"])}, files=files)
    a = doctor.post("/api/attempts", json={"task_code": task_code}).json()
    qs = a["questions"]
    doctor.put(
        f"/api/attempts/{a['id']}/answers/{qs[0]['id']}",
        json={"answer_text": "良性", "review_flag": True, "time_spent_seconds": 12},
    )
    doctor.put(f"/api/attempts/{a['id']}/answers/{qs[1]['id']}", json={"answer_text": "良性"})  # 错
    doctor.post(f"/api/attempts/{a['id']}/submit")
    return a["id"]


def test_doctor_cannot_access_admin(client: TestClient) -> None:
    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    assert client.get("/api/admin/users").status_code == 403


def test_author_cannot_access_admin(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    assert client.get("/api/admin/users").status_code == 403


def test_admin_can_list_users(client: TestClient) -> None:
    _make_user(client, "doc1", ROLE_DOCTOR)
    other = TestClient(client.app)
    _make_user(other, "root", ROLE_ADMIN)
    _login(other, "root")
    r = other.get("/api/admin/users")
    assert r.status_code == 200
    usernames = {u["username"] for u in r.json()}
    assert {"doc1", "root"}.issubset(usernames)


def test_admin_can_promote_user(client: TestClient) -> None:
    _make_user(client, "doc1", ROLE_DOCTOR)
    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    # 找 doc1 的 id
    users = admin.get("/api/admin/users").json()
    doc1_id = next(u["id"] for u in users if u["username"] == "doc1")

    r = admin.patch(f"/api/admin/users/{doc1_id}", json={"role": "author"})
    assert r.status_code == 200
    assert r.json()["role"] == "author"


def test_admin_cannot_self_demote(client: TestClient) -> None:
    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    me = admin.get("/api/me").json()
    r = admin.patch(f"/api/admin/users/{me['id']}", json={"role": "doctor"})
    assert r.status_code == 400
    r = admin.patch(f"/api/admin/users/{me['id']}", json={"is_active": 0})
    assert r.status_code == 400


def test_admin_can_reset_password(client: TestClient) -> None:
    _make_user(client, "doc1", ROLE_DOCTOR)
    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    users = admin.get("/api/admin/users").json()
    doc1_id = next(u["id"] for u in users if u["username"] == "doc1")
    r = admin.patch(f"/api/admin/users/{doc1_id}", json={"new_password": "newsecret"})
    assert r.status_code == 200

    # 用旧密码登录失败
    fresh = TestClient(client.app)
    r = fresh.post("/api/auth/login", json={"username": "doc1", "password": "secret123"})
    assert r.status_code == 401
    # 用新密码登录成功
    r = fresh.post("/api/auth/login", json={"username": "doc1", "password": "newsecret"})
    assert r.status_code == 200


def test_admin_attempts_list_and_filter(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    doctor = TestClient(client.app)
    _make_user(doctor, "doc1", ROLE_DOCTOR)
    _login(doctor, "doc1")
    aid = _seed_attempt(author, doctor, task_code="tt")

    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    r = admin.get("/api/admin/attempts")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == aid
    assert items[0]["username"] == "doc1"
    assert items[0]["task_code"] == "tt"

    # 过滤 status=submitted 命中
    r = admin.get("/api/admin/attempts?status=submitted")
    assert len(r.json()) == 1
    # 过滤 status=in_progress 不命中
    r = admin.get("/api/admin/attempts?status=in_progress")
    assert len(r.json()) == 0
    # 过滤错误任务码 → 空
    r = admin.get("/api/admin/attempts?task_code=nope")
    assert len(r.json()) == 0


def test_admin_attempt_detail(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    doctor = TestClient(client.app)
    _make_user(doctor, "doc1", ROLE_DOCTOR)
    _login(doctor, "doc1")
    aid = _seed_attempt(author, doctor)
    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")

    r = admin.get(f"/api/admin/attempts/{aid}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["id"] == aid
    assert d["user"]["username"] == "doc1"
    assert d["status"] == "submitted"
    assert len(d["rows"]) == 2
    assert all("ground_truth" in r and "is_correct" in r for r in d["rows"])
    assert d["batch_index"] == 0
    assert d["rows"][0]["batch_index"] == 0
    assert d["rows"][0]["batch_position"] == 0
    assert d["rows"][0]["review_flag"] is True
    assert d["rows"][0]["time_spent_seconds"] == 12
    # 第 1 题对，第 2 题错
    assert d["rows"][0]["is_correct"] is True
    assert d["rows"][1]["is_correct"] is False


def test_csv_attempts_export(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    doctor = TestClient(client.app)
    _make_user(doctor, "doc1", ROLE_DOCTOR)
    _login(doctor, "doc1")
    _seed_attempt(author, doctor, task_code="tt")

    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    r = admin.get("/api/admin/exports/attempts.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    body = r.content.decode("utf-8-sig")
    lines = [line for line in body.splitlines() if line]
    assert lines[0].startswith("attempt_id,user_id,username")
    # 数据行包含 doc1 + tt
    assert any("doc1" in line and "tt" in line for line in lines[1:])


def test_csv_answers_export(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    doctor = TestClient(client.app)
    _make_user(doctor, "doc1", ROLE_DOCTOR)
    _login(doctor, "doc1")
    _seed_attempt(author, doctor, task_code="tt")

    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    r = admin.get("/api/admin/exports/answers.csv")
    assert r.status_code == 200
    body = r.content.decode("utf-8-sig")
    lines = [line for line in body.splitlines() if line]
    assert lines[0].startswith("attempt_id,username,display_name")
    rows = list(csv.DictReader(io.StringIO(body)))
    assert {
        "batch_index",
        "batch_position",
        "review_flag",
        "time_spent_seconds",
    }.issubset(rows[0].keys())
    assert any(
        row["answer_text"] == "良性"
        and row["review_flag"] == "1"
        and row["time_spent_seconds"] == "12"
        for row in rows
    )
    # 应该有 2 条答题记录
    data_lines = [line for line in lines[1:] if "良性" in line or "恶性" in line]
    assert len(data_lines) == 2
