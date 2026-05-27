// 首页：登录态展示 + 研究任务列表 + 判读历史。
import { fetchMe, apiGet, apiPost } from "./api.js";

const $ = (id) => document.getElementById(id);

const ROLE_LABELS = { admin: "管理员", author: "任务管理员", doctor: "判读者" };
const STATUS_LABELS = { in_progress: "进行中", submitted: "已提交" };
const BATCH_STATUS_LABELS = { not_started: "未开始", in_progress: "进行中", submitted: "已提交" };
const BATCH_STATUS_CLASS = { not_started: "chip-muted", in_progress: "chip-warning", submitted: "chip-success" };

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fmt(d) {
  if (!d) return "-";
  return new Date(d).toLocaleString("zh-CN", { hour12: false });
}

async function startAttempt(code, batchIndex = null) {
  try {
    const payload = { task_code: code };
    if (batchIndex !== null && batchIndex !== undefined) {
      payload.batch_index = Number(batchIndex);
    }
    const a = await apiPost("/api/attempts", payload);
    window.location.href = `/quiz/${a.id}`;
  } catch (e) {
    alert(e.message || "无法开始判读");
  }
}

async function loadTaskBatches(task) {
  if (!task.is_published) return { batches: [], batchError: null };
  try {
    const batches = await apiGet(`/api/tasks/${encodeURIComponent(task.code)}/batches`);
    return { batches: Array.isArray(batches) ? batches : [], batchError: null };
  } catch (e) {
    if (e.status === 404) return { batches: [], batchError: null };
    return { batches: [], batchError: e };
  }
}

function renderBatchMeta(batch) {
  const pieces = [];
  if (batch.total !== undefined && batch.total !== null) {
    pieces.push(`${Number(batch.total)} 题`);
  }
  if (batch.status === "submitted") {
    pieces.push(`提交：${fmt(batch.submitted_at)}`);
  } else if (batch.status === "in_progress") {
    pieces.push(`开始：${fmt(batch.started_at)}`);
  }
  return pieces.length ? pieces.join(" · ") : "待开始";
}

function renderBatchAction(task, batch) {
  const status = batch.status || "not_started";
  const attemptId = batch.attempt_id;
  if (status === "submitted") {
    if (!attemptId) {
      return `<button class="btn" type="button" disabled>已提交</button>`;
    }
    return `<a class="btn" href="/result/${attemptId}">查看结果</a>`;
  }
  const label = status === "in_progress" ? "继续判读" : "开始判读";
  return `
    <button
      class="btn btn-primary"
      type="button"
      data-action="start-batch"
      data-code="${escapeHtml(task.code)}"
      data-batch-index="${Number(batch.batch_index || 0)}"
    >${label}</button>`;
}

function renderBatchList(task) {
  if (task.batchError) {
    return `<p class="feedback" data-kind="error">批次加载失败：${escapeHtml(task.batchError.message)}</p>`;
  }
  return `
    <div class="batch-list">
      ${task.batches.map((batch) => {
        const status = batch.status || "not_started";
        const label = batch.batch_label || `第 ${Number(batch.batch_index || 0) + 1} 批`;
        return `
          <div class="batch-row">
            <div class="batch-row-main">
              <div class="batch-row-title">
                <strong>${escapeHtml(label)}</strong>
                <span class="chip ${BATCH_STATUS_CLASS[status] || "chip-muted"}">${BATCH_STATUS_LABELS[status] || escapeHtml(status)}</span>
              </div>
              <p class="task-meta">${escapeHtml(renderBatchMeta(batch))}</p>
            </div>
            <div class="actions batch-actions">
              ${renderBatchAction(task, batch)}
            </div>
          </div>`;
      }).join("")}
    </div>`;
}

function renderTaskCard(task) {
  const hasBatchView = task.is_published && (Number(task.n_batches || 0) > 1 || task.batches.length > 1);
  const answerOptions = Array.isArray(task.answer_options) ? task.answer_options : [];
  const taskAction = hasBatchView
    ? renderBatchList(task)
    : `
      <div class="actions">
        <button class="btn btn-primary" data-action="start-task" data-code="${escapeHtml(task.code)}">${task.is_published ? "开始 / 续读" : "草稿（未开放）"}</button>
      </div>`;

  return `
    <article class="task-card ${hasBatchView ? "task-card-batched" : ""}">
      <div class="task-card-head">
        <div>
          <p class="eyebrow">${escapeHtml(task.code)}</p>
          <h3>${escapeHtml(task.name)}</h3>
        </div>
        <span class="chip ${task.is_published ? "chip-success" : "chip-muted"}">${task.is_published ? "已发布" : "草稿"}</span>
      </div>
      ${task.description ? `<p class="brand-copy">${escapeHtml(task.description)}</p>` : ""}
      <p class="task-meta">判读选项：${answerOptions.map(escapeHtml).join(" · ")}</p>
      ${taskAction}
    </article>`;
}

async function renderTasks() {
  const root = $("tasks-root");
  try {
    const tasks = await apiGet("/api/tasks");
    if (!tasks.length) {
      root.innerHTML = `<p class="brand-copy">暂无研究任务。</p>`;
      return;
    }
    const withBatches = await Promise.all(tasks.map(async (task) => {
      const { batches, batchError } = await loadTaskBatches(task);
      return { ...task, batches, batchError };
    }));
    root.innerHTML = withBatches.map(renderTaskCard).join("");
    root.querySelectorAll("button[data-action='start-task']").forEach((btn) => {
      btn.addEventListener("click", () => startAttempt(btn.dataset.code));
      if (btn.textContent.includes("草稿")) btn.disabled = true;
    });
    root.querySelectorAll("button[data-action='start-batch']").forEach((btn) => {
      btn.addEventListener("click", () => startAttempt(btn.dataset.code, btn.dataset.batchIndex));
    });
  } catch (e) {
    root.innerHTML = `<p class="feedback" data-kind="error">加载失败：${escapeHtml(e.message)}</p>`;
  }
}

function historyTaskLabel(attempt) {
  const parts = [escapeHtml(attempt.task_name)];
  const hasBatchLabel = attempt.batch_label || Number(attempt.batch_total || 0) > 1 || Number(attempt.batch_index || 0) > 0;
  if (hasBatchLabel) {
    const label = attempt.batch_label || `第 ${Number(attempt.batch_index || 0) + 1} 批`;
    parts.push(`<span class="history-subtext">${escapeHtml(label)}</span>`);
  }
  return parts.join("");
}

async function renderHistory() {
  const root = $("history-root");
  try {
    const list = await apiGet("/api/attempts");
    if (!list.length) {
      root.innerHTML = `<p class="brand-copy">还没有判读记录。</p>`;
      return;
    }
    root.innerHTML = `
      <table class="history-table">
        <thead><tr><th>研究任务</th><th>状态</th><th>参考一致性</th><th>开始</th><th>提交</th><th></th></tr></thead>
        <tbody>${list.map((a) => `
          <tr>
            <td>${historyTaskLabel(a)}</td>
            <td><span class="chip ${a.status === "submitted" ? "chip-success" : "chip-muted"}">${STATUS_LABELS[a.status] || a.status}</span></td>
            <td>${a.status === "submitted" ? `${a.correct}/${a.total} (${(a.score * 100).toFixed(1)}%)` : "-"}</td>
            <td>${fmt(a.started_at)}</td>
            <td>${fmt(a.submitted_at)}</td>
            <td><a class="btn" href="${a.status === "submitted" ? `/result/${a.id}` : `/quiz/${a.id}`}">${a.status === "submitted" ? "查看结果" : "继续判读"}</a></td>
          </tr>
        `).join("")}</tbody>
      </table>`;
  } catch (e) {
    root.innerHTML = `<p class="feedback" data-kind="error">加载失败：${escapeHtml(e.message)}</p>`;
  }
}

async function render() {
  const me = await fetchMe();
  if (!me) {
    $("auth-state").innerHTML = `
      <p class="brand-copy">还未登录。</p>
      <div class="actions">
        <a href="/login" class="btn btn-primary">去登录</a>
        <a href="/register" class="btn">注册新账号</a>
      </div>`;
    $("body-after-auth").classList.add("hidden");
    return;
  }

  const roleLabel = ROLE_LABELS[me.role] || me.role;
  $("auth-state").innerHTML = `
    <div class="user-card">
      <div>
        <p class="eyebrow">已登录</p>
        <h2>${escapeHtml(me.display_name || me.username)} <span class="chip">${roleLabel}</span></h2>
        <p class="brand-copy">用户名：<code>${escapeHtml(me.username)}</code></p>
      </div>
      <div class="actions">
        ${me.role === "admin" ? `<a class="btn" href="/admin">平台管理中心</a>` : ""}
        ${me.role !== "doctor" ? `<a class="btn" href="/author">研究任务工作台</a>` : ""}
        <button type="button" class="btn" id="logout-btn">退出登录</button>
      </div>
    </div>`;
  $("logout-btn").addEventListener("click", async () => {
    await apiPost("/api/auth/logout");
    window.location.reload();
  });

  $("body-after-auth").classList.remove("hidden");
  await renderTasks();
  await renderHistory();
}

render().catch((e) => {
  $("auth-state").textContent = "加载失败：" + (e?.message || e);
});
