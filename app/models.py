"""SQLAlchemy ORM 模型。M1: User；M2: Task/Question；M3: Attempt/Answer。"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# 角色常量
ROLE_ADMIN = "admin"
ROLE_AUTHOR = "author"
ROLE_DOCTOR = "doctor"
ALL_ROLES = (ROLE_ADMIN, ROLE_AUTHOR, ROLE_DOCTOR)

# 职业阶段
CAREER_GRADUATE = "graduate"
CAREER_PRACTITIONER = "practitioner"
CAREER_OTHER = "other"
ALL_CAREER_STAGES = (CAREER_GRADUATE, CAREER_PRACTITIONER, CAREER_OTHER)

# Attempt 状态常量
STATUS_IN_PROGRESS = "in_progress"
STATUS_SUBMITTED = "submitted"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    work_hospital: Mapped[str | None] = mapped_column(String(256), nullable=True)
    career_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    career_stage_other: Mapped[str | None] = mapped_column(String(128), nullable=True)
    license_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    physician_title: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_DOCTOR)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    @property
    def profile_complete(self) -> bool:
        return bool(
            self.display_name
            and self.display_name.strip()
            and self.work_hospital
            and self.work_hospital.strip()
            and self.career_stage in ALL_CAREER_STAGES
            and (
                self.career_stage != CAREER_OTHER
                or bool(self.career_stage_other and self.career_stage_other.strip())
            )
            and self.license_years is not None
            and self.physician_title
            and self.physician_title.strip()
        )

    def __repr__(self) -> str:
        return f"<User {self.id} {self.username} role={self.role}>"


class Task(Base):
    """一组题（题库）。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_options_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    randomize_options: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    creator: Mapped[User] = relationship("User", foreign_keys=[created_by])
    questions: Mapped[list[Question]] = relationship(
        "Question", back_populates="task", cascade="all, delete-orphan"
    )

    @property
    def answer_options(self) -> list[str]:
        try:
            value = json.loads(self.answer_options_json)
            return [str(x) for x in value] if isinstance(value, list) else []
        except (ValueError, TypeError):
            return []

    @answer_options.setter
    def answer_options(self, options: list[str]) -> None:
        self.answer_options_json = json.dumps(list(options), ensure_ascii=False)


class Question(Base):
    """单题 = 单图。"""

    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=False, index=True
    )
    image_path: Mapped[str] = mapped_column(String(255), nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ground_truth: Mapped[str] = mapped_column(String(64), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    task: Mapped[Task] = relationship("Task", back_populates="questions")


class Attempt(Base):
    """一次答题会话。"""

    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_IN_PROGRESS
    )
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    task: Mapped[Task] = relationship("Task", foreign_keys=[task_id])
    answers: Mapped[list[Answer]] = relationship(
        "Answer", back_populates="attempt", cascade="all, delete-orphan"
    )


class Answer(Base):
    """单题作答。"""

    __tablename__ = "answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_q"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("questions.id"), nullable=False
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_flag: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_correct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    attempt: Mapped[Attempt] = relationship("Attempt", back_populates="answers")
    question: Mapped[Question] = relationship("Question", foreign_keys=[question_id])
