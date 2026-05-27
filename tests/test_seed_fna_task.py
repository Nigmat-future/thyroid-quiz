"""FNA 合并导入脚本测试。"""

from __future__ import annotations

import csv
from pathlib import Path

from PIL import Image
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import ROLE_ADMIN, Question, Task, User
from app.security import hash_password
from app.services.fna import FNA_TASK_CODE, parse_source_note
from scripts.seed_fna_task import DATASETS, assign_batches, load_source_rows, seed_task


def _write_png(path: Path, seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (16, 16), color=(seed % 255, (seed * 3) % 255, (seed * 5) % 255))
    img.save(path, format="PNG")


def _make_fna_fixture(root: Path, rows_per_center: int = 1) -> None:
    image_dir = root / "images"
    for idx, (_, csv_name) in enumerate(DATASETS):
        with (root / csv_name).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["file_path", "label"])
            writer.writeheader()
            for row_idx in range(rows_per_center):
                label = str((idx + row_idx) % 2)
                rel = f"images/{idx}_{row_idx}.png"
                _write_png(image_dir / f"{idx}_{row_idx}.png", idx * 10 + row_idx + 1)
                writer.writerow({"file_path": rel, "label": label})


def _create_admin() -> None:
    with SessionLocal() as db:
        db.add(
            User(
                username="root",
                password_hash=hash_password("secret123"),
                role=ROLE_ADMIN,
                is_active=1,
            )
        )
        db.commit()


def test_load_source_rows_validates_all_configured_csvs(tmp_path: Path) -> None:
    _make_fna_fixture(tmp_path)

    rows = load_source_rows(tmp_path)

    assert len(rows) == len(DATASETS)
    assert {r.source_center for r in rows} == {center for center, _ in DATASETS}
    assert {r.ground_truth for r in rows} == {"确定不是癌", "确定是癌"}


def test_assign_batches_round_robins_centers_and_positions(tmp_path: Path) -> None:
    _make_fna_fixture(tmp_path, rows_per_center=2)
    rows = load_source_rows(tmp_path)

    batched = assign_batches(rows, batch_size=3)

    expected_centers = [center for center, _ in DATASETS]
    assert [item.row.source_center for item in batched[: len(DATASETS)]] == expected_centers
    assert [item.row.source_center for item in batched[len(DATASETS) :]] == expected_centers
    assert [item.batch_index for item in batched] == [
        idx // 3 for idx in range(len(DATASETS) * 2)
    ]
    assert [item.batch_position for item in batched] == [
        idx % 3 for idx in range(len(DATASETS) * 2)
    ]


def test_seed_task_replace_does_not_duplicate_questions(tmp_path: Path) -> None:
    _make_fna_fixture(tmp_path)
    _create_admin()

    seed_task(tmp_path, replace=False)
    seed_task(tmp_path, replace=True)

    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.code == FNA_TASK_CODE))
        assert task is not None
        assert task.answer_options == [
            "确定不是癌",
            "倾向不是癌",
            "不确定",
            "倾向是癌",
            "确定是癌",
        ]
        n_questions = db.scalar(select(func.count(Question.id)).where(Question.task_id == task.id))
        assert n_questions == len(DATASETS)
        first_question = db.scalar(
            select(Question).where(Question.task_id == task.id).order_by(Question.order_index)
        )
        source_center, source_file_path = parse_source_note(first_question.note)
        assert source_center
        assert source_file_path.startswith("images/")


def test_seed_task_persists_balanced_batch_metadata(tmp_path: Path) -> None:
    _make_fna_fixture(tmp_path, rows_per_center=2)
    _create_admin()

    seed_task(tmp_path, replace=False, batch_size=3)

    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.code == FNA_TASK_CODE))
        questions = list(
            db.scalars(
                select(Question).where(Question.task_id == task.id).order_by(Question.order_index)
            ).all()
        )

    assert len(questions) == len(DATASETS) * 2
    assert [q.batch_index for q in questions] == [idx // 3 for idx in range(len(questions))]
    assert [q.batch_position for q in questions] == [idx % 3 for idx in range(len(questions))]
    centers = [parse_source_note(q.note)[0] for q in questions]
    expected_centers = [center for center, _ in DATASETS]
    assert centers[: len(DATASETS)] == expected_centers
    assert centers[len(DATASETS) :] == expected_centers
