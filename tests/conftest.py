"""Pytest 全局 fixture：把测试隔离到临时 SQLite + 独立 storage。

⚠️ 必须在 import app.* 之前注入环境变量，否则 settings 会读到真实 .env。
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# 1) 在导入任何 app 模块之前，先准备独立的临时目录与 env。
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="thyquiz_test_"))
_DB_PATH = _TEST_ROOT / "test.db"

os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["STORAGE_DIR"] = str(_TEST_ROOT / "storage")
os.environ["APP_ENV"] = "test"

# 2) 现在再导入 app，settings 会读到上面的 env。
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: F401, E402  确保模型注册到 Base
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

# 用 Base.metadata 直接建表（测试不跑 alembic，更快、更不脏）
Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _reset_db():
    """每个测试结束后清空所有表，互不干扰。"""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def client() -> TestClient:
    """全新 TestClient，cookie 不跨用例残留。"""
    return TestClient(app)


def pytest_sessionfinish(session, exitstatus):
    """跑完测试清掉临时目录。"""
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
