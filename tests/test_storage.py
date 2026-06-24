"""图片存储压缩测试。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.config import settings
from app.services.storage import store_local_image


def _write_gradient_bmp(path: Path) -> None:
    img = Image.new("RGB", (128, 96))
    pixels = img.load()
    for y in range(img.height):
        for x in range(img.width):
            pixels[x, y] = ((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256)
    img.save(path, format="BMP")


def test_store_local_image_compresses_large_image_without_resizing(tmp_path: Path) -> None:
    source = tmp_path / "source.bmp"
    _write_gradient_bmp(source)
    original_size = source.stat().st_size

    rel_path, _ = store_local_image(source)
    target = settings.storage_dir / rel_path

    assert target.suffix == ".jpg"
    assert target.stat().st_size < original_size
    with Image.open(target) as stored:
        assert stored.format == "JPEG"
        assert stored.size == (128, 96)
