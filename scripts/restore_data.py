"""Restore uploaded data from the Railway volume.

Railway CLI on Windows can upload files into paths such as
``/data/F:/some/local/path``. This script repairs those misplaced uploads before
the app starts.
"""
from __future__ import annotations

import os
import shutil
import tarfile
from pathlib import Path

DATA = Path(os.environ.get("RESTORE_DATA_DIR", "/data"))


def count_files(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def find_largest_file(*names: str) -> Path | None:
    """Find the largest file matching any of the given names under /data."""
    if not DATA.exists():
        print(f"[restore] Data directory does not exist: {DATA}")
        return None

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
    target_size = target.stat().st_size if target.exists() else 0

    # Prefer the largest uploaded DB. A tiny target can be created by Alembic
    # when restoration was skipped by Railway's startCommand override.
    uploaded = find_largest_file("thyroid_quiz.db")
    if uploaded:
        uploaded_size = uploaded.stat().st_size
        if uploaded.resolve() != target.resolve() and uploaded_size > max(target_size, 100_000):
            print(f"[restore] Found uploaded DB at: {uploaded} ({uploaded_size} bytes)")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(uploaded, target)
            print(f"[restore] Copied -> {target} ({target.stat().st_size} bytes)")
            return True

    if target_size > 100_000:
        print(f"[restore] DB already at {target} ({target_size} bytes)")
        return True

    # Last chance: list everything so deployment logs show where files landed.
    print("[restore] Searching /data for all files...")
    all_files = list(DATA.rglob("*")) if DATA.exists() else []
    print(f"[restore] Total files under /data: {len(all_files)}")
    for f in all_files:
        if f.is_file():
            print(f"  {f.relative_to(DATA)} ({f.stat().st_size} bytes)")
    return False


def safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    base = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise RuntimeError(f"Unsafe tar member path: {member.name}") from exc
    tar.extractall(path=dest)


def merge_misplaced_images() -> int:
    target = DATA / "storage" / "images"
    target.mkdir(parents=True, exist_ok=True)

    merged = 0
    for img_dir in DATA.rglob("images"):
        if not img_dir.is_dir() or img_dir.parent.name != "storage":
            continue
        if img_dir.resolve() == target.resolve():
            continue

        source_count = count_files(img_dir)
        if source_count == 0:
            continue
        current_count = count_files(target)
        if current_count >= source_count:
            print(
                f"[restore] Images already present at {target} "
                f"({current_count} files); source {img_dir} has {source_count}"
            )
            continue

        print(f"[restore] Merging images from {img_dir} ({source_count} files)")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(img_dir, target, dirs_exist_ok=True)
        merged += source_count

    return merged


def extract_images() -> int:
    extracted = 0
    for f in DATA.rglob("*.tar.gz"):
        if f.stat().st_size > 1_000_000:
            print(f"[restore] Extracting tar: {f}")
            try:
                with tarfile.open(f, "r:gz") as tar:
                    safe_extract(tar, DATA)
            except (EOFError, OSError, tarfile.TarError) as exc:
                print(f"[restore] Skipping unreadable tar archive {f}: {exc}")
                continue
            else:
                os.remove(f)
                extracted += 1

    merge_misplaced_images()

    img_dir = DATA / "storage" / "images"
    count = count_files(img_dir)
    if count:
        print(f"[restore] Images found: {count}")
    else:
        print("[restore] No images directory found")
    return extracted


def _expected_image_count() -> int:
    """Threshold below which we treat the volume as unseeded and fetch the archive."""
    raw = os.environ.get("SEED_IMAGE_COUNT", "")
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def fetch_seed_archive() -> bool:
    """Download the seed tarball from a public URL if the volume looks empty.

    Triggered only when SEED_ARCHIVE_URL is set and the on-volume image count
    is below SEED_IMAGE_COUNT. Railway CLI can't push files into a volume, so
    we ship the dataset as a GitHub Release asset and pull it here on cold start.
    """
    url = os.environ.get("SEED_ARCHIVE_URL", "").strip()
    if not url:
        return False

    img_dir = DATA / "storage" / "images"
    have = count_files(img_dir)
    need = _expected_image_count()
    if need and have >= need:
        print(f"[restore] Seed not needed ({have} >= {need} images)")
        return False

    dest = DATA / "seed.tar.gz"
    print(f"[restore] Fetching seed archive: {url} -> {dest}")
    # curl: -L follow redirect (release assets 302), --fail surface HTTP errors,
    # resume-friendly via -C - in case a partial file lingers from a prior boot.
    rc = os.system(
        f"curl -L --fail -C - --retry 5 --retry-delay 5 "
        f"-o {dest} {url}"
    )
    if rc != 0 or not dest.exists() or dest.stat().st_size < 1_000_000:
        print(f"[restore] Seed download failed (rc={rc})")
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False
    print(f"[restore] Downloaded {dest.stat().st_size} bytes")
    return True


if __name__ == "__main__":
    print("[restore] Starting data restoration...")
    db_ok = restore_db()
    fetch_seed_archive()
    extract_images()
    if db_ok:
        print("[restore] Database restored. Alembic will detect it's at current revision.")
    print("[restore] Done")
