# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pillow>=10.4",
#   "sqlalchemy>=2.0.30",
#   "pydantic-settings>=2.4",
# ]
# ///
"""压缩题库里已经存在的大图。

使用：
    python -m scripts.compress_existing_images

环境变量：
    IMAGE_COMPRESS_ENABLED=1
    IMAGE_COMPRESS_MIN_BYTES=1048576
    IMAGE_COMPRESS_QUALITY=82
    IMAGE_COMPRESS_LIMIT=500
"""

from __future__ import annotations

import os

from app.db import SessionLocal
from app.services.image_compression import (
    DEFAULT_JPEG_QUALITY,
    DEFAULT_LIMIT,
    DEFAULT_MIN_BYTES,
    CompressionOptions,
    CompressionSummary,
    compress_existing_question_images,
)


def _enabled_from_env() -> bool:
    raw = os.environ.get("IMAGE_COMPRESS_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[compress_images] {name}={raw!r} 不是整数，使用默认值 {default}")
        return default


def _env_limit() -> int | None:
    value = _env_int("IMAGE_COMPRESS_LIMIT", DEFAULT_LIMIT)
    if value <= 0:
        return None
    return value


def _options_from_env() -> CompressionOptions:
    return CompressionOptions(
        min_bytes=max(0, _env_int("IMAGE_COMPRESS_MIN_BYTES", DEFAULT_MIN_BYTES)),
        quality=max(1, min(95, _env_int("IMAGE_COMPRESS_QUALITY", DEFAULT_JPEG_QUALITY))),
        limit=_env_limit(),
    )


def _saved_bytes(summary: CompressionSummary) -> int:
    return max(0, summary.bytes_before - summary.bytes_after)


def main() -> int:
    if not _enabled_from_env():
        print("[compress_images] IMAGE_COMPRESS_ENABLED=0，已跳过。")
        return 0

    options = _options_from_env()
    print(
        "[compress_images] 开始压缩："
        f"min_bytes={options.min_bytes}, quality={options.quality}, limit={options.limit}"
    )
    with SessionLocal() as db:
        summary = compress_existing_question_images(db, options)

    print(
        "[compress_images] 完成："
        f"扫描 {summary.scanned_paths} 个路径，"
        f"大图候选 {summary.large_candidates} 个，"
        f"压缩 {summary.compressed_files} 个文件，"
        f"更新 {summary.updated_rows} 条题库记录，"
        f"节省 {_saved_bytes(summary)} bytes。"
    )
    print(
        "[compress_images] 跳过："
        f"小图 {summary.skipped_small}，"
        f"缺失 {summary.skipped_missing}，"
        f"已压缩 {summary.skipped_marked}，"
        f"动图 {summary.skipped_animated}，"
        f"损坏 {summary.skipped_unreadable}，"
        f"无收益 {summary.skipped_not_smaller}。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
