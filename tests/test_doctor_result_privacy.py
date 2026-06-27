"""Doctor-facing result privacy tests."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ROLE_AUTHOR, ROLE_DOCTOR, User
from tests.conftest import register_user


def _png(seed: int) -> bytes:
    img = Image.new("RGB", (16, 16), color=(seed % 255, (seed * 7) % 255, (seed * 13) % 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_user(client: TestClient, username: str, role: str = ROLE_DOCTOR) -> int:
    response = register_user(client, username, display_name=username)
    assert response.status_code == 201, response.text
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


def _seed_task(client: TestClient, code: str, gts: list[str]) -> None:
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
    files = [("files", (f"q{i}.png", _png(200 + i), "image/png")) for i in range(len(gts))]
    response = client.post(
        f"/api/tasks/{code}/questions/upload",
        data={"ground_truths": json.dumps(gts)},
        files=files,
    )
    assert response.status_code == 201, response.text


def _create_attempt_with_answers(client: TestClient, task_code: str, answers: list[str]) -> dict:
    attempt = client.post("/api/attempts", json={"task_code": task_code}).json()
    for question, answer in zip(attempt["questions"], answers, strict=True):
        response = client.put(
            f"/api/attempts/{attempt['id']}/answers/{question['id']}",
            json={"answer_text": answer},
        )
        assert response.status_code == 200, response.text
    return attempt


def _assert_no_correctness_fields(payload: dict) -> None:
    assert "score" not in payload
    assert "correct" not in payload
    for row in payload["rows"]:
        assert "ground_truth" not in row
        assert "is_correct" not in row


def test_doctor_submit_and_result_only_show_completion(client: TestClient) -> None:
    # Given: a submitted attempt with one correct and one incorrect answer.
    author = TestClient(client.app)
    _make_user(author, "privacy_author", ROLE_AUTHOR)
    _login(author, "privacy_author")
    _seed_task(author, "privacy", ["良性", "恶性"])
    _make_user(client, "privacy_doc")
    _login(client, "privacy_doc")
    attempt = _create_attempt_with_answers(client, "privacy", ["良性", "良性"])

    # When: the doctor submits and later opens the result endpoint.
    submit_response = client.post(f"/api/attempts/{attempt['id']}/submit")
    result_response = client.get(f"/api/attempts/{attempt['id']}/result")

    # Then: both responses expose completion only, never correctness.
    assert submit_response.status_code == 200, submit_response.text
    assert result_response.status_code == 200, result_response.text
    for payload in (submit_response.json(), result_response.json()):
        assert payload["status"] == "submitted"
        assert payload["answered"] == 2
        assert payload["total"] == 2
        _assert_no_correctness_fields(payload)


def test_doctor_history_only_shows_completion(client: TestClient) -> None:
    # Given: one submitted attempt and one in-progress attempt.
    author = TestClient(client.app)
    _make_user(author, "history_author", ROLE_AUTHOR)
    _login(author, "history_author")
    _seed_task(author, "history_done", ["良性", "恶性"])
    _seed_task(author, "history_open", ["良性", "恶性"])
    _make_user(client, "history_doc")
    _login(client, "history_doc")
    submitted = _create_attempt_with_answers(client, "history_done", ["良性", "恶性"])
    in_progress = _create_attempt_with_answers(client, "history_open", ["恶性", ""])
    submit_response = client.post(f"/api/attempts/{submitted['id']}/submit")
    assert submit_response.status_code == 200, submit_response.text

    # When: the doctor opens their own attempt history.
    response = client.get("/api/attempts")

    # Then: history contains completion counts without score or correct count.
    assert response.status_code == 200, response.text
    rows = {item["id"]: item for item in response.json()}
    assert rows[submitted["id"]]["status"] == "submitted"
    assert rows[submitted["id"]]["answered"] == 2
    assert rows[submitted["id"]]["total"] == 2
    assert rows[in_progress["id"]]["status"] == "in_progress"
    assert rows[in_progress["id"]]["answered"] == 1
    assert rows[in_progress["id"]]["total"] == 2
    for item in rows.values():
        assert "score" not in item
        assert "correct" not in item
