# 甲状腺超声图像答题系统 — 项目规格说明（SPEC v0.1）

> 状态：**待用户审阅** · 日期：2026-05-08 · 参考项目：`F:\淋巴瘤\LymphomaClassifier\web\doctor_quiz`

本文档先定边界、后写代码。所有未在本文中明确写出的功能，默认视为 **out of scope**。

---

## 1. 项目目标

一句话：**面向医生的甲状腺超声图像在线答题平台**，支持多套题库、真账号登录、题目上传与标准答案管理、答题计分与结果统计。

非目标（明确不做）：
- ❌ 不做 AI 自动诊断、不集成模型推理
- ❌ 不做实时多人协作 / IM
- ❌ 不做移动端原生 App（仅响应式 Web）
- ❌ 不做 DICOM / 影像 PACS 对接（图片以 JPG/PNG 形式上传）
- ❌ 不做支付 / 订阅

---

## 2. 用户角色与权限

| 角色 | 中文 | 权限范围 |
|---|---|---|
| `admin` | 管理员（你本人） | 全权：用户管理、题库管理、上传图、看所有结果、导出数据、改任何账号密码与角色 |
| `author` | 出题人 | 上传图片、为图片设标准答案、组织题库（创建/编辑任务）、查看所属任务的答题统计 |
| `doctor` | 医生 | 注册/登录、选择任务答题、查看自己的提交历史与得分 |

**升级规则**：仅 `admin` 可以把 `doctor` 提升为 `author` 或 `admin`。

**注册策略**（拟定，待确认）：
- 默认策略：**开放注册为 `doctor`**，注册后即可登录答题
- `author` / `admin` 必须由现有 `admin` 在后台手动赋权

---

## 3. 功能范围（In Scope）

### 3.1 账号系统
- 用户名 + 密码注册（密码 bcrypt 哈希）
- 登录后下发 session cookie（HTTPOnly、SameSite=Lax）
- 找回密码：**v0.1 不做**，由 admin 后台直接重置密码代替
- 个人资料：显示名、所属机构（可选）

### 3.2 题库与图片管理（author / admin）
- **任务（Task）**：一组题的集合。例：「甲状腺良恶性二分类 v1」「TI-RADS 分级 v1」
  - 字段：code（slug，URL 用）、name、description、答案选项 JSON（如 `["良性","恶性"]`）、是否对医生开放、created_by
- **题目（Question）**：1 题 = 1 张图
  - 字段：所属 task、image_path（服务器存储路径）、ground_truth（必须是 task 答案选项之一）、order_index、备注、uploaded_by
- 上传：拖拽 / 多选批量上传；上传时为每张图选答案，或上传后在列表里逐张设
- 编辑：可改答案、改顺序、删除（删除会软删除，避免影响已交卷的统计）

### 3.3 答题流程（doctor）
- 进入首页 → 选任务 → 进入答题页
- 一次进入一个任务 = 一个 **attempt**；同一任务未提交时再次进入自动续答
- 答题页：
  - 大图展示（支持 lightbox 放大）
  - 答案选项按 task 配置渲染（单选）
  - 备注框（可选）
  - 题号导航：已答 / 当前 / 未答 三态
  - 自动保存：每次答案变化或翻题前异步落库
- 提交（一次性、不可撤回）→ 跳转结果页

### 3.4 结果与计分
- 提交后立即计分：`score = 答对数 / 总题数`
- 医生在结果页可见：总分、每题对错、自己的答案 vs 标准答案、自己的备注
- **答题过程中不显示标准答案**（防作弊，与参考项目一致）
- 结果一旦提交，attempt 锁定不可改

### 3.5 后台（admin）
- 用户列表 / 改角色 / 重置密码 / 禁用账号
- 任务列表 / 查看每任务的答题人数与平均分
- 全部 attempt 列表（按医生、任务筛选）
- 单个 attempt 详情（看每题作答）
- CSV 导出：attempts 总览 + 逐题答案

### 3.6 出题人后台（author）
- 跟 admin 题库管理一致，但只能管 **自己创建的 task**
- 看自己 task 下的答题统计

---

## 4. 数据模型（SQLite，初期；后期可平迁 PostgreSQL）

```sql
-- 用户
users (
  id INTEGER PK,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name TEXT,
  role TEXT NOT NULL CHECK(role IN ('admin','author','doctor')),
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
)

-- 会话（也可以用 itsdangerous 签名 cookie，无需此表）
sessions (
  token TEXT PK,
  user_id INTEGER NOT NULL REFERENCES users(id),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
)

-- 任务（题库）
tasks (
  id INTEGER PK,
  code TEXT UNIQUE NOT NULL,                -- URL slug
  name TEXT NOT NULL,
  description TEXT,
  answer_options_json TEXT NOT NULL,        -- e.g. '["良性","恶性"]'
  is_published INTEGER NOT NULL DEFAULT 0,  -- 1=对医生开放
  created_by INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)

-- 题目
questions (
  id INTEGER PK,
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  image_path TEXT NOT NULL,                 -- 相对 storage 根的路径
  image_sha256 TEXT NOT NULL,               -- 去重
  ground_truth TEXT NOT NULL,               -- 必须 ∈ answer_options_json
  order_index INTEGER NOT NULL,
  note TEXT,
  uploaded_by INTEGER NOT NULL REFERENCES users(id),
  is_deleted INTEGER NOT NULL DEFAULT 0,    -- 软删
  created_at TEXT NOT NULL
)

-- 答题会话（一次进入 = 一条 attempt）
attempts (
  id INTEGER PK,
  user_id INTEGER NOT NULL REFERENCES users(id),
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  status TEXT NOT NULL CHECK(status IN ('in_progress','submitted')) DEFAULT 'in_progress',
  score REAL,                                -- 提交时计算
  total INTEGER,                             -- 提交时快照题目数
  correct INTEGER,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  submitted_at TEXT
)

-- 单题作答
answers (
  id INTEGER PK,
  attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES questions(id),
  answer_text TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  is_correct INTEGER,                        -- 提交时回填
  updated_at TEXT NOT NULL,
  UNIQUE(attempt_id, question_id)
)
```

---

## 5. API 设计（REST，全部 `/api/*`，JSON）

### 鉴权
- `POST /api/auth/register` `{username, password, display_name?}` → 自动登录
- `POST /api/auth/login` `{username, password}` → set-cookie
- `POST /api/auth/logout`
- `GET  /api/me`

### 任务（公开）
- `GET  /api/tasks` 已发布任务列表（doctor 视角）
- `GET  /api/tasks/{code}` 含题目数、选项

### 答题（doctor）
- `POST /api/attempts` `{task_code}` → 创建或恢复 in_progress
- `GET  /api/attempts/{id}` 含题目列表（不含 ground_truth）+ 已答快照
- `PUT  /api/attempts/{id}/answers/{question_id}` `{answer_text, note}`
- `POST /api/attempts/{id}/submit` → 计分并锁定
- `GET  /api/attempts/{id}/result` 已提交后才可见，含每题对错与正解

### 题库管理（author / admin）
- `POST   /api/tasks` 创建
- `PATCH  /api/tasks/{code}`
- `POST   /api/tasks/{code}/questions/upload` multipart：批量图 + JSON 元数据
- `GET    /api/tasks/{code}/questions` 含 ground_truth
- `PATCH  /api/questions/{id}`
- `DELETE /api/questions/{id}` 软删

### 后台（admin）
- `GET    /api/admin/users`
- `PATCH  /api/admin/users/{id}` 改角色 / 重置密码 / 启用禁用
- `GET    /api/admin/attempts?task=&user=`
- `GET    /api/admin/attempts/{id}`
- `GET    /api/admin/exports/attempts.csv`

### 静态图片
- `GET /storage/{image_path}` 仅登录用户可访问（doctor 也行，因为图本身就是题目）

---

## 6. 前端页面

| 路径 | 角色 | 说明 |
|---|---|---|
| `/login` | 公开 | 登录 |
| `/register` | 公开 | 注册（默认 doctor） |
| `/` | doctor+ | 任务列表，每个卡片显示题数、自己最近成绩 |
| `/quiz/{attempt_id}` | doctor+ | 答题主界面（主体复刻参考项目 UI） |
| `/result/{attempt_id}` | doctor+ | 提交后看分数与逐题对错 |
| `/author` | author+ | 出题人后台：我的任务列表 |
| `/author/tasks/{code}` | author+ | 单个任务的题目管理 + 上传 |
| `/admin` | admin | 用户管理 + 全局结果 + 导出 |

UI 风格：采用克制的医疗/科研工作台语言（浅色底、低饱和青绿、清晰边框、表格化信息密度），避免蓝紫渐变、光晕和模板化玻璃拟态。

---

## 7. 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| 后端 | **Python 3.11 + FastAPI + SQLAlchemy 2.0 + Alembic** | API 自动文档（/docs）方便调试 |
| 鉴权 | **starlette session middleware + bcrypt** | session cookie，简单够用 |
| 文件存储 | 本地文件系统 `storage/` | 图片走 sha256 命名避免重复 |
| 数据库 | SQLite（开发&小规模） | 留好 PostgreSQL 切换路径（DATABASE_URL 环境变量） |
| 前端 | **原生 HTML + CSS + ES Modules JS** | 不引前端框架，跟参考一致 |
| 模板 | Jinja2（仅做 HTML 骨架注入） | 业务逻辑全在前端 fetch + DOM |
| 打包 | 不打包；FastAPI `StaticFiles` 直挂 `web/` | 前端零构建 |
| 容器 | Dockerfile + docker-compose.yml | 部署用 |

---

## 8. 目录结构

```
F:\甲状腺Web\
├── SPEC.md                       ← 本文件
├── README.md
├── pyproject.toml                ← 依赖
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── alembic/                      ← 迁移
│   └── versions/
├── app/                          ← FastAPI 后端
│   ├── __init__.py
│   ├── main.py                   ← FastAPI 入口
│   ├── config.py
│   ├── db.py
│   ├── models.py                 ← SQLAlchemy 模型
│   ├── schemas.py                ← Pydantic
│   ├── auth.py                   ← 鉴权依赖
│   ├── routers/
│   │   ├── auth.py
│   │   ├── tasks.py
│   │   ├── attempts.py
│   │   ├── questions.py
│   │   └── admin.py
│   └── services/
│       ├── scoring.py
│       └── storage.py
├── web/                          ← 前端静态资源
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── quiz.html
│   ├── result.html
│   ├── author.html
│   ├── admin.html
│   ├── styles.css
│   ├── styles/                   ← 拆分的 css
│   ├── js/
│   │   ├── api.js                ← fetch 封装
│   │   ├── auth.js
│   │   ├── quiz.js
│   │   ├── author.js
│   │   └── admin.js
│   └── assets/
├── storage/                      ← 上传图，git 忽略
│   └── images/
├── data/
│   └── thyroid_quiz.db           ← SQLite，git 忽略
├── scripts/
│   ├── init_admin.py             ← 初始化 admin 账号
│   └── seed_demo.py              ← 灌测试数据
└── tests/
    ├── test_auth.py
    ├── test_attempts.py
    └── test_scoring.py
```

---

## 9. 部署方案

> 你说"用 GitHub"。**注意**：GitHub Pages 只能托管静态站，**跑不了 FastAPI 后端**。所以方案是：

**仓库托管 GitHub + 部署到免费 PaaS**，推荐顺序：

1. **Railway**（推荐，最简单）
   - 连 GitHub 仓库 → 自动检测 Dockerfile → 部署
   - 提供持久卷（存 SQLite + 图片）
   - 免费额度：每月 $5 credit
2. **Fly.io**
   - 也支持 Dockerfile + 持久卷（Volumes）
   - 免费额度：3 个 256MB 小机器
3. **Render**
   - 支持 Web Service + Disk
   - 免费层会休眠（首次访问慢 30s）

GitHub 部分：
- `main` 分支推送 → CI（pytest + ruff） → 部署平台自动 redeploy
- GitHub Actions 跑测试 + 构建 Docker 镜像（可选推到 GHCR）

域名 + HTTPS：上述 PaaS 都自带 `*.up.railway.app` / `*.fly.dev` 子域名 + HTTPS 证书，零配置。后期可绑自有域名。

---

## 10. 开发里程碑

| 里程碑 | 内容 | 交付物 |
|---|---|---|
| **M0 骨架** | 项目脚手架、依赖、Docker、health check | 能 docker-compose up 跑出 200 OK |
| **M1 鉴权** | users 表、注册登录登出、session、role 装饰器 | 三角色登录跑通 |
| **M2 题库 CRUD** | tasks/questions 表、上传图片接口、author 后台页 | admin 能传图建任务 |
| **M3 答题** | attempts/answers、答题页、自动保存、续答 | doctor 能完整答题 |
| **M4 提交计分** | 计分逻辑、结果页、锁定 | 提交后能看分数 |
| **M5 后台** | admin 用户管理、attempt 浏览、CSV 导出 | admin 后台完整 |
| **M6 部署** | GitHub repo、Dockerfile 调优、Railway 上线 | 公网可访问 URL |

---

## 11. 待确认 / 需要你决定的开放问题

1. **注册策略**：默认开放 doctor 注册？还是必须 admin 邀请码？（我倾向开放注册）
2. **答题选项展示顺序**：固定 vs 随机化（防记答案位置）？
3. **图片删除策略**：软删还是硬删？已交卷的 attempt 看历史时若题目被删，怎么显示？
4. **导出粒度**：CSV 导出是每行一个 attempt 总览，还是每行一题一答？（我倾向都给）
5. **首次部署**：要不要我顺手帮你 `git init` + 推到 GitHub？（需要你提前建好空仓库 / 给我授权）

---

> **审阅完毕、确认开干？告诉我「spec OK」我就按 M0→M6 顺序开搞。**
> **要改什么直接说改哪条，我更新 SPEC 再动手。**
