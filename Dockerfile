FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 系统依赖：Pillow 需要的图像库 + git（部分包构建用）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo libpng16-16 libwebp7 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
# 解析依赖到 requirements 后安装；保持 pip 可缓存
RUN pip install --upgrade pip && \
    pip install \
        "fastapi>=0.115" \
        "uvicorn[standard]>=0.30" \
        "sqlalchemy>=2.0.30" \
        "alembic>=1.13" \
        "bcrypt>=4.2" \
        "itsdangerous>=2.2" \
        "python-multipart>=0.0.9" \
        "jinja2>=3.1" \
        "pydantic>=2.8" \
        "pydantic-settings>=2.4" \
        "python-dotenv>=1.0" \
        "pillow>=10.4"

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY web ./web
COPY scripts ./scripts

RUN mkdir -p /app/data /app/storage/images

EXPOSE 8000

# 启动：先跑迁移与 admin 初始化，再起服务
CMD ["sh", "-c", "if [ -f /data/images.tar.gz ]; then tar -xzf /data/images.tar.gz -C /data/ && rm -f /data/images.tar.gz && echo 'Images extracted from tar'; fi && alembic upgrade head && python -m scripts.init_admin && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
