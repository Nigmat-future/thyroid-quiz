"""Attempt submission, result, and history tests."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ROLE_AUTHOR, ROLE_DOCTOR, Attempt, User


def _png(seed: int) -> bytes:
    img = Image.new(
        "RGB",
        (32, 32),
        color=(seed % 255, (seed * 7) % 255, (seed * 13) % 255),
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_user(client: TestClient, username: str, role: str = ROLE_DOCTOR) -> int:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123", "display_name": username},
    )
    assert response.status_code == 201
    if role == ROLE_DOCTOR:
        return int(response.json()["id"])

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        assert user is not None
        user.role = role
        db.commit()
        return user.id


def _login(client: TestClient, username: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": "secret123"})
    assert response.status_code == 200, response.text


def _seed_task(
    client: TestClient,
    code: str = "thy",
    n_q: int = 3,
    gts: list[str] | None = None,
) -> None:
    gts = gts or ["良性", "恶性", "良性"][:n_q]
    response = client.post(
        "/api/tasks",
        json={
            "code": code,
            "name": f"任务 {code}",
            "answer_options": ["良性", "恶性"],
            "is_published": True,
        },
    )
    assert response.status_code == 201, response.text
    files = [("files", (f"q{i}.png", _png(100 + i), "image/png")) for i in range(n_q)]
    response = client.post(
        f"/api/tasks/{code}/questions/upload",
        data={"ground_truths": json.dumps(gts)},
        files=files,
    )
    assert response.status_code == 201, response.text


def test_submit_calculates_score(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=4, gts=["良性", "恶性", "良性", "恶性"])

    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    attempt = client.post("/api/attempts", json={"task_code": "t1"}).json()
    questions = attempt["questions"]

    answers = ["良性", "恶性", "恶性", ""]
    for question, answer in zip(questions, answers, strict=True):
        client.put(
            f"/api/attempts/{attempt['id']}/answers/{question['id']}",
            json={"answer_text": answer},
        )

    response = client.post(f"/api/attempts/{attempt['id']}/submit")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "submitted"
    assert result["total"] == 4
    assert result["answered"] == 3
    assert "correct" not in result
    assert "score" not in result
    with SessionLocal() as db:
        saved = db.get(Attempt, attempt["id"])
        assert saved is not None
        assert saved.correct == 2
        assert abs(saved.score - 0.5) < 1e-6


def test_submit_locks_attempt(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=1)
    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    attempt = client.post("/api/attempts", json={"task_code": "t1"}).json()
    question_id = attempt["questions"][0]["id"]
    client.put(
        f"/api/attempts/{attempt['id']}/answers/{question_id}",
        json={"answer_text": "良性"},
    )
    client.post(f"/api/attempts/{attempt['id']}/submit")

    assert client.get(f"/api/attempts/{attempt['id']}").status_code == 409
    response = client.put(
        f"/api/attempts/{attempt['id']}/answers/{question_id}",
        json={"answer_text": "恶性"},
    )
    assert response.status_code == 409
    response = client.post(f"/api/attempts/{attempt['id']}/submit")
    assert response.status_code == 200


def test_result_view_hides_ground_truth_and_correctness(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=2, gts=["良性", "恶性"])
    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    attempt = client.post("/api/attempts", json={"task_code": "t1"}).json()
    questions = attempt["questions"]
    client.put(
        f"/api/attempts/{attempt['id']}/answers/{questions[0]['id']}",
        json={"answer_text": "良性"},
    )
    client.put(
        f"/api/attempts/{attempt['id']}/answers/{questions[1]['id']}",
        json={"answer_text": "良性"},
    )
    client.post(f"/api/attempts/{attempt['id']}/submit")

    response = client.get(f"/api/attempts/{attempt['id']}/result")
    assert response.status_code == 200
    result = response.json()
    assert result["answered"] == 2
    assert result["total"] == 2
    assert all("ground_truth" not in row for row in result["rows"])
    assert all("is_correct" not in row for row in result["rows"])
    assert [row["answer_text"] for row in result["rows"]] == ["良性", "良性"]


def test_result_unauthorized_until_submit(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=1)
    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    attempt = client.post("/api/attempts", json={"task_code": "t1"}).json()
    response = client.get(f"/api/attempts/{attempt['id']}/result")
    assert response.status_code == 409


def test_my_attempts_history(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "auth1", ROLE_AUTHOR)
    _login(author, "auth1")
    _seed_task(author, code="t1", n_q=1)
    _make_user(client, "doc1", ROLE_DOCTOR)
    _login(client, "doc1")
    attempt = client.post("/api/attempts", json={"task_code": "t1"}).json()
    question_id = attempt["questions"][0]["id"]
    client.put(
        f"/api/attempts/{attempt['id']}/answers/{question_id}",
        json={"answer_text": "良性"},
    )
    client.post(f"/api/attempts/{attempt['id']}/submit")

    response = client.get("/api/attempts")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["status"] == "submitted"
    assert items[0]["task_code"] == "t1"
    assert items[0]["answered"] == 1
    assert items[0]["total"] == 1
    assert "score" not in items[0]
    assert "correct" not in items[0]
