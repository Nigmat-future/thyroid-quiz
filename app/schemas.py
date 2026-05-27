"""Pydantic schemas — API 入参出参契约。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ===== Auth =====

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)


class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None
    role: str
    is_active: int
    created_at: datetime


# ===== Admin user mgmt =====

class UserAdminUpdate(BaseModel):
    role: str | None = None
    is_active: int | None = None
    new_password: str | None = Field(default=None, min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)


# ===== Tasks =====

class TaskCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    answer_options: list[str] = Field(min_length=2, max_length=20)
    randomize_options: bool = False
    is_published: bool = False

    @field_validator("answer_options")
    @classmethod
    def _options_unique_nonempty(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v]
        if any(not s for s in cleaned):
            raise ValueError("答案选项不可为空字符串")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("答案选项不能重复")
        return cleaned


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    answer_options: list[str] | None = Field(default=None, min_length=2, max_length=20)
    randomize_options: bool | None = None
    is_published: bool | None = None


class TaskPublic(BaseModel):
    """暴露给医生的任务字段；不含未发布任务。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    answer_options: list[str]
    randomize_options: bool
    is_published: bool
    n_questions: int = 0
    n_batches: int = 1


class TaskAdminPublic(TaskPublic):
    """author/admin 视角，含创建人 + 计数。"""

    created_by: int
    created_at: datetime
    updated_at: datetime
    n_questions: int = 0


# ===== Questions =====

class QuestionUpdate(BaseModel):
    ground_truth: str | None = None
    order_index: int | None = None
    note: str | None = None


class QuestionPublic(BaseModel):
    """医生视角；不含 ground_truth。"""

    id: int
    image_url: str
    order_index: int
    batch_index: int = 0
    batch_position: int = 0
    note: str | None = None


class QuestionAdminPublic(BaseModel):
    """author/admin 视角；含 ground_truth。"""

    id: int
    task_id: int
    image_url: str
    image_sha256: str
    ground_truth: str
    order_index: int
    batch_index: int = 0
    batch_position: int = 0
    note: str | None
    uploaded_by: int
    created_at: datetime


# ===== Attempts =====

class AttemptCreate(BaseModel):
    task_code: str = Field(min_length=1, max_length=64)
    batch_index: int | None = Field(default=None, ge=0)


class AnswerInput(BaseModel):
    answer_text: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=2000)
    review_flag: bool = False
    time_spent_seconds: int = Field(default=0, ge=0)


class AnswerSnapshot(BaseModel):
    """attempt 详情里的单题答案。"""

    question_id: int
    answer_text: str
    note: str
    review_flag: bool = False
    time_spent_seconds: int = 0
    updated_at: datetime


class AttemptInProgress(BaseModel):
    """医生正在答题时的视图：题目列表（无 ground_truth）+ 已存答案。"""

    id: int
    task_code: str
    task_name: str
    answer_options: list[str]
    status: str
    batch_index: int = 0
    batch_total: int = 1
    started_at: datetime
    updated_at: datetime
    questions: list[QuestionPublic]
    answers: list[AnswerSnapshot]


class AttemptResultRow(BaseModel):
    question_id: int
    image_url: str
    order_index: int
    batch_index: int = 0
    batch_position: int = 0
    answer_text: str
    note: str
    review_flag: bool = False
    time_spent_seconds: int = 0
    ground_truth: str
    is_correct: bool


class AttemptResult(BaseModel):
    id: int
    task_code: str
    task_name: str
    status: str
    batch_index: int = 0
    score: float
    total: int
    correct: int
    submitted_at: datetime
    rows: list[AttemptResultRow]


class AttemptSummary(BaseModel):
    """admin 视角的 attempt 摘要。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    username: str
    display_name: str | None
    task_id: int
    task_code: str
    task_name: str
    status: str
    batch_index: int = 0
    score: float | None
    total: int | None
    correct: int | None
    started_at: datetime
    submitted_at: datetime | None
