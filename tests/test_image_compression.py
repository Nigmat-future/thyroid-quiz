"""存量题库图片压缩测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import ROLE_ADMIN, Question, Task, User
from app.services.image_compression import (
    JPEG_COMPRESSION_MARKER,
    CompressionOptions,
    compress_existing_question_images,
)


def _write_large_bmp(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (192, 128))
    pixels = img.load()
    for y in range(img.height):
        for x in range(img.width):
            pixels[x, y] = ((x * 5) % 256, (y * 7) % 256, ((x + y) * 3) % 256)
    img.save(path, format="BMP")


def _create_question(image_path: str, image_sha256: str) -> int:
    with SessionLocal() as db:
        user = User(
            username="compress-admin",
            password_hash="hash",
            role=ROLE_ADMIN,
            is_active=1,
        )
        db.add(user)
        db.flush()

        task = Task(
            code="compress-task",
            name="压缩测试",
            answer_options_json='["A","B"]',
            created_by=user.id,
        )
        db.add(task)
        db.flush()

        question = Question(
            task_id=task.id,
            image_path=image_path,
            image_sha256=image_sha256,
            ground_truth="A",
            uploaded_by=user.id,
        )
        db.add(question)
        db.commit()
        return question.id


def test_compress_existing_question_images_rewrites_large_images_without_resizing() -> None:
    # Given
    source = settings.storage_images_dir / "legacy" / "large.bmp"
    _write_large_bmp(source)
    original_bytes = source.read_bytes()
    original_size = source.stat().st_size
    rel_path = source.relative_to(settings.storage_dir).as_posix()
    question_id = _create_question(rel_path, hashlib.sha256(original_bytes).hexdigest())

    # When
    with SessionLocal() as db:
        summary = compress_existing_question_images(
            db,
            CompressionOptions(min_bytes=1, quality=82, limit=10),
        )
        updated = db.scalar(select(Question).where(Question.id == question_id))

    # Then
    assert updated is not None
    target = settings.storage_dir / updated.image_path
    assert summary.compressed_files == 1
    assert summary.updated_rows == 1
    assert summary.bytes_before == original_size
    assert summary.bytes_after == target.stat().st_size
    assert target.suffix == ".jpg"
    assert target.stat().st_size < original_size
    assert updated.image_sha256 == hashlib.sha256(target.read_bytes()).hexdigest()
    with Image.open(target) as stored:
        assert stored.format == "JPEG"
        assert stored.size == (192, 128)
        assert stored.info.get("comment") == JPEG_COMPRESSION_MARKER


def test_compress_existing_question_images_skips_already_marked_images() -> None:
    # Given
    source = settings.storage_images_dir / "legacy" / "idempotent.bmp"
    _write_large_bmp(source)
    rel_path = source.relative_to(settings.storage_dir).as_posix()
    question_id = _create_question(rel_path, hashlib.sha256(source.read_bytes()).hexdigest())
    options = CompressionOptions(min_bytes=1, quality=82, limit=10)

    with SessionLocal() as db:
        compress_existing_question_images(db, options)
        first_path = db.scalar(select(Question.image_path).where(Question.id == question_id))

    # When
    with SessionLocal() as db:
        summary = compress_existing_question_images(db, options)
        second_path = db.scalar(select(Question.image_path).where(Question.id == question_id))

    # Then
    assert first_path == second_path
    assert summary.compressed_files == 0
    assert summary.updated_rows == 0
    assert summary.skipped_marked == 1
