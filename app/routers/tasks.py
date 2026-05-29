"""任务（题库）+ 题目（图片）API。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.db import get_db
from app.models import (
    ROLE_ADMIN,
    ROLE_AUTHOR,
    ROLE_DOCTOR,
    Answer,
    Attempt,
    Question,
    Task,
    User,
)
from app.schemas import (
    QuestionAdminPublic,
    QuestionUpdate,
    TaskAdminPublic,
    TaskCreate,
    TaskPublic,
    TaskUpdate,
)
from app.services.storage import (
    media_type_of,
    public_url_of,
    resolve_image_path,
    store_upload,
)

tasks_router = APIRouter(prefix="/api/tasks", tags=["tasks"])
questions_router = APIRouter(prefix="/api/questions", tags=["questions"])
storage_router = APIRouter(prefix="/storage", tags=["storage"])


# ---------- helpers ----------

def _can_manage_task(user: User, task: Task) -> bool:
    if user.role == ROLE_ADMIN:
        return True
    if user.role == ROLE_AUTHOR and task.created_by == user.id:
        return True
    return False


def _require_manage(user: User, task: Task) -> None:
    if not _can_manage_task(user, task):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "你没有权限管理此任务")


def _task_admin_dict(db: Session, t: Task) -> dict:
    n = db.scalar(
        select(func.count(Question.id)).where(
            Question.task_id == t.id, Question.is_deleted == 0
        )
    )
    n_batches = db.scalar(
        select(func.count(func.distinct(Question.batch_index))).where(
            Question.task_id == t.id, Question.is_deleted == 0
        )
    )
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "description": t.description,
        "answer_options": t.answer_options,
        "randomize_options": bool(t.randomize_options),
        "is_published": bool(t.is_published),
        "n_questions": int(n or 0),
        "n_batches": int(n_batches or 1),
        "created_by": t.created_by,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _task_public_dict(db: Session, t: Task) -> dict:
    n_questions = db.scalar(
        select(func.count(Question.id)).where(
            Question.task_id == t.id, Question.is_deleted == 0
        )
    )
    n_batches = db.scalar(
        select(func.count(func.distinct(Question.batch_index))).where(
            Question.task_id == t.id, Question.is_deleted == 0
        )
    )
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "description": t.description,
        "answer_options": t.answer_options,
        "randomize_options": bool(t.randomize_options),
        "is_published": bool(t.is_published),
        "n_questions": int(n_questions or 0),
        "n_batches": int(n_batches or 1),
    }


def _question_admin_dict(q: Question) -> dict:
    return {
        "id": q.id,
        "task_id": q.task_id,
        "image_url": public_url_of(q.image_path),
        "image_sha256": q.image_sha256,
        "ground_truth": q.ground_truth,
        "order_index": q.order_index,
        "batch_index": q.batch_index,
        "batch_position": q.batch_position,
        "note": q.note,
        "uploaded_by": q.uploaded_by,
        "created_at": q.created_at,
    }


# ---------- 公共：医生可见 ----------

@tasks_router.get("", response_model=list[TaskPublic])
def list_tasks(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """医生看到的是 published 任务；author/admin 能看到自己/全部。"""
    stmt = select(Task)
    if user.role == ROLE_DOCTOR:
        stmt = stmt.where(Task.is_published == 1)
    elif user.role == ROLE_AUTHOR:
        # author 看到自己创建的 + 已发布的
        stmt = stmt.where((Task.created_by == user.id) | (Task.is_published == 1))
    stmt = stmt.order_by(Task.created_at.desc())
    return [_task_public_dict(db, t) for t in db.scalars(stmt).all()]


@tasks_router.get("/{code}", response_model=TaskPublic)
def get_task_public(
    code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    task = db.scalar(select(Task).where(Task.code == code))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if user.role == ROLE_DOCTOR and not task.is_published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return _task_public_dict(db, task)


@tasks_router.get("/{code}/batches", response_model=list[dict])
def list_task_batches(
    code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """按批次列出任务入口；医生首页用它避免一次面对全部题。"""
    task = db.scalar(select(Task).where(Task.code == code))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if user.role == ROLE_DOCTOR and not task.is_published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")

    batch_rows = db.execute(
        select(Question.batch_index, func.count(Question.id))
        .where(Question.task_id == task.id, Question.is_deleted == 0)
        .group_by(Question.batch_index)
        .order_by(Question.batch_index)
    ).all()
    if not batch_rows:
        return []

    attempts = db.scalars(
        select(Attempt).where(Attempt.user_id == user.id, Attempt.task_id == task.id)
    ).all()
    attempt_by_batch = {}
    for attempt in attempts:
        current = attempt_by_batch.get(attempt.batch_index)
        if current is None or (
            current.status != "in_progress" and attempt.status == "in_progress"
        ):
            attempt_by_batch[attempt.batch_index] = attempt

    total_batches = len(batch_rows)
    out = []
    for batch_index, total in batch_rows:
        attempt = attempt_by_batch.get(int(batch_index or 0))
        out.append(
            {
                "batch_index": int(batch_index or 0),
                "batch_label": f"第 {int(batch_index or 0) + 1} 批",
                "batch_total": total_batches,
                "total": int(total or 0),
                "status": attempt.status if attempt else "not_started",
                "attempt_id": attempt.id if attempt else None,
                "started_at": attempt.started_at if attempt else None,
                "submitted_at": attempt.submitted_at if attempt else None,
            }
        )
    return out


# ---------- author/admin：管理任务 ----------

@tasks_router.post("", response_model=TaskAdminPublic, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    user: User = Depends(require_role(ROLE_AUTHOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(Task).where(Task.code == payload.code)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "任务编码已存在")

    task = Task(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        answer_options_json=json.dumps(payload.answer_options, ensure_ascii=False),
        randomize_options=int(payload.randomize_options),
        is_published=int(payload.is_published),
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return _task_admin_dict(db, task)


@tasks_router.get("/{code}/admin", response_model=TaskAdminPublic)
def get_task_admin(
    code: str,
    user: User = Depends(require_role(ROLE_AUTHOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    task = db.scalar(select(Task).where(Task.code == code))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    _require_manage(user, task)
    return _task_admin_dict(db, task)


@tasks_router.patch("/{code}", response_model=TaskAdminPublic)
def update_task(
    code: str,
    payload: TaskUpdate,
    user: User = Depends(require_role(ROLE_AUTHOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    task = db.scalar(select(Task).where(Task.code == code))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    _require_manage(user, task)

    if payload.name is not None:
        task.name = payload.name
    if payload.description is not None:
        task.description = payload.description
    if payload.answer_options is not None:
        # 修改选项时，校验现有题目的 ground_truth 仍在新选项里
        new_set = set(payload.answer_options)
        used = db.scalars(
            select(Question.ground_truth).where(
                Question.task_id == task.id, Question.is_deleted == 0
            )
        ).all()
        missing = sorted({g for g in used if g not in new_set})
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"以下答案在题目中已使用，不能从选项里删除：{missing}",
            )
        task.answer_options_json = json.dumps(payload.answer_options, ensure_ascii=False)
    if payload.randomize_options is not None:
        task.randomize_options = int(payload.randomize_options)
    if payload.is_published is not None:
        task.is_published = int(payload.is_published)
    task.updated_at = func.now()
    db.commit()
    db.refresh(task)
    return _task_admin_dict(db, task)


@tasks_router.delete("/{code}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    code: str,
    user: User = Depends(require_role(ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    task = db.scalar(select(Task).where(Task.code == code))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    # 先清掉关联答题（answers→attempts），再删任务（questions 由 ORM 级联）。
    # 否则 attempts 会变成孤儿（SQLite 不强制外键）或触发外键冲突（Postgres）。
    attempt_ids = select(Attempt.id).where(Attempt.task_id == task.id)
    db.execute(delete(Answer).where(Answer.attempt_id.in_(attempt_ids)))
    db.execute(delete(Attempt).where(Attempt.task_id == task.id))
    db.delete(task)  # cascade 删 questions
    db.commit()


# ---------- 题目 ----------

@tasks_router.get("/{code}/questions", response_model=list[QuestionAdminPublic])
def list_questions_admin(
    code: str,
    user: User = Depends(require_role(ROLE_AUTHOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> list[dict]:
    task = db.scalar(select(Task).where(Task.code == code))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    _require_manage(user, task)

    qs = db.scalars(
        select(Question)
        .where(Question.task_id == task.id, Question.is_deleted == 0)
        .order_by(Question.order_index, Question.id)
    ).all()
    return [_question_admin_dict(q) for q in qs]


@tasks_router.post(
    "/{code}/questions/upload",
    response_model=list[QuestionAdminPublic],
    status_code=status.HTTP_201_CREATED,
)
def upload_questions(
    code: str,
    files: list[UploadFile] = File(..., description="图片文件，可多选"),
    ground_truths: str = Form(..., description="JSON 数组，与 files 顺序对齐"),
    notes: str | None = Form(None, description="JSON 数组，可选"),
    batch_index_start: int = Form(0, description="批次起始编号"),
    batch_size: int = Form(0, description="每批题数；0 表示沿用单批"),
    user: User = Depends(require_role(ROLE_AUTHOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> list[dict]:
    task = db.scalar(select(Task).where(Task.code == code))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    _require_manage(user, task)

    try:
        truths = json.loads(ground_truths)
    except json.JSONDecodeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ground_truths 不是合法 JSON：{e}") from e
    if not isinstance(truths, list) or len(truths) != len(files):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ground_truths 长度与文件数量不一致")
    if batch_index_start < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "batch_index_start 不能小于 0")
    if batch_size < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "batch_size 不能小于 0")

    note_list: list[str | None] = []
    if notes:
        try:
            parsed = json.loads(notes)
        except json.JSONDecodeError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"notes 不是合法 JSON：{e}") from e
        if not isinstance(parsed, list) or len(parsed) != len(files):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "notes 长度与文件数量不一致")
        note_list = [str(x) if x is not None else None for x in parsed]
    else:
        note_list = [None] * len(files)

    options = set(task.answer_options)
    for i, gt in enumerate(truths):
        if not isinstance(gt, str) or gt not in options:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"第 {i + 1} 张图的标准答案 '{gt}' 不在任务选项里",
            )

    # 计算下一组 order_index
    next_idx = (
        db.scalar(
            select(func.coalesce(func.max(Question.order_index), -1)).where(
                Question.task_id == task.id, Question.is_deleted == 0
            )
        )
        or -1
    )
    next_idx = int(next_idx) + 1

    created: list[Question] = []
    for i, (f, gt) in enumerate(zip(files, truths, strict=True)):
        absolute_idx = next_idx + i
        if batch_size:
            batch_index = batch_index_start + (absolute_idx // batch_size)
            batch_position = absolute_idx % batch_size
        else:
            batch_index = batch_index_start
            batch_position = absolute_idx
        rel_path, sha = store_upload(f)
        q = Question(
            task_id=task.id,
            image_path=rel_path,
            image_sha256=sha,
            ground_truth=gt,
            order_index=absolute_idx,
            batch_index=batch_index,
            batch_position=batch_position,
            note=note_list[i],
            uploaded_by=user.id,
            is_deleted=0,
        )
        db.add(q)
        created.append(q)
    db.commit()
    for q in created:
        db.refresh(q)
    return [_question_admin_dict(q) for q in created]


@questions_router.patch("/{question_id}", response_model=QuestionAdminPublic)
def update_question(
    question_id: int,
    payload: QuestionUpdate,
    user: User = Depends(require_role(ROLE_AUTHOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    q = db.get(Question, question_id)
    if q is None or q.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在")
    task = db.get(Task, q.task_id)
    _require_manage(user, task)

    if payload.ground_truth is not None:
        if payload.ground_truth not in set(task.answer_options):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "标准答案不在任务的选项列表里"
            )
        q.ground_truth = payload.ground_truth
    if payload.order_index is not None:
        q.order_index = int(payload.order_index)
    if payload.note is not None:
        q.note = payload.note
    db.commit()
    db.refresh(q)
    return _question_admin_dict(q)


@questions_router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(
    question_id: int,
    user: User = Depends(require_role(ROLE_AUTHOR, ROLE_ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    q = db.get(Question, question_id)
    if q is None or q.is_deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "题目不存在")
    task = db.get(Task, q.task_id)
    _require_manage(user, task)
    q.is_deleted = 1
    db.commit()


# ---------- 鉴权图片下发 ----------

@storage_router.get("/{image_path:path}")
def serve_image(image_path: str, _: User = Depends(get_current_user)) -> FileResponse:
    """登录用户才能拉图。M2 起替换 StaticFiles 直挂的 /storage。"""
    target = resolve_image_path(image_path)
    return FileResponse(target, media_type=media_type_of(target))
