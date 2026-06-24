"""Admin-facing API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas import UserPublic


class AdminPerformanceMetrics(BaseModel):
    total: int
    answered: int
    correct: int
    accuracy: float | None
    auc: float | None
    auc_positive: int
    auc_negative: int
    uncertain: int
    ppv: float | None
    npv: float | None
    sensitivity: float | None
    specificity: float | None


class AdminUserSummary(UserPublic):
    submitted_attempts: int = 0
    in_progress_attempts: int = 0
    submitted_answered: int = 0
    in_progress_answered: int = 0
    total: int = 0
    answered: int = 0
    correct: int = 0
    accuracy: float | None = None
    auc: float | None = None
    auc_positive: int = 0
    auc_negative: int = 0
    uncertain: int = 0
    ppv: float | None = None
    npv: float | None = None
    sensitivity: float | None = None
    specificity: float | None = None


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


class AdminAttemptUserSummary(BaseModel):
    user_id: int
    username: str
    display_name: str | None
    submitted_attempts: int = 0
    in_progress_attempts: int = 0
    submitted_answered: int = 0
    in_progress_answered: int = 0
    total: int = 0
    answered: int = 0
    correct: int = 0
    accuracy: float | None = None
    auc: float | None = None
    auc_positive: int = 0
    auc_negative: int = 0
    uncertain: int = 0
    ppv: float | None = None
    npv: float | None = None
    sensitivity: float | None = None
    specificity: float | None = None


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
    metrics: AdminPerformanceMetrics
    rows: list[AdminAttemptDetailRow]
