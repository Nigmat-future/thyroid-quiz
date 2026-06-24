"""M2 题库 CRUD + 上传测试。"""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import (
    ROLE_ADMIN,
    ROLE_AUTHOR,
    ROLE_DOCTOR,
    Answer,
    Attempt,
    Question,
    User,
)
from app.services.storage import store_local_image


def _png_bytes(seed: int = 0) -> bytes:
    """生成一张可识别的 PNG，每 seed 颜色不同避免 sha256 重复。"""
    img = Image.new("RGB", (32, 32), color=(seed % 255, (seed * 7) % 255, (seed * 13) % 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_user(client: TestClient, username: str, role: str = ROLE_DOCTOR) -> None:
    """注册并把角色按 role 提升（直接改 DB）。"""
    r = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123", "display_name": username},
    )
    assert r.status_code == 201
    if role != ROLE_DOCTOR:
        with SessionLocal() as db:
            u = db.scalar(select(User).where(User.username == username))
            u.role = role
            db.commit()


def _login(client: TestClient, username: str, password: str = "secret123") -> None:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _create_task(client: TestClient, code: str = "thy_bin", **overrides) -> dict:
    body = {
        "code": code,
        "name": "甲状腺二分类",
        "description": "测试题库",
        "answer_options": ["良性", "恶性"],
        "is_published": False,
        **overrides,
    }
    r = client.post("/api/tasks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- 任务 CRUD ----------

def test_doctor_cannot_create_task(client: TestClient) -> None:
    _make_user(client, "doc1", ROLE_DOCTOR)
    r = client.post("/api/tasks", json={
        "code": "x", "name": "y", "answer_options": ["A", "B"]
    })
    assert r.status_code == 403


def test_author_creates_task(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    task = _create_task(client)
    assert task["code"] == "thy_bin"
    assert task["answer_options"] == ["良性", "恶性"]
    assert task["n_questions"] == 0
    assert task["is_published"] is False


def test_task_code_unique(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="dup")
    r = client.post("/api/tasks", json={
        "code": "dup", "name": "x", "answer_options": ["a", "b"]
    })
    assert r.status_code == 409


def test_doctor_only_sees_published(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="draft1", is_published=False)
    _create_task(client, code="pub1", is_published=True)

    other = TestClient(client.app)
    _make_user(other, "doc2", ROLE_DOCTOR)
    _login(other, "doc2")
    r = other.get("/api/tasks")
    codes = {t["code"] for t in r.json()}
    assert codes == {"pub1"}

    # 直接 GET 草稿任务也 404
    assert other.get("/api/tasks/draft1").status_code == 404


def test_patch_options_blocks_used_answer(client: TestClient) -> None:
    """已被题目使用的标准答案不能从选项里删除。"""
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="t1")
    # 先传一张良性图
    files = [("files", ("a.png", _png_bytes(1), "image/png"))]
    r = client.post(
        "/api/tasks/t1/questions/upload",
        data={"ground_truths": json.dumps(["良性"])},
        files=files,
    )
    assert r.status_code == 201, r.text
    # 试图把"良性"踢出选项 → 400
    r = client.patch("/api/tasks/t1", json={"answer_options": ["恶性", "未知"]})
    assert r.status_code == 400


# ---------- 上传题目 ----------

def test_upload_questions_basic(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="t1", is_published=True)

    files = [
        ("files", ("a.png", _png_bytes(1), "image/png")),
        ("files", ("b.png", _png_bytes(2), "image/png")),
    ]
    r = client.post(
        "/api/tasks/t1/questions/upload",
        data={"ground_truths": json.dumps(["良性", "恶性"])},
        files=files,
    )
    assert r.status_code == 201, r.text
    qs = r.json()
    assert len(qs) == 2
    assert qs[0]["ground_truth"] == "良性"
    assert qs[1]["ground_truth"] == "恶性"
    assert qs[0]["order_index"] == 0
    assert qs[1]["order_index"] == 1
    assert qs[0]["image_sha256"] != qs[1]["image_sha256"]


def test_upload_questions_can_assign_batches(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="batch_upload", is_published=True)

    files = [
        ("files", ("a.png", _png_bytes(11), "image/png")),
        ("files", ("b.png", _png_bytes(12), "image/png")),
        ("files", ("c.png", _png_bytes(13), "image/png")),
    ]
    r = client.post(
        "/api/tasks/batch_upload/questions/upload",
        data={
            "ground_truths": json.dumps(["良性", "恶性", "良性"]),
            "batch_index_start": "3",
            "batch_size": "2",
        },
        files=files,
    )
    assert r.status_code == 201, r.text
    qs = r.json()
    assert [(q["batch_index"], q["batch_position"]) for q in qs] == [
        (3, 0),
        (3, 1),
        (4, 0),
    ]


def test_doctor_can_list_task_batches_with_attempt_status(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _create_task(author, code="batched", is_published=True)
    files = [
        ("files", ("a.png", _png_bytes(21), "image/png")),
        ("files", ("b.png", _png_bytes(22), "image/png")),
        ("files", ("c.png", _png_bytes(23), "image/png")),
    ]
    r = author.post(
        "/api/tasks/batched/questions/upload",
        data={"ground_truths": json.dumps(["良性", "恶性", "良性"])},
        files=files,
    )
    assert r.status_code == 201, r.text
    questions = r.json()
    with SessionLocal() as db:
        for idx, qid in enumerate(q["id"] for q in questions):
            question = db.get(Question, qid)
            question.batch_index = 0 if idx == 0 else 1
            question.batch_position = 0 if idx == 0 else idx - 1
        db.commit()

    doctor = TestClient(client.app)
    _make_user(doctor, "doc1", ROLE_DOCTOR)
    _login(doctor, "doc1")
    task = doctor.get("/api/tasks/batched").json()
    assert task["n_batches"] == 2

    r = doctor.get("/api/tasks/batched/batches")
    assert r.status_code == 200, r.text
    batches = r.json()
    assert [(b["batch_index"], b["total"], b["status"]) for b in batches] == [
        (0, 1, "not_started"),
        (1, 2, "not_started"),
    ]

    attempt = doctor.post("/api/attempts", json={"task_code": "batched", "batch_index": 1})
    assert attempt.status_code == 201, attempt.text
    r = doctor.get("/api/tasks/batched/batches")
    batches = r.json()
    assert batches[1]["status"] == "in_progress"
    assert batches[1]["attempt_id"] == attempt.json()["id"]


def test_upload_invalid_ground_truth_rejected(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="t1")

    files = [("files", ("a.png", _png_bytes(3), "image/png"))]
    r = client.post(
        "/api/tasks/t1/questions/upload",
        data={"ground_truths": json.dumps(["其他"])},
        files=files,
    )
    assert r.status_code == 400


def test_upload_dedups_same_image(client: TestClient) -> None:
    """两张相同图片应共用同一文件（sha256 相同）。"""
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="t1")
    same = _png_bytes(99)
    files = [
        ("files", ("a.png", same, "image/png")),
        ("files", ("b.png", same, "image/png")),
    ]
    r = client.post(
        "/api/tasks/t1/questions/upload",
        data={"ground_truths": json.dumps(["良性", "良性"])},
        files=files,
    )
    assert r.status_code == 201
    qs = r.json()
    assert qs[0]["image_sha256"] == qs[1]["image_sha256"]
    assert qs[0]["image_url"] == qs[1]["image_url"]


def test_upload_rejects_non_image(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="t1")
    files = [("files", ("a.txt", b"not an image", "text/plain"))]
    r = client.post(
        "/api/tasks/t1/questions/upload",
        data={"ground_truths": json.dumps(["良性"])},
        files=files,
    )
    assert r.status_code == 400


def test_question_patch_and_soft_delete(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="t1")
    files = [("files", ("a.png", _png_bytes(5), "image/png"))]
    r = client.post(
        "/api/tasks/t1/questions/upload",
        data={"ground_truths": json.dumps(["良性"])},
        files=files,
    )
    qid = r.json()[0]["id"]

    # 改答案
    r = client.patch(f"/api/questions/{qid}", json={"ground_truth": "恶性", "note": "复测"})
    assert r.status_code == 200
    assert r.json()["ground_truth"] == "恶性"
    assert r.json()["note"] == "复测"

    # 软删
    r = client.delete(f"/api/questions/{qid}")
    assert r.status_code == 204
    # 再 patch → 404
    assert client.patch(f"/api/questions/{qid}", json={"note": "x"}).status_code == 404
    # 列表不再包含
    r = client.get("/api/tasks/t1/questions")
    assert all(q["id"] != qid for q in r.json())


# ---------- 跨人权限 ----------

def test_author_cannot_manage_others_task(client: TestClient) -> None:
    _make_user(client, "alice", ROLE_AUTHOR)
    _login(client, "alice")
    _create_task(client, code="alice_task")

    other = TestClient(client.app)
    _make_user(other, "bob", ROLE_AUTHOR)
    _login(other, "bob")
    r = other.get("/api/tasks/alice_task/admin")
    assert r.status_code == 403
    r = other.patch("/api/tasks/alice_task", json={"name": "hacked"})
    assert r.status_code == 403


def test_admin_can_manage_anything(client: TestClient) -> None:
    _make_user(client, "alice", ROLE_AUTHOR)
    _login(client, "alice")
    _create_task(client, code="alice_task")

    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    r = admin.get("/api/tasks/alice_task/admin")
    assert r.status_code == 200
    r = admin.patch("/api/tasks/alice_task", json={"name": "renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"


def test_admin_can_delete_task_cascades(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="t1")
    files = [("files", ("a.png", _png_bytes(7), "image/png"))]
    client.post(
        "/api/tasks/t1/questions/upload",
        data={"ground_truths": json.dumps(["良性"])},
        files=files,
    )
    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    r = admin.delete("/api/tasks/t1")
    assert r.status_code == 204
    # 其他人 author 删除应 403
    other = TestClient(client.app)
    _make_user(other, "auth2", ROLE_AUTHOR)
    _login(other, "auth2")
    _create_task(other, code="t2")
    r = other.delete("/api/tasks/t2")
    assert r.status_code == 403


# ---------- 鉴权图片下发 ----------

def test_storage_requires_auth(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    _create_task(client, code="t1")
    files = [("files", ("a.png", _png_bytes(11), "image/png"))]
    r = client.post(
        "/api/tasks/t1/questions/upload",
        data={"ground_truths": json.dumps(["良性"])},
        files=files,
    )
    image_url = r.json()[0]["image_url"]

    # 登录用户能下载
    r = client.get(image_url)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("image/")

    # 未登录用户被拦
    anon = TestClient(client.app)
    r = anon.get(image_url)
    assert r.status_code == 401


def test_storage_path_traversal_blocked(client: TestClient) -> None:
    _make_user(client, "auth1", ROLE_AUTHOR)
    _login(client, "auth1")
    r = client.get("/storage/../etc/passwd")
    assert r.status_code in (400, 404)


def test_store_local_image_overwrites_truncated_existing_file(tmp_path) -> None:
    source = tmp_path / "source.png"
    raw = _png_bytes(42)
    source.write_bytes(raw)

    rel_path, _ = store_local_image(source)
    target = settings.storage_dir / rel_path
    target.write_bytes(b"")

    rel_path_again, _ = store_local_image(source)

    assert rel_path_again == rel_path
    assert target.read_bytes() == raw


def test_delete_task_with_attempts_cleans_up(client: TestClient) -> None:
    """删除有答题记录的任务：不应 500，且 attempts/answers 一并清理。

    回归：之前只 db.delete(task)，attempts 会变孤儿或触发外键冲突。
    """
    _make_user(client, "admin1", ROLE_ADMIN)
    _login(client, "admin1")
    _create_task(client, code="delme", is_published=True)
    r = client.post(
        "/api/tasks/delme/questions/upload",
        data={"ground_truths": json.dumps(["良性"])},
        files=[("files", ("q0.png", _png_bytes(1), "image/png"))],
    )
    assert r.status_code == 201, r.text
    qid = r.json()[0]["id"]

    doctor = TestClient(client.app)
    _make_user(doctor, "doc1", ROLE_DOCTOR)
    _login(doctor, "doc1")
    a = doctor.post("/api/attempts", json={"task_code": "delme"}).json()
    doctor.put(f"/api/attempts/{a['id']}/answers/{qid}", json={"answer_text": "良性"})
    assert doctor.post(f"/api/attempts/{a['id']}/submit").status_code == 200

    d = client.delete("/api/tasks/delme")
    assert d.status_code == 204, d.text

    with SessionLocal() as db:
        assert db.scalar(select(func.count(Attempt.id))) == 0
        assert db.scalar(select(func.count(Answer.id))) == 0
        assert db.scalar(select(func.count(Question.id))) == 0
