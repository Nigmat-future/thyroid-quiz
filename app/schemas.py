"""Pydantic schemas — API 入参出参契约。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import ALL_CAREER_STAGES, CAREER_GRADUATE, CAREER_PRACTITIONER

# ===== Auth =====


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class UserProfileFields(BaseModel):
    display_name: str = Field(min_length=1, max_length=128)
    work_hospital: str = Field(min_length=1, max_length=256)
    physician_title: str = Field(min_length=1, max_length=64)
    career_stage: str = Field(min_length=1, max_length=32)
    license_years: int = Field(ge=0, le=80)

    @field_validator("display_name", "work_hospital", "physician_title")
    @classmethod
    def _strip_required_text(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("不可为空")
        return cleaned

    @field_validator("career_stage")
    @classmethod
    def _validate_career_stage(cls, v: str) -> str:
        if v not in ALL_CAREER_STAGES:
            raise ValueError(f"无效身份类型，应为 {CAREER_GRADUATE} 或 {CAREER_PRACTITIONER}")
        return v


class UserCreate(UserProfileFields):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None
    work_hospital: str | None
    physician_title: str | None
    career_stage: str | None
    license_years: int | None
    profile_complete: bool
    role: str
    is_active: int
    created_at: datetime


class UserProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    work_hospital: str | None = Field(default=None, min_length=1, max_length=256)
    physician_title: str | None = Field(default=None, min_length=1, max_length=64)
    career_stage: str | None = Field(default=None, min_length=1, max_length=32)
    license_years: int | None = Field(default=None, ge=0, le=80)

    @field_validator("display_name", "work_hospital", "physician_title")
    @classmethod
    def _strip_optional_text(cls, v: str | None) -> str | None:
        return _clean_text(v)

    @field_validator("career_stage")
    @classmethod
    def _validate_optional_career_stage(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALL_CAREER_STAGES:
            raise ValueError(f"无效身份类型，应为 {CAREER_GRADUATE} 或 {CAREER_PRACTITIONER}")
        return v


class AdminUserSummary(UserPublic):
    submitted_attempts: int = 0
    total: int = 0
    answered: int = 0
    correct: int = 0
    accuracy: float | None = None
    auc: float | None = None
    auc_positive: int = 0
    auc_negative: int = 0


# ===== Admin user mgmt =====


class UserAdminUpdate(BaseModel):
    role: str | None = None
    is_active: int | None = None
    new_password: str | None = Field(default=None, min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=128)
    work_hospital: str | None = Field(default=None, max_length=256)
    physician_title: str | None = Field(default=None, max_length=64)
    career_stage: str | None = Field(default=None, max_length=32)
    license_years: int | None = Field(default=None, ge=0, le=80)

    @field_validator("display_name", "work_hospital", "physician_title")
    @classmethod
    def _strip_admin_text(cls, v: str | None) -> str | None:
        return _clean_text(v)

    @field_validator("career_stage")
    @classmethod
    def _validate_admin_career_stage(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ALL_CAREER_STAGES:
            raise ValueError(f"无效身份类型，应为 {CAREER_GRADUATE} 或 {CAREER_PRACTITIONER}")
        return v


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


class AttemptResult(BaseModel):
    """医生提交后的完成度视图；不含标准答案、对错或正确率。"""

    id: int
    task_code: str
    task_name: str
    status: str
    batch_index: int = 0
    total: int
    answered: int
    submitted_at: datetime
    rows: list[AttemptResultRow]


class AttemptHistoryItem(BaseModel):
    """医生自己的答题历史；只展示完成进度。"""

    id: int
    task_code: str
    task_name: str
    status: str
    batch_index: int = 0
    batch_total: int = 1
    answered: int
    total: int
    started_at: datetime
    submitted_at: datetime | None


class AdminAttemptMetrics(BaseModel):
    total: int
    answered: int
    correct: int
    accuracy: float | None
    auc: float | None
    auc_positive: int
    auc_negative: int


class AdminAttemptDetailUser(BaseModel):
    id: int
    username: str
    display_name: str | None


class AdminAttemptDetailTask(BaseModel):
    id: int
    code: str
    name: str


class AdminAttemptDetailRow(BaseModel):
    question_id: int
    order_index: int
    batch_index: int = 0
    batch_position: int = 0
    image_url: str
    ground_truth: str
    answer_text: str
    note: str
    review_flag: bool
    time_spent_seconds: int
    is_correct: bool
    truth_binary: int | None
    doctor_malignancy_score: float | None
    source_center: str
    source_file_path: str


class AdminAttemptDetail(BaseModel):
    id: int
    user: AdminAttemptDetailUser
    task: AdminAttemptDetailTask
    status: str
    batch_index: int = 0
    score: float | None
    total: int | None
    correct: int | None
    started_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    metrics: AdminAttemptMetrics
    rows: list[AdminAttemptDetailRow]


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
    answered: int | None = None
    auc: float | None = None
    started_at: datetime
    submitted_at: datetime | None
