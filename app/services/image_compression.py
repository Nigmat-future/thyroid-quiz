"""存量题库图片压缩服务。"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Final, assert_never

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Question

DEFAULT_JPEG_QUALITY: Final = 82
DEFAULT_MIN_BYTES: Final = 1_048_576
DEFAULT_LIMIT: Final = 500
JPEG_EXTENSION: Final = ".jpg"
JPEG_COMPRESSION_MARKER: Final = b"thyropada-compressed-v1"


@dataclass(frozen=True, slots=True)
class CompressionOptions:
    min_bytes: int = DEFAULT_MIN_BYTES
    quality: int = DEFAULT_JPEG_QUALITY
    limit: int | None = DEFAULT_LIMIT
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class CompressedBytes:
    data: bytes
    before_bytes: int
    after_bytes: int


@dataclass(frozen=True, slots=True)
class AlreadyCompressed:
    before_bytes: int


@dataclass(frozen=True, slots=True)
class AnimatedImage:
    before_bytes: int


@dataclass(frozen=True, slots=True)
class NotSmaller:
    before_bytes: int
    after_bytes: int


@dataclass(frozen=True, slots=True)
class UnreadableImage:
    before_bytes: int
    reason: str


ImageCompressionAttempt = (
    CompressedBytes | AlreadyCompressed | AnimatedImage | NotSmaller | UnreadableImage
)


@dataclass(frozen=True, slots=True)
class CompressionSummary:
    scanned_paths: int
    large_candidates: int
    compressed_files: int
    updated_rows: int
    skipped_small: int
    skipped_missing: int
    skipped_marked: int
    skipped_animated: int
    skipped_unreadable: int
    skipped_not_smaller: int
    bytes_before: int
    bytes_after: int


def compress_image_bytes(
    raw: bytes, quality: int = DEFAULT_JPEG_QUALITY
) -> ImageCompressionAttempt:
    """把图片重压为带标记的 JPEG；不缩放，若无收益则返回跳过原因。"""
    before_bytes = len(raw)
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.info.get("comment") == JPEG_COMPRESSION_MARKER:
                return AlreadyCompressed(before_bytes=before_bytes)
            if getattr(im, "is_animated", False):
                return AnimatedImage(before_bytes=before_bytes)

            rgb = im.convert("RGB")
            out = io.BytesIO()
            rgb.save(
                out,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
                comment=JPEG_COMPRESSION_MARKER,
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return UnreadableImage(before_bytes=before_bytes, reason=str(exc))

    compressed = out.getvalue()
    after_bytes = len(compressed)
    if after_bytes >= before_bytes:
        return NotSmaller(before_bytes=before_bytes, after_bytes=after_bytes)
    return CompressedBytes(data=compressed, before_bytes=before_bytes, after_bytes=after_bytes)


def _safe_storage_path(image_path: str) -> Path | None:
    rel = (image_path or "").lstrip("/").replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        return None

    base = settings.storage_dir.resolve()
    target = (settings.storage_dir / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None

    if not target.exists() or not target.is_file():
        return None
    return target


def _store_compressed_bytes(data: bytes) -> tuple[str, str]:
    sha = hashlib.sha256(data).hexdigest()
    bucket = settings.storage_images_dir / sha[:2]
    bucket.mkdir(parents=True, exist_ok=True)
    target = bucket / f"{sha}{JPEG_EXTENSION}"
    if not target.exists() or target.stat().st_size != len(data):
        target.write_bytes(data)
    rel_path = target.relative_to(settings.storage_dir).as_posix()
    return rel_path, sha


def _question_image_paths(db: Session) -> list[str]:
    rows = db.scalars(
        select(Question.image_path)
        .where(Question.is_deleted == 0)
        .group_by(Question.image_path)
        .order_by(Question.image_path)
    ).all()
    return list(rows)


def _update_questions(db: Session, old_path: str, new_path: str, sha: str) -> int:
    result = db.execute(
        update(Question)
        .where(Question.image_path == old_path)
        .values(image_path=new_path, image_sha256=sha)
    )
    db.commit()
    return int(result.rowcount or 0)


def compress_existing_question_images(
    db: Session,
    options: CompressionOptions | None = None,
) -> CompressionSummary:
    """压缩题库中已存在的大图，并把题库记录指向新文件。"""
    opts = options or CompressionOptions()
    scanned_paths = 0
    large_candidates = 0
    compressed_files = 0
    updated_rows = 0
    skipped_small = 0
    skipped_missing = 0
    skipped_marked = 0
    skipped_animated = 0
    skipped_unreadable = 0
    skipped_not_smaller = 0
    bytes_before = 0
    bytes_after = 0

    for image_path in _question_image_paths(db):
        scanned_paths += 1
        source = _safe_storage_path(image_path)
        if source is None:
            skipped_missing += 1
            continue

        source_size = source.stat().st_size
        if source_size < opts.min_bytes:
            skipped_small += 1
            continue

        large_candidates += 1
        if opts.limit is not None and large_candidates > opts.limit:
            break

        attempt = compress_image_bytes(source.read_bytes(), quality=opts.quality)
        match attempt:
            case CompressedBytes(data=data, before_bytes=before, after_bytes=after):
                compressed_files += 1
                bytes_before += before
                bytes_after += after
                if opts.dry_run:
                    continue
                new_path, sha = _store_compressed_bytes(data)
                updated_rows += _update_questions(db, image_path, new_path, sha)
            case AlreadyCompressed():
                skipped_marked += 1
            case AnimatedImage():
                skipped_animated += 1
            case UnreadableImage():
                skipped_unreadable += 1
            case NotSmaller():
                skipped_not_smaller += 1
            case _ as unreachable:
                assert_never(unreachable)

    return CompressionSummary(
        scanned_paths=scanned_paths,
        large_candidates=large_candidates,
        compressed_files=compressed_files,
        updated_rows=updated_rows,
        skipped_small=skipped_small,
        skipped_missing=skipped_missing,
        skipped_marked=skipped_marked,
        skipped_animated=skipped_animated,
        skipped_unreadable=skipped_unreadable,
        skipped_not_smaller=skipped_not_smaller,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
    )
