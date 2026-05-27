# 部署指南

> ⚠️ **GitHub Pages 跑不了 FastAPI**（Pages 只托管静态站）。本应用需要持久化的 Python 后端 + 文件存储 + SQLite。
> 推荐方案：**仓库托管 GitHub + 部署到免费 PaaS**（Railway / Fly.io / Render）。

---

## 0. 通用准备

把仓库推到 GitHub：

```powershell
cd F:\甲状腺Web

git init
git add .
git commit -m "init: 甲状腺超声答题系统"
git branch -M main

# 在 GitHub 网页建好空仓库后：
git remote add origin https://github.com/<你的用户名>/thyroid-quiz.git
git push -u origin main
```

GitHub Actions（`.github/workflows/ci.yml`）会自动跑 `ruff` + `pytest` + Docker 构建冒烟测试。

---

## 方案 A：Railway（最推荐 · 最简单）

**优点**：UI 友好、自动检测 Dockerfile、提供持久卷、HTTPS 子域名零配置。

1. 注册 https://railway.com，绑定 GitHub
2. **New Project → Deploy from GitHub repo → 选择 thyroid-quiz**
3. 部署完成后到项目 **Settings**：
   - **Volumes**：新建一个挂到 `/app/data`（存 SQLite + 图片）
   - **Variables**：
     ```
     SECRET_KEY = <openssl rand -hex 32 生成的随机串>
     APP_ENV = production
     DATABASE_URL = sqlite:////app/data/thyroid_quiz.db
     STORAGE_DIR = /app/data/storage
     INIT_ADMIN_USERNAME = admin
     INIT_ADMIN_PASSWORD = <强密码>
     ```
4. **Settings → Networking → Generate Domain**，得到形如 `thyroid-quiz-production.up.railway.app`
5. 首次部署后到 Railway shell 跑：
   ```bash
   python -m scripts.init_admin
   ```
   （或用 Railway 的 Run Command 功能）

`railway.json` 已配置 healthcheck = `/api/health` + 启动命令自动跑迁移。

---

## 方案 B：Fly.io（适合常驻 + 海外加速）

```bash
# 安装 flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly auth login

cd F:\甲状腺Web
fly launch --no-deploy   # 选 nrt 区域；它会按 fly.toml 创建 app

# 1GB 持久卷（够用很久）
fly volumes create thyroid_data --size 1 --region nrt

# 必备 secret
fly secrets set SECRET_KEY=$(openssl rand -hex 32)
fly secrets set INIT_ADMIN_USERNAME=admin INIT_ADMIN_PASSWORD=<强密码>

fly deploy

# 首次创建 admin
fly ssh console -C "python -m scripts.init_admin"
```

`fly.toml` 已配置 HTTPS 强制 + auto_stop（无人访问时停机省钱）。

---

## 方案 C：Render（免费层会休眠 30s 冷启动）

1. https://render.com → New → Web Service → 连 GitHub
2. **Environment**：Docker
3. **Build Command**：留空（用 Dockerfile）
4. **Start Command**：`alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Disks**：挂一块 1GB 到 `/app/data`
6. **Environment Variables**：同方案 A

---

## 方案 D：自有 VPS / 局域网（最自由）

```bash
# 服务器上：
git clone https://github.com/<你>/thyroid-quiz.git
cd thyroid-quiz
cp .env.example .env
# 编辑 .env，至少改 SECRET_KEY 和 INIT_ADMIN_PASSWORD

docker compose up -d
docker compose exec app python -m scripts.init_admin
```

前面套 nginx / Caddy 反代 + HTTPS 即可。

---

## 安全自检清单

- [ ] `SECRET_KEY` 是 32+ 字节随机串（**不能用默认值**）
- [ ] `INIT_ADMIN_PASSWORD` 已改，登录后立即在 admin 后台再改一次
- [ ] `APP_ENV=production`（启用 HTTPS-only cookie）
- [ ] HTTPS 已启用（PaaS 自动给 / VPS 自己装 Caddy）
- [ ] 持久卷已挂载 `/app/data`（重启后数据不丢）
- [ ] 注册策略：默认开放注册为 doctor；如需改为邀请制，编辑 `app/routers/auth.py` 的 `register` 路由

---

## 常见问题

**Q: 部署后图片传上去刷新就没了？**
A: 没挂持久卷。Docker 容器文件系统是临时的，必须挂 volume / disk 到 `/app/data`。

**Q: 为什么不用 GitHub Pages？**
A: Pages 只能跑静态文件。FastAPI 是 Python 服务，需要进程常驻 + 数据库 + 文件 IO。

**Q: SQLite 够用吗？**
A: 几十医生 × 几百题完全够。需要更大规模再切 PostgreSQL：把 `DATABASE_URL` 改成 `postgresql+psycopg://...` 即可，模型层零改动。
