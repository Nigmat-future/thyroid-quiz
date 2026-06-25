// 任务管理员首页：新建任务 + 列出任务（自己 + 已发布）
import { apiGet, apiPost } from "./api.js";
import { requireLoggedInWithProfile } from "./profile.js";

const $ = (id) => document.getElementById(id);

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function setFeedback(id, text, kind = "error") {
  const el = $(id);
  if (!el) return;
  el.textContent = text || "";
  el.dataset.kind = kind;
}

function parseOptions(text) {
  return text
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

async function ensureAuthor() {
  const me = await requireLoggedInWithProfile();
  if (!me) return null;
  if (me.role !== "author" && me.role !== "admin") {
    document.querySelector("main").innerHTML = `
      <section class="panel">
        <h2>权限不足</h2>
        <p class="brand-copy">当前账号是 <strong>${escapeHtml(me.role)}</strong>，仅 author / admin 可访问研究任务工作台。</p>
        <p><a class="btn" href="/">返回首页</a></p>
      </section>`;
    return null;
  }
  return me;
}

async function loadTasks() {
  const root = $("tasks-list");
  try {
    const tasks = await apiGet("/api/tasks");
    if (!tasks.length) {
      root.innerHTML = `<p class="brand-copy">还没有任务。先在上方创建一个吧。</p>`;
      return;
    }
    root.innerHTML = tasks.map((t) => `
      <article class="task-card">
        <div class="task-card-head">
          <div>
            <p class="eyebrow">${escapeHtml(t.code)}</p>
            <h3>${escapeHtml(t.name)}</h3>
          </div>
          <span class="chip ${t.is_published ? "chip-success" : "chip-muted"}">${t.is_published ? "已发布" : "草稿"}</span>
        </div>
        ${t.description ? `<p class="brand-copy">${escapeHtml(t.description)}</p>` : ""}
        <p class="task-meta">判读选项：${t.answer_options.map(escapeHtml).join(" · ")}</p>
        <div class="actions">
          <a class="btn btn-primary" href="/author/tasks/${encodeURIComponent(t.code)}">管理图像</a>
        </div>
      </article>
    `).join("");
  } catch (e) {
    root.innerHTML = `<p class="feedback" data-kind="error">加载失败：${escapeHtml(e.message)}</p>`;
  }
}

function bindCreate() {
  const form = $("create-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setFeedback("create-feedback", "");
    const options = parseOptions($("options").value);
    if (options.length < 2) {
      setFeedback("create-feedback", "至少需要 2 个判读选项");
      return;
    }
    const payload = {
      code: $("code").value.trim(),
      name: $("name").value.trim(),
      description: $("description").value.trim() || null,
      answer_options: options,
      randomize_options: $("randomize").checked,
      is_published: $("published").checked,
    };
    $("create-btn").disabled = true;
    try {
      await apiPost("/api/tasks", payload);
      setFeedback("create-feedback", "创建成功，跳转中…", "success");
      window.location.href = `/author/tasks/${encodeURIComponent(payload.code)}`;
    } catch (err) {
      setFeedback("create-feedback", err.message || "创建失败");
      $("create-btn").disabled = false;
    }
  });
}

(async function init() {
  if (!(await ensureAuthor())) return;
  bindCreate();
  await loadTasks();
})();
