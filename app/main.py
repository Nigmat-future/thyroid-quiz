"""FastAPI 入口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import PROJECT_ROOT, settings
from app.routers.admin import admin_router
from app.routers.attempts import attempts_router
from app.routers.auth import auth_router, me_router
from app.routers.tasks import questions_router, storage_router, tasks_router

WEB_ROOT: Path = PROJECT_ROOT / "web"


def create_app() -> FastAPI:
    app = FastAPI(
        title="甲状腺超声图像答题系统",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="thyquiz_session",
        max_age=settings.session_hours * 3600,
        https_only=settings.is_production,
        same_site="lax",
    )

    @app.get("/api/health", tags=["health"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": "0.1.0", "env": settings.app_env})

    # 业务路由
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(tasks_router)
    app.include_router(questions_router)
    app.include_router(attempts_router)
    app.include_router(admin_router)
    app.include_router(storage_router)  # 鉴权图片下发

    # 静态前端资源 —— web/ 下 css / js / html
    if WEB_ROOT.exists():
        app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")

    # 页面
    def _page(name: str):
        async def _serve() -> FileResponse:
            return FileResponse(WEB_ROOT / name)

        return _serve

    app.add_api_route("/", _page("index.html"), include_in_schema=False, methods=["GET"])
    app.add_api_route("/login", _page("login.html"), include_in_schema=False, methods=["GET"])
    app.add_api_route(
        "/register", _page("register.html"), include_in_schema=False, methods=["GET"]
    )
    app.add_api_route("/author", _page("author.html"), include_in_schema=False, methods=["GET"])
    app.add_api_route(
        "/author/tasks/{code}",
        _page("author_task.html"),
        include_in_schema=False,
        methods=["GET"],
    )
    app.add_api_route("/admin", _page("admin.html"), include_in_schema=False, methods=["GET"])

    # 答题页 + 结果页
    app.add_api_route(
        "/quiz/{attempt_id}", _page("quiz.html"), include_in_schema=False, methods=["GET"]
    )
    app.add_api_route(
        "/result/{attempt_id}", _page("result.html"), include_in_schema=False, methods=["GET"]
    )

    return app


app = create_app()
