"""Admin user-level metrics tests."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ROLE_ADMIN, ROLE_AUTHOR, ROLE_DOCTOR, User
from app.services.fna import FNA_ANSWER_OPTIONS


def _png(seed: int) -> bytes:
    image = Image.new(
        "RGB",
        (16, 16),
        color=(seed % 255, (seed * 5) % 255, (seed * 11) % 255),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


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
    response = client.post(
        "/api/auth/login", json={"username": username, "password": "secret123"}
    )
    assert response.status_code == 200, response.text


def _create_fna_task(author: TestClient) -> None:
    response = author.post(
        "/api/tasks",
        json={
            "code": "fna_binary_5class",
            "name": "FNA",
            "answer_options": FNA_ANSWER_OPTIONS,
            "is_published": True,
        },
    )
    assert response.status_code == 201, response.text


def _upload_batch(
    author: TestClient,
    truths: list[str],
    seed_offset: int,
    batch_index_start: int,
) -> None:
    response = author.post(
        "/api/tasks/fna_binary_5class/questions/upload",
        data={
            "ground_truths": json.dumps(truths),
            "batch_index_start": str(batch_index_start),
        },
        files=[
            ("files", (f"q{seed_offset + idx}.png", _png(seed_offset + idx), "image/png"))
            for idx, _truth in enumerate(truths)
        ],
    )
    assert response.status_code == 201, response.text


def _submit_attempt(
    doctor: TestClient,
    batch_index: int,
    answers: list[str],
) -> None:
    attempt = doctor.post(
        "/api/attempts",
        json={"task_code": "fna_binary_5class", "batch_index": batch_index},
    ).json()
    for question, answer_text in zip(attempt["questions"], answers, strict=True):
        response = doctor.put(
            f"/api/attempts/{attempt['id']}/answers/{question['id']}",
            json={"answer_text": answer_text},
        )
        assert response.status_code == 200, response.text
    response = doctor.post(f"/api/attempts/{attempt['id']}/submit")
    assert response.status_code == 200, response.text


def test_admin_users_include_overall_auc_per_user(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "author1", ROLE_AUTHOR)
    _login(author, "author1")
    _create_fna_task(author)
    _upload_batch(author, ["确定不是癌", "确定不是癌", "确定是癌", "确定是癌"], 1, 0)
    _upload_batch(author, ["确定不是癌", "确定是癌"], 10, 1)

    doctor = TestClient(client.app)
    _make_user(doctor, "doctor1")
    _login(doctor, "doctor1")
    _submit_attempt(doctor, 0, ["倾向不是癌", "确定不是癌", "倾向是癌", "不确定"])
    _submit_attempt(doctor, 1, ["不确定", "确定是癌"])

    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")

    response = admin.get("/api/admin/users")
    assert response.status_code == 200, response.text
    users = {user["username"]: user for user in response.json()}

    doctor_metrics = users["doctor1"]
    assert doctor_metrics["submitted_attempts"] == 2
    assert doctor_metrics["total"] == 6
    assert doctor_metrics["answered"] == 6
    assert doctor_metrics["correct"] == 4
    assert doctor_metrics["accuracy"] == 4 / 6
    assert doctor_metrics["auc"] == 17 / 18
    assert doctor_metrics["auc_positive"] == 3
    assert doctor_metrics["auc_negative"] == 3

    admin_metrics = users["root"]
    assert admin_metrics["submitted_attempts"] == 0
    assert admin_metrics["total"] == 0
    assert admin_metrics["accuracy"] is None
    assert admin_metrics["auc"] is None
