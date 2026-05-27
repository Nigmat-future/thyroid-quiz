"""集中读取环境变量。所有运行时配置从这里取。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'thyroid_quiz.db'}"

    secret_key: str = "change-me-please-use-a-long-random-string"
    session_hours: int = 72

    storage_dir: Path = PROJECT_ROOT / "storage"
    max_upload_bytes: int = 20 * 1024 * 1024

    init_admin_username: str = "admin"
    init_admin_password: str = "admin123456"
    init_admin_display_name: str = "超级管理员"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def storage_images_dir(self) -> Path:
        return self.storage_dir / "images"


settings = Settings()

# 启动时确保关键目录存在
(PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
settings.storage_images_dir.mkdir(parents=True, exist_ok=True)
