"""Restore uploaded data from volume - fix Railway CLI path mangling."""
from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path

DATA = Path("/data")


def restore_db() -> bool:
    target = DATA / "thyroid_quiz.db"
    for f in DATA.rglob("thyroid_quiz.db"):
        if f == target:
            continue
        size = f.stat().st_size
        if size > 100_000:
            print(f"[restore] Found DB: {f} ({size} bytes)")
            shutil.copy2(f, target)
            print(f"[restore] Copied to {target}")
            return True
    print("[restore] No valid uploaded DB found (fresh setup)")
    return False


def extract_images() -> int:
    extracted = 0
    for f in DATA.rglob("*.tar.gz"):
        size = f.stat().st_size
        if size > 1_000_000:
            print(f"[restore] Found tar: {f} ({size} bytes)")
            with tarfile.open(f, "r:gz") as tar:
                tar.extractall(path=DATA)
            print(f"[restore] Extracted from {f.name}")
            os.remove(f)
            extracted += 1
    for f in DATA.rglob("*.tgz"):
        if f.stat().st_size > 1_000_000:
            with tarfile.open(f, "r:gz") as tar:
                tar.extractall(path=DATA)
            os.remove(f)
            extracted += 1
    # Count images
    img_dir = DATA / "storage" / "images"
    if img_dir.exists():
        count = sum(1 for _ in img_dir.rglob("*") if _.is_file())
        print(f"[restore] Total images: {count}")
    else:
        print("[restore] No images directory found")
    return extracted


if __name__ == "__main__":
    print("[restore] Starting data restoration...")
    restore_db()
    extract_images()
    print("[restore] Done")
