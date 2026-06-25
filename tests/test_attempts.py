"""M3 答题流程 + M4 提交计分 测试。"""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ROLE_AUTHOR, ROLE_DOCTOR, Question, User
from app.services.fna import FNA_ANSWER_OPTIONS
from tests.conftest import register_user


def _png(seed: int) -> bytes:
    img = Image.new("RGB", (32, 32), color=(seed % 255, (seed * 7) % 255, (seed * 13) % 255))
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


def _login(client: TestClient, username: str) -> None:
    r = client.post("/api/auth/login", json={"username": username, "password": "secret123"})
    assert r.status_code == 200, r.text


def _seed_task(
    client: TestClient,
    code: str = "thy",
    n_q: int = 3,
    opts: list[str] | None = None,
    gts: list[str] | None = None,
    published: bool = True,
) -> dict:
    """返回 (admin) task dict。"""
    opts = opts or ["良性", "恶性"]
    gts = gts or ["良性", "恶性", "良性"][:n_q]
    r = client.post(
        "/api/tasks",
        json={
            "code": code,
            "name": f"任务 {code}",
            "answer_options": opts,
            "is_published": published,
        },
    )
    assert r.status_code == 201, r.text
    files = [("files", (f"q{i}.png", _png(100 + i), "image/png")) for i in range(n_q)]
    r = client.post(
        f"/api/tasks/{code}/questions/upload",
        data={"ground_truths": json.dumps(gts)},
        files=files,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------- attempt 创建 / 续答 ----------


def test_doctor_starts_attempt_and_can_resume(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=3)

    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")

    r = client.post("/api/attempts", json={"task_code": "t1"})
    assert r.status_code == 201, r.text
    a1 = r.json()
    assert a1["status"] == "in_progress"
    assert len(a1["questions"]) == 3
    # 题目暴露的字段不能含 ground_truth
    for q in a1["questions"]:
        assert "ground_truth" not in q

    # 再次 POST 应返回同一个 attempt（续答）
    r2 = client.post("/api/attempts", json={"task_code": "t1"})
    assert r2.status_code == 201
    assert r2.json()["id"] == a1["id"]


def test_doctor_cannot_attempt_unpublished(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="draft1", n_q=1, published=False)

    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    r = client.post("/api/attempts", json={"task_code": "draft1"})
    assert r.status_code == 404


# ---------- 保存答案 ----------


def test_save_answer_round_trip(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=2)

    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    r = client.post("/api/attempts", json={"task_code": "t1"})
    a = r.json()
    qid = a["questions"][0]["id"]

    r = client.put(
        f"/api/attempts/{a['id']}/answers/{qid}",
        json={
            "answer_text": "良性",
            "note": "我的备注",
            "review_flag": True,
            "time_spent_seconds": 7,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["answer_text"] == "良性"
    assert r.json()["note"] == "我的备注"
    assert r.json()["review_flag"] is True
    assert r.json()["time_spent_seconds"] == 7

    r = client.put(
        f"/api/attempts/{a['id']}/answers/{qid}",
        json={
            "answer_text": "良性",
            "note": "复核后保留",
            "review_flag": False,
            "time_spent_seconds": 3,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["review_flag"] is False
    assert r.json()["time_spent_seconds"] == 7

    # 刷新 attempt 应包含此答案
    r = client.get(f"/api/attempts/{a['id']}")
    saved = r.json()["answers"]
    assert any(
        s["question_id"] == qid
        and s["answer_text"] == "良性"
        and s["review_flag"] is False
        and s["time_spent_seconds"] == 7
        for s in saved
    )


def test_doctor_starts_specific_batch_and_only_gets_batch_questions(
    client: TestClient,
) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    created = _seed_task(
        author,
        code="batched",
        n_q=4,
        gts=["良性", "恶性", "良性", "恶性"],
    )
    with SessionLocal() as db:
        for idx, qid in enumerate(q["id"] for q in created):
            question = db.get(Question, qid)
            question.batch_index = idx // 2
            question.batch_position = idx % 2
        db.commit()

    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    r = client.post("/api/attempts", json={"task_code": "batched", "batch_index": 1})
    assert r.status_code == 201, r.text
    attempt = r.json()
    qs = attempt["questions"]
    assert attempt["batch_index"] == 1
    assert attempt["batch_total"] == 2
    assert len(qs) == 2
    assert [q["batch_index"] for q in qs] == [1, 1]
    assert [q["batch_position"] for q in qs] == [0, 1]

    r = client.put(
        f"/api/attempts/{attempt['id']}/answers/{created[0]['id']}",
        json={"answer_text": "良性"},
    )
    assert r.status_code == 404

    client.put(
        f"/api/attempts/{attempt['id']}/answers/{qs[0]['id']}",
        json={"answer_text": "良性"},
    )
    client.put(
        f"/api/attempts/{attempt['id']}/answers/{qs[1]['id']}",
        json={"answer_text": "恶性"},
    )
    result = client.post(f"/api/attempts/{attempt['id']}/submit").json()
    assert result["batch_index"] == 1
    assert result["total"] == 2
    assert [row["batch_position"] for row in result["rows"]] == [0, 1]


def test_save_invalid_option_rejected(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=1)
    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    r = client.post("/api/attempts", json={"task_code": "t1"})
    a = r.json()
    qid = a["questions"][0]["id"]
    r = client.put(
        f"/api/attempts/{a['id']}/answers/{qid}",
        json={"answer_text": "其他选项"},
    )
    assert r.status_code == 400


def test_save_five_class_auc_answer(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(
        author,
        code="fna5",
        n_q=1,
        opts=FNA_ANSWER_OPTIONS,
        gts=["确定是癌"],
    )
    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    a = client.post("/api/attempts", json={"task_code": "fna5"}).json()
    qid = a["questions"][0]["id"]

    r = client.put(
        f"/api/attempts/{a['id']}/answers/{qid}",
        json={"answer_text": "倾向是癌"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["answer_text"] == "倾向是癌"


def test_other_user_cannot_access_attempt(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=1)

    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    a = client.post("/api/attempts", json={"task_code": "t1"}).json()

    other = TestClient(client.app)
    _make_user(other, "doc2", ROLE_DOCTOR)
    _login(other, "doc2")
    r = other.get(f"/api/attempts/{a['id']}")
    assert r.status_code == 403
