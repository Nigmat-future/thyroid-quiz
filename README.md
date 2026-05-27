# 甲状腺超声图像答题系统

面向医生的甲状腺超声图像在线答题平台。多套题库、真账号登录、题目上传与标准答案管理、答题计分与结果统计。

> 详细规格见 [`SPEC.md`](./SPEC.md)，部署见 [`DEPLOY.md`](./DEPLOY.md)。当前进度：**M0-M6 已完成**。

## 技术栈

- **后端**：Python 3.11 + FastAPI + SQLAlchemy 2.0 + Alembic + SQLite（可平迁 PostgreSQL）
- **前端**：原生 HTML / CSS / ES Module JS（不引前端框架）
- **鉴权**：starlette session middleware + bcrypt
- **存储**：本地文件系统（图片 sha256 命名去重）
- **部署**：Dockerfile + docker-compose；推荐 Railway / Fly.io / Render

## 本地开发

```powershell
# 1. 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 安装依赖（含开发工具）
pip install -e ".[dev]"

# 3. 复制环境变量并按需修改
Copy-Item .env.example .env

# 4. 跑迁移
alembic upgrade head

# 5. 创建初始管理员
python -m scripts.init_admin

# 6. 启动开发服务器
uvicorn app.main:app --reload
```

启动后访问：

- 首页：http://127.0.0.1:8000/
- API 文档：http://127.0.0.1:8000/api/docs
- Health：http://127.0.0.1:8000/api/health

## 测试

```powershell
ruff check app tests scripts
pytest -q
```

## Docker

```powershell
docker compose up --build
```

## 目录结构

```
app/                FastAPI 后端
  routers/          API 路由（按业务拆分）
  services/         业务服务层
alembic/            数据库迁移
web/                前端静态资源
storage/            上传图片（git 忽略）
data/               SQLite 文件（git 忽略）
scripts/            管理脚本
tests/              pytest
```

## 角色与权限

| 角色 | 权限 |
|---|---|
| `admin` | 全权 |
| `author` | 上传题、设答案、组织自己的任务 |
| `doctor` | 答题、看自己成绩 |

## 里程碑

- [x] **M0** 骨架：FastAPI + Docker + 健康检查
- [x] **M1** 鉴权：注册 / 登录 / 角色
- [x] **M2** 题库管理：上传图、设答案、任务 CRUD
- [x] **M3** 答题流程：自动保存、续答
- [x] **M4** 提交计分 + 结果页
- [x] **M5** admin 后台 + CSV 导出
- [x] **M6** 部署上线配置：GitHub Actions + Railway/Fly/Render 文档
