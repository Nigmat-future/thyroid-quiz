"""Restore uploaded data from volume - fix Railway CLI path mangling."""
from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path

DATA = Path("/data")


def find_largest_file(*names: str) -> Path | None:
    """Find the largest file matching any of the given names under /data."""
    best: Path | None = None
    best_size = 0
    for name in names:
        for f in DATA.rglob(name):
            if not f.is_file():
                continue
            sz = f.stat().st_size
            if sz > best_size:
                best = f
                best_size = sz
    return best


def restore_db() -> bool:
    target = DATA / "thyroid_quiz.db"

    # 1. Check if already at the correct place
    if target.exists() and target.stat().st_size > 100_000:
        print(f"[restore] DB already at {target} ({target.stat().st_size} bytes)")
        return True

    # 2. Find uploaded file anywhere under /data
    uploaded = find_largest_file("thyroid_quiz.db")
    if uploaded and uploaded != target:
        print(f"[restore] Found uploaded DB at: {uploaded} ({uploaded.stat().st_size} bytes)")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(uploaded, target)
        print(f"[restore] Copied -> {target} ({target.stat().st_size} bytes)")
        return True

    # 3. Try brute-force listing all files in /data dirs
    print(f"[restore] Searching /data for all files...")
    all_files = list(DATA.rglob("*"))
    print(f"[restore] Total files under /data: {len(all_files)}")
    for f in all_files:
        print(f"  {f.relative_to(DATA)} ({f.stat().st_size} bytes)")
    return False


def extract_images() -> int:
    extracted = 0
    for f in DATA.rglob("*.tar.gz"):
        if f.stat().st_size > 1_000_000:
            print(f"[restore] Extracting tar: {f.name}")
            with tarfile.open(f, "r:gz") as tar:
                tar.extractall(path=DATA)
            os.remove(f)
            extracted += 1

    img_dir = DATA / "storage" / "images"
    if img_dir.exists():
        count = sum(1 for _ in img_dir.rglob("*") if _.is_file())
        print(f"[restore] Images found: {count}")
    else:
        print("[restore] No images directory found")
    return extracted


if __name__ == "__main__":
    print("[restore] Starting data restoration...")
    db_ok = restore_db()
    extract_images()
    if db_ok:
        print("[restore] Database restored. Alembic will detect it's at current revision.")
    print("[restore] Done")
