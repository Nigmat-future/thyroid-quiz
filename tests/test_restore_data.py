from __future__ import annotations

from scripts import restore_data


def test_restore_db_prefers_larger_misplaced_upload(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(restore_data, "DATA", tmp_path)

    target = tmp_path / "thyroid_quiz.db"
    target.write_bytes(b"x" * 69_632)

    misplaced = tmp_path / "misplaced" / "Git" / "Git" / "thyroid_quiz.db"
    misplaced.parent.mkdir(parents=True)
    misplaced.write_bytes(b"valid-db" * 800_000)

    assert restore_data.restore_db() is True
    assert target.read_bytes() == misplaced.read_bytes()


def test_merge_misplaced_images_into_storage_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(restore_data, "DATA", tmp_path)

    misplaced = tmp_path / "misplaced" / "Git" / "Git" / "storage" / "images" / "ab"
    misplaced.mkdir(parents=True)
    (misplaced / "image.jpg").write_bytes(b"image-bytes")

    assert restore_data.merge_misplaced_images() == 1
    assert (tmp_path / "storage" / "images" / "ab" / "image.jpg").read_bytes() == b"image-bytes"
