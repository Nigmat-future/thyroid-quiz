"""Admin attempt metrics tests."""

from __future__ import annotations

import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ROLE_ADMIN, ROLE_AUTHOR, ROLE_DOCTOR, User
from app.services.fna import FNA_ANSWER_OPTIONS, build_source_note
from tests.conftest import register_user


def _png(seed: int) -> bytes:
    img = Image.new(
        "RGB", (16, 16), color=(seed % 255, (seed * 5) % 255, (seed * 11) % 255)
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_user(client: TestClient, username: str, role: str = ROLE_DOCTOR) -> int:
    response = register_user(client, username, display_name=username)
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


def test_admin_attempts_include_auc_and_detail_metrics(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "author1", ROLE_AUTHOR)
    _login(author, "author1")
    task_response = author.post(
        "/api/tasks",
        json={
            "code": "fna_binary_5class",
            "name": "FNA",
            "answer_options": FNA_ANSWER_OPTIONS,
            "is_published": True,
        },
    )
    assert task_response.status_code == 201, task_response.text
    upload_response = author.post(
        "/api/tasks/fna_binary_5class/questions/upload",
        data={
            "ground_truths": json.dumps(
                ["确定不是癌", "确定不是癌", "确定是癌", "确定是癌"]
            ),
            "notes": json.dumps(
                [
                    build_source_note("重庆", "重庆test/benign/a.png"),
                    build_source_note("重庆", "重庆test/benign/b.png"),
                    build_source_note("福建", "福建test/malignant/c.png"),
                    build_source_note("福建", "福建test/malignant/d.png"),
                ]
            ),
        },
        files=[
            ("files", ("a.png", _png(1), "image/png")),
            ("files", ("b.png", _png(2), "image/png")),
            ("files", ("c.png", _png(3), "image/png")),
            ("files", ("d.png", _png(4), "image/png")),
        ],
    )
    assert upload_response.status_code == 201, upload_response.text

    doctor = TestClient(client.app)
    _make_user(doctor, "doctor1")
    _login(doctor, "doctor1")
    attempt = doctor.post("/api/attempts", json={"task_code": "fna_binary_5class"}).json()
    answers = ["确定不是癌", "倾向不是癌", "倾向是癌", "确定是癌"]
    for question, answer in zip(attempt["questions"], answers, strict=True):
        response = doctor.put(
            f"/api/attempts/{attempt['id']}/answers/{question['id']}",
            json={"answer_text": answer},
        )
        assert response.status_code == 200, response.text
    submit_response = doctor.post(f"/api/attempts/{attempt['id']}/submit")
    assert submit_response.status_code == 200, submit_response.text

    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")

    list_response = admin.get("/api/admin/attempts")
    assert list_response.status_code == 200, list_response.text
    summary = list_response.json()[0]
    assert summary["correct"] == 4
    assert summary["total"] == 4
    assert summary["score"] == 1.0
    assert summary["auc"] == 1.0

    detail_response = admin.get(f"/api/admin/attempts/{attempt['id']}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()
    assert detail["metrics"] == {
        "total": 4,
        "answered": 4,
        "correct": 4,
        "accuracy": 1.0,
        "auc": 1.0,
        "auc_positive": 2,
        "auc_negative": 2,
        "uncertain": 0,
        "ppv": 1.0,
        "npv": 1.0,
        "sensitivity": 1.0,
        "specificity": 1.0,
    }
    assert len(detail["rows"]) == 4
    assert {row["truth_binary"] for row in detail["rows"]} == {0, 1}
    assert {row["doctor_malignancy_score"] for row in detail["rows"]} == {
        0.0,
        0.3,
        0.7,
        1.0,
    }
    assert {row["source_center"] for row in detail["rows"]} == {"重庆", "福建"}


def test_admin_attempt_user_summaries_follow_filters(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "author2", ROLE_AUTHOR)
    _login(author, "author2")
    task_response = author.post(
        "/api/tasks",
        json={
            "code": "fna_binary_5class",
            "name": "FNA",
            "answer_options": FNA_ANSWER_OPTIONS,
            "is_published": True,
        },
    )
    assert task_response.status_code == 201, task_response.text
    upload_response = author.post(
        "/api/tasks/fna_binary_5class/questions/upload",
        data={
            "ground_truths": json.dumps(
                ["确定不是癌", "确定不是癌", "确定是癌", "确定是癌"]
            ),
        },
        files=[
            ("files", ("a.png", _png(31), "image/png")),
            ("files", ("b.png", _png(32), "image/png")),
            ("files", ("c.png", _png(33), "image/png")),
            ("files", ("d.png", _png(34), "image/png")),
        ],
    )
    assert upload_response.status_code == 201, upload_response.text

    doctor_one = TestClient(client.app)
    doctor_one_id = _make_user(doctor_one, "doctor_a")
    _login(doctor_one, "doctor_a")
    first_attempt = doctor_one.post(
        "/api/attempts", json={"task_code": "fna_binary_5class"}
    ).json()
    first_answers = ["确定不是癌", "不确定", "倾向是癌", "确定是癌"]
    for question, answer in zip(first_attempt["questions"], first_answers, strict=True):
        response = doctor_one.put(
            f"/api/attempts/{first_attempt['id']}/answers/{question['id']}",
            json={"answer_text": answer},
        )
        assert response.status_code == 200, response.text
    submit_response = doctor_one.post(f"/api/attempts/{first_attempt['id']}/submit")
    assert submit_response.status_code == 200, submit_response.text

    in_progress_attempt = doctor_one.post(
        "/api/attempts", json={"task_code": "fna_binary_5class"}
    ).json()
    response = doctor_one.put(
        f"/api/attempts/{in_progress_attempt['id']}/answers/{in_progress_attempt['questions'][0]['id']}",
        json={"answer_text": "确定不是癌"},
    )
    assert response.status_code == 200, response.text

    doctor_two = TestClient(client.app)
    _make_user(doctor_two, "doctor_b")
    _login(doctor_two, "doctor_b")
    second_attempt = doctor_two.post(
        "/api/attempts", json={"task_code": "fna_binary_5class"}
    ).json()
    second_answers = ["倾向是癌", "确定不是癌", "倾向不是癌", "确定是癌"]
    for question, answer in zip(second_attempt["questions"], second_answers, strict=True):
        response = doctor_two.put(
            f"/api/attempts/{second_attempt['id']}/answers/{question['id']}",
            json={"answer_text": answer},
        )
        assert response.status_code == 200, response.text
    submit_response = doctor_two.post(f"/api/attempts/{second_attempt['id']}/submit")
    assert submit_response.status_code == 200, submit_response.text

    admin = TestClient(client.app)
    _make_user(admin, "root2", ROLE_ADMIN)
    _login(admin, "root2")

    summary_response = admin.get("/api/admin/attempts/user-summaries")
    assert summary_response.status_code == 200, summary_response.text
    users = {user["username"]: user for user in summary_response.json()}

    doctor_one_metrics = users["doctor_a"]
    assert doctor_one_metrics["submitted_answered"] == 4
    assert doctor_one_metrics["in_progress_answered"] == 1
    assert doctor_one_metrics["accuracy"] == 4 / 5
    assert doctor_one_metrics["uncertain"] == 1
    assert doctor_one_metrics["ppv"] == 1.0
    assert doctor_one_metrics["npv"] == 1.0
    assert doctor_one_metrics["sensitivity"] == 1.0
    assert doctor_one_metrics["specificity"] == 1.0

    submitted_only = admin.get(
        f"/api/admin/attempts/user-summaries?status=submitted&user_id={doctor_one_id}"
    )
    assert submitted_only.status_code == 200, submitted_only.text
    [submitted_user] = submitted_only.json()
    assert submitted_user["username"] == "doctor_a"
    assert submitted_user["submitted_answered"] == 4
    assert submitted_user["in_progress_answered"] == 0
    assert submitted_user["accuracy"] == 3 / 4
    assert submitted_user["uncertain"] == 1

    in_progress_only = admin.get(
        f"/api/admin/attempts/user-summaries?status=in_progress&user_id={doctor_one_id}"
    )
    assert in_progress_only.status_code == 200, in_progress_only.text
    [in_progress_user] = in_progress_only.json()
    assert in_progress_user["username"] == "doctor_a"
    assert in_progress_user["submitted_answered"] == 0
    assert in_progress_user["in_progress_answered"] == 1
    assert in_progress_user["accuracy"] == 1.0
    assert in_progress_user["auc"] is None
