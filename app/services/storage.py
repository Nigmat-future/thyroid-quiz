"""图片存储：sha256 命名 + 两位前缀分桶。"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from PIL import Image, UnidentifiedImageError

from app.config import settings

# 允许的图片扩展名 → MIME 类型；用于回放时设置 Content-Type
ALLOWED_EXTS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _ext_for(filename: str | None, sniffed_format: str | None) -> str:
    """优先用文件名后缀；否则按 PIL 嗅探出的格式补一个。"""
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in ALLOWED_EXTS:
            return ext
    if sniffed_format:
        sniffed = "." + sniffed_format.lower()
        if sniffed in ALLOWED_EXTS:
            return sniffed
        if sniffed_format.lower() == "jpeg":
            return ".jpg"
    return ".bin"  # 走不到这里；上层会拦


def _validate_image(data: bytes) -> str:
    """用 PIL 校验确实是图片，返回 PIL 嗅探出的 format。"""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
            return im.format or "JPEG"
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"非法图片或文件损坏：{exc}"
        ) from exc


def _store_image_bytes(raw: bytes, filename: str | None = None) -> tuple[str, str]:
    """
    校验并落盘一张图片，返回 (image_path, sha256)。

    image_path 形如 "images/ab/abcdef....jpg"，相对 STORAGE_DIR。
    若 sha256 已存在则复用现有文件，避免重复落盘。
    """
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件为空")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"文件超过上限 {settings.max_upload_bytes // 1024 // 1024} MB",
        )

    sniffed = _validate_image(raw)
    ext = _ext_for(filename, sniffed)
    sha = hashlib.sha256(raw).hexdigest()

    bucket = settings.storage_images_dir / sha[:2]
    bucket.mkdir(parents=True, exist_ok=True)
    target = bucket / f"{sha}{ext}"
    if not target.exists():
        target.write_bytes(raw)

    rel = target.relative_to(settings.storage_dir).as_posix()
    return rel, sha


def store_upload(file: UploadFile) -> tuple[str, str]:
    """落盘一张网页上传图片，返回 (image_path, sha256)。"""
    return _store_image_bytes(file.file.read(), file.filename)


def store_local_image(path: str | Path) -> tuple[str, str]:
    """落盘一张本地图片，返回 (image_path, sha256)。"""
    source = Path(path)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"图片不存在：{source}")
    return _store_image_bytes(source.read_bytes(), source.name)


def resolve_image_path(image_path: str) -> Path:
    """把数据库里存的相对路径解析为绝对路径，并防穿越。"""
    rel = (image_path or "").lstrip("/").replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "非法图片路径")
    target = (settings.storage_dir / rel).resolve()
    base = settings.storage_dir.resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "非法图片路径") from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在")
    return target


def media_type_of(path: Path) -> str:
    return ALLOWED_EXTS.get(path.suffix.lower(), "application/octet-stream")


def public_url_of(image_path: str) -> str:
    """供前端拉图的鉴权 URL（M2 起强制登录可见）。"""
    return f"/storage/{image_path.lstrip('/')}"
