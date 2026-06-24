"""FNA binary-direction scoring tests."""

from __future__ import annotations

import csv
import io
import json

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ROLE_ADMIN, ROLE_AUTHOR, ROLE_DOCTOR, Answer, Attempt, User
from app.services.attempt_metrics import (
    AnswerMetricRow,
    malignancy_score_for,
    summarize_attempt_metrics,
)
from app.services.fna import FNA_ANSWER_OPTIONS, build_source_note


def _png(seed: int) -> bytes:
    image = Image.new(
        "RGB",
        (16, 16),
        color=(seed % 255, (seed * 7) % 255, (seed * 13) % 255),
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


def test_fna_metrics_use_binary_direction_when_answer_is_likely() -> None:
    rows = [
        AnswerMetricRow(answer_text="倾向不是癌", ground_truth="确定不是癌"),
        AnswerMetricRow(answer_text="倾向是癌", ground_truth="确定是癌"),
        AnswerMetricRow(answer_text="不确定", ground_truth="确定是癌"),
    ]

    metrics = summarize_attempt_metrics(rows)

    assert metrics.correct == 2
    assert metrics.accuracy == 2 / 3


def test_fna_auc_scores_follow_configured_risk_values() -> None:
    scores = [
        malignancy_score_for("确定不是癌"),
        malignancy_score_for("倾向不是癌"),
        malignancy_score_for("不确定"),
        malignancy_score_for("倾向是癌"),
        malignancy_score_for("确定是癌"),
    ]

    assert scores == [0.0, 0.3, 0.5, 0.7, 1.0]


def test_submit_persists_fna_binary_direction_correctness(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "author1", ROLE_AUTHOR)
    _login(author, "author1")
    response = author.post(
        "/api/tasks",
        json={
            "code": "fna_scoring",
            "name": "FNA scoring",
            "answer_options": FNA_ANSWER_OPTIONS,
            "is_published": True,
        },
    )
    assert response.status_code == 201, response.text
    response = author.post(
        "/api/tasks/fna_scoring/questions/upload",
        data={"ground_truths": json.dumps(["确定不是癌", "确定是癌", "确定是癌"])},
        files=[
            ("files", ("a.png", _png(1), "image/png")),
            ("files", ("b.png", _png(2), "image/png")),
            ("files", ("c.png", _png(3), "image/png")),
        ],
    )
    assert response.status_code == 201, response.text

    doctor = TestClient(client.app)
    _make_user(doctor, "doctor1")
    _login(doctor, "doctor1")
    attempt = doctor.post("/api/attempts", json={"task_code": "fna_scoring"}).json()
    answers = ["倾向不是癌", "倾向是癌", "不确定"]
    for question, answer_text in zip(attempt["questions"], answers, strict=True):
        response = doctor.put(
            f"/api/attempts/{attempt['id']}/answers/{question['id']}",
            json={"answer_text": answer_text},
        )
        assert response.status_code == 200, response.text

    response = doctor.post(f"/api/attempts/{attempt['id']}/submit")
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        saved_attempt = db.get(Attempt, attempt["id"])
        assert saved_attempt is not None
        saved_answers = list(
            db.scalars(
                select(Answer)
                .where(Answer.attempt_id == attempt["id"])
                .order_by(Answer.id.asc())
            ).all()
        )

    assert saved_attempt.correct == 2
    assert saved_attempt.score == 2 / 3
    assert [answer.is_correct for answer in saved_answers] == [1, 1, 0]


def test_csv_answers_export_uses_fna_binary_scores(client: TestClient) -> None:
    author = TestClient(client.app)
    _make_user(author, "author1", ROLE_AUTHOR)
    _login(author, "author1")
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
    response = author.post(
        "/api/tasks/fna_binary_5class/questions/upload",
        data={
            "ground_truths": json.dumps(["确定不是癌", "确定是癌"]),
            "notes": json.dumps(
                [
                    build_source_note("重庆", "重庆test/benign/a.png"),
                    build_source_note("福建", "福建test/malignant/b.png"),
                ]
            ),
        },
        files=[
            ("files", ("a.png", _png(21), "image/png")),
            ("files", ("b.png", _png(22), "image/png")),
        ],
    )
    assert response.status_code == 201, response.text

    doctor = TestClient(client.app)
    _make_user(doctor, "doctor1")
    _login(doctor, "doctor1")
    attempt = doctor.post("/api/attempts", json={"task_code": "fna_binary_5class"}).json()
    questions = attempt["questions"]
    doctor.put(
        f"/api/attempts/{attempt['id']}/answers/{questions[0]['id']}",
        json={"answer_text": "倾向不是癌", "review_flag": True, "time_spent_seconds": 9},
    )
    doctor.put(
        f"/api/attempts/{attempt['id']}/answers/{questions[1]['id']}",
        json={"answer_text": "倾向是癌", "time_spent_seconds": 14},
    )
    doctor.post(f"/api/attempts/{attempt['id']}/submit")

    admin = TestClient(client.app)
    _make_user(admin, "root", ROLE_ADMIN)
    _login(admin, "root")
    response = admin.get("/api/admin/exports/answers.csv")
    assert response.status_code == 200

    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert {row["truth_binary"] for row in rows} == {"0", "1"}
    assert {row["doctor_malignancy_score"] for row in rows} == {"0.3", "0.7"}
    assert {row["is_correct"] for row in rows} == {"1"}
    assert {row["source_center"] for row in rows} == {"重庆", "福建"}
    assert {row["time_spent_seconds"] for row in rows} == {"9", "14"}
