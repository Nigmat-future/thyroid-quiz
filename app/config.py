"""集中读取环境变量。所有运行时配置从这里取。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# session 签名密钥的占位默认值；生产环境必须覆盖，否则 Cookie 可被伪造。
DEFAULT_SECRET_KEY = "change-me-please-use-a-long-random-string"


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

    secret_key: str = DEFAULT_SECRET_KEY
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
    def has_insecure_secret_key(self) -> bool:
        """生产环境仍在用占位密钥 → 会话可被伪造，应拒绝启动。"""
        return self.is_production and self.secret_key == DEFAULT_SECRET_KEY

    @property
    def storage_images_dir(self) -> Path:
        return self.storage_dir / "images"


settings = Settings()

# 启动时确保关键目录存在
(PROJECT_ROOT / "data").mkdir(parents=True, exist_ok=True)
settings.storage_images_dir.mkdir(parents=True, exist_ok=True)
