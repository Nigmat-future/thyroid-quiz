"""把本地 FNA test CSV 合并导入为五档二分类任务。

使用：
    python -m scripts.seed_fna_task --dry-run
    python -m scripts.seed_fna_task --replace
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ROLE_ADMIN, Answer, Attempt, Question, Task, User
from app.services.fna import (
    FNA_ANSWER_OPTIONS,
    FNA_GROUND_TRUTH_BY_LABEL,
    FNA_TASK_CODE,
    FNA_TASK_NAME,
    build_source_note,
)
from app.services.storage import store_local_image

DEFAULT_FNA_ROOT = Path(r"D:\Desktop\项目\FNA")
DEFAULT_BATCH_SIZE = 100
DATASETS = (
    ("重庆", "重庆test.csv"),
    ("福建", "福建test.csv"),
    ("赣人民", "赣人民test.csv"),
    ("赣医", "赣医test.csv"),
    ("九江", "九江test.csv"),
    ("南昌", "南昌test.csv"),
    ("苏州", "苏州test.csv"),
)


@dataclass(frozen=True)
class SourceRow:
    source_center: str
    source_file_path: str
    image_path: Path
    label: str
    ground_truth: str


@dataclass(frozen=True)
class BatchedSourceRow:
    row: SourceRow
    order_index: int
    batch_index: int
    batch_position: int


def _read_dataset(
    root: Path,
    source_center: str,
    csv_name: str,
    skip_invalid: bool,
) -> list[SourceRow]:
    csv_path = root / csv_name
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 不存在：{csv_path}")

    rows: list[SourceRow] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or {"file_path", "label"} - set(reader.fieldnames):
            raise ValueError(f"{csv_path} 必须包含 file_path,label 两列")
        for line_no, row in enumerate(reader, start=2):
            rel = (row.get("file_path") or "").strip()
            label = (row.get("label") or "").strip()
            if label not in FNA_GROUND_TRUTH_BY_LABEL:
                raise ValueError(f"{csv_path}:{line_no} label 必须是 0 或 1，实际为 {label!r}")
            if not rel:
                raise ValueError(f"{csv_path}:{line_no} file_path 为空")
            image_path = root / rel
            if not image_path.exists():
                raise FileNotFoundError(f"{csv_path}:{line_no} 图片不存在：{image_path}")
            if image_path.stat().st_size == 0:
                message = f"{csv_path}:{line_no} 图片为空：{image_path}"
                if skip_invalid:
                    print(f"[seed_fna] 跳过无效图片：{message}", file=sys.stderr)
                    continue
                raise ValueError(message)
            rows.append(
                SourceRow(
                    source_center=source_center,
                    source_file_path=rel.replace("\\", "/"),
                    image_path=image_path,
                    label=label,
                    ground_truth=FNA_GROUND_TRUTH_BY_LABEL[label],
                )
            )
    return rows


def load_source_rows(root: Path, skip_invalid: bool = False) -> list[SourceRow]:
    """读取并校验所有纳入合并任务的数据集。"""
    all_rows: list[SourceRow] = []
    for source_center, csv_name in DATASETS:
        all_rows.extend(_read_dataset(root, source_center, csv_name, skip_invalid=skip_invalid))
    return all_rows


def print_stats(rows: list[SourceRow]) -> None:
    by_center = Counter(r.source_center for r in rows)
    by_label = Counter(r.label for r in rows)
    print(f"[seed_fna] 待导入图片数：{len(rows)}")
    print("[seed_fna] 标签分布：" + ", ".join(f"{k}={by_label[k]}" for k in sorted(by_label)))
    print("[seed_fna] 中心分布：")
    for center, count in by_center.items():
        print(f"  - {center}: {count}")


def assign_batches(
    rows: list[SourceRow],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[BatchedSourceRow]:
    """按中心轮转均衡排题，再按批大小生成 batch_index/batch_position。"""
    if batch_size <= 0:
        raise ValueError("--batch-size 必须大于 0")

    center_order = [center for center, _ in DATASETS]
    grouped: dict[str, list[SourceRow]] = {center: [] for center in center_order}
    extras: list[str] = []
    for row in rows:
        if row.source_center not in grouped:
            grouped[row.source_center] = []
            extras.append(row.source_center)
        grouped[row.source_center].append(row)

    balanced: list[SourceRow] = []
    ordered_centers = center_order + extras
    offsets = {center: 0 for center in ordered_centers}
    remaining = len(rows)
    while remaining:
        progressed = False
        for center in ordered_centers:
            offset = offsets[center]
            bucket = grouped[center]
            if offset >= len(bucket):
                continue
            balanced.append(bucket[offset])
            offsets[center] = offset + 1
            remaining -= 1
            progressed = True
        if not progressed:
            break

    return [
        BatchedSourceRow(
            row=row,
            order_index=idx,
            batch_index=idx // batch_size,
            batch_position=idx % batch_size,
        )
        for idx, row in enumerate(balanced)
    ]


def _find_admin(db: Session) -> User:
    admin = db.scalar(select(User).where(User.role == ROLE_ADMIN).order_by(User.id.asc()))
    if admin is None:
        raise RuntimeError("未找到 admin 用户，请先运行：python -m scripts.init_admin")
    return admin


def _prepare_task(db: Session, replace: bool) -> Task:
    existing = db.scalar(select(Task).where(Task.code == FNA_TASK_CODE))
    if existing is not None and not replace:
        n_questions = db.scalar(
            select(func.count(Question.id)).where(
                Question.task_id == existing.id, Question.is_deleted == 0
            )
        )
        raise RuntimeError(
            f"任务 {FNA_TASK_CODE!r} 已存在，当前题数 {int(n_questions or 0)}；"
            "如需重建请加 --replace"
        )

    if existing is not None:
        attempt_ids = select(Attempt.id).where(Attempt.task_id == existing.id)
        db.execute(delete(Answer).where(Answer.attempt_id.in_(attempt_ids)))
        db.execute(delete(Attempt).where(Attempt.task_id == existing.id))
        db.execute(delete(Question).where(Question.task_id == existing.id))
        task = existing
    else:
        admin = _find_admin(db)
        task = Task(code=FNA_TASK_CODE, created_by=admin.id)
        db.add(task)

    task.name = FNA_TASK_NAME
    task.description = "7 个中心 test CSV 合并；医生五档判断，导出支持人类 AUC。"
    task.answer_options = FNA_ANSWER_OPTIONS
    task.randomize_options = 0
    task.is_published = 1
    return task


def seed_task(
    root: Path,
    replace: bool,
    rows: list[SourceRow] | None = None,
    skip_invalid: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    rows = rows if rows is not None else load_source_rows(root, skip_invalid=skip_invalid)
    print_stats(rows)
    batched_rows = assign_batches(rows, batch_size=batch_size)

    with SessionLocal() as db:
        task = _prepare_task(db, replace=replace)
        db.flush()
        admin = _find_admin(db)

        for idx, item in enumerate(batched_rows):
            row = item.row
            image_path, sha = store_local_image(row.image_path)
            db.add(
                Question(
                    task_id=task.id,
                    image_path=image_path,
                    image_sha256=sha,
                    ground_truth=row.ground_truth,
                    order_index=item.order_index,
                    batch_index=item.batch_index,
                    batch_position=item.batch_position,
                    note=build_source_note(row.source_center, row.source_file_path),
                    uploaded_by=admin.id,
                    is_deleted=0,
                )
            )
            if (idx + 1) % 500 == 0:
                print(f"[seed_fna] 已处理 {idx + 1}/{len(rows)}")

        db.commit()

    print(f"[seed_fna] 导入完成：任务 {FNA_TASK_CODE}，题目 {len(rows)}")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fna-root", type=Path, default=DEFAULT_FNA_ROOT, help="FNA 数据根目录")
    parser.add_argument("--dry-run", action="store_true", help="只校验并打印统计，不写数据库")
    parser.add_argument("--replace", action="store_true", help="若任务已存在，清空并重建该任务")
    parser.add_argument("--skip-invalid", action="store_true", help="跳过 0 字节等无效图片")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"每批题目数量，默认 {DEFAULT_BATCH_SIZE}",
    )
    args = parser.parse_args(argv)

    try:
        rows = load_source_rows(args.fna_root, skip_invalid=args.skip_invalid)
        if args.dry_run:
            print_stats(rows)
            print("[seed_fna] dry-run 完成，未写入数据库")
            return 0
        seed_task(
            args.fna_root,
            replace=args.replace,
            rows=rows,
            skip_invalid=args.skip_invalid,
            batch_size=args.batch_size,
        )
        return 0
    except Exception as exc:
        print(f"[seed_fna] 失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
