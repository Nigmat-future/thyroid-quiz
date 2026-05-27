// 研究任务图像集管理：上传图像 + 维护参考标准
import { api, apiGet, apiPatch, apiPost, apiDelete, fetchMe } from "./api.js";

const code = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
const $ = (id) => document.getElementById(id);

let task = null;       // TaskAdminPublic
let questions = [];    // QuestionAdminPublic[]
const pending = new Map();  // local-id -> { file, gt }
let pendingSeq = 0;

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

async function ensureAuthor() {
  const me = await fetchMe();
  if (!me) { window.location.href = "/login"; return null; }
  if (me.role !== "author" && me.role !== "admin") {
    document.querySelector("main").innerHTML = `<section class="panel"><h2>权限不足</h2></section>`;
    return null;
  }
  return me;
}

async function loadTask() {
  task = await apiGet(`/api/tasks/${encodeURIComponent(code)}/admin`);
  $("task-name").textContent = task.name;
  $("task-meta").innerHTML = `编码 <code>${escapeHtml(task.code)}</code> · ${task.n_questions} 张图像 · 判读选项 ${task.answer_options.map(escapeHtml).join(" / ")}`;
  const chip = $("publish-chip");
  chip.textContent = task.is_published ? "已发布" : "草稿";
  chip.className = "chip " + (task.is_published ? "chip-success" : "chip-muted");
}

async function loadQuestions() {
  questions = await apiGet(`/api/tasks/${encodeURIComponent(code)}/questions`);
  $("q-count").textContent = String(questions.length);
  if (!questions.length) {
    $("questions-list").innerHTML = `<p class="brand-copy">还没有图像，先在上方上传一些图像吧。</p>`;
    return;
  }
  const opts = task.answer_options;
  $("questions-list").innerHTML = questions.map((q) => `
    <article class="question-card" data-id="${q.id}">
      <img src="${escapeHtml(q.image_url)}" loading="lazy" alt="超声图像">
      <div class="question-card-body">
        <p class="eyebrow">第 ${q.order_index + 1} 张图像</p>
        <label class="field">
          <span>参考标准</span>
          <select data-role="gt">
            ${opts.map((o) => `<option value="${escapeHtml(o)}" ${o === q.ground_truth ? "selected" : ""}>${escapeHtml(o)}</option>`).join("")}
          </select>
        </label>
        <label class="field">
          <span>序号</span>
          <input type="number" data-role="order" value="${q.order_index}">
        </label>
        <label class="field">
          <span>备注</span>
          <input type="text" data-role="note" value="${escapeHtml(q.note ?? "")}">
        </label>
        <div class="actions">
          <button class="btn" data-role="save">保存</button>
          <button class="btn btn-danger" data-role="del">删除</button>
        </div>
        <p class="feedback" data-role="feedback"></p>
      </div>
    </article>`).join("");

  $("questions-list").querySelectorAll(".question-card").forEach((card) => {
    const id = Number(card.dataset.id);
    const fb = card.querySelector('[data-role="feedback"]');
    card.querySelector('[data-role="save"]').addEventListener("click", async () => {
      fb.textContent = "";
      try {
        await apiPatch(`/api/questions/${id}`, {
          ground_truth: card.querySelector('[data-role="gt"]').value,
          order_index: Number(card.querySelector('[data-role="order"]').value),
          note: card.querySelector('[data-role="note"]').value,
        });
        fb.dataset.kind = "success";
        fb.textContent = "已保存";
      } catch (e) { fb.dataset.kind = "error"; fb.textContent = e.message; }
    });
    card.querySelector('[data-role="del"]').addEventListener("click", async () => {
      if (!confirm("确认移除此图像？")) return;
      try {
        await apiDelete(`/api/questions/${id}`);
        await loadQuestions();
      } catch (e) { fb.dataset.kind = "error"; fb.textContent = e.message; }
    });
  });
}

function renderPending() {
  if (!task) return;
  const opts = task.answer_options;
  const root = $("pending-list");
  if (!pending.size) {
    root.innerHTML = "";
    $("upload-btn").disabled = true;
    $("clear-btn").disabled = true;
    return;
  }
  root.innerHTML = [...pending.entries()].map(([key, item]) => `
    <div class="pending-row" data-key="${key}">
      <img src="${URL.createObjectURL(item.file)}" alt="预览">
      <div class="pending-row-body">
        <strong>${escapeHtml(item.file.name)}</strong>
        <span class="brand-copy">${(item.file.size / 1024).toFixed(1)} KB</span>
        <select data-role="gt">
          ${opts.map((o) => `<option value="${escapeHtml(o)}" ${o === item.gt ? "selected" : ""}>${escapeHtml(o)}</option>`).join("")}
        </select>
      </div>
      <button class="btn" data-role="rm">移除</button>
    </div>
  `).join("");
  root.querySelectorAll(".pending-row").forEach((row) => {
    const key = row.dataset.key;
    row.querySelector('[data-role="gt"]').addEventListener("change", (e) => {
      pending.get(key).gt = e.target.value;
    });
    row.querySelector('[data-role="rm"]').addEventListener("click", () => {
      pending.delete(key);
      renderPending();
    });
  });
  $("upload-btn").disabled = false;
  $("clear-btn").disabled = false;
}

function addFiles(fileList) {
  if (!task) return;
  const defaultOpt = task.answer_options[0];
  for (const f of fileList) {
    if (!f.type.startsWith("image/")) continue;
    pending.set(`p${++pendingSeq}`, { file: f, gt: defaultOpt });
  }
  renderPending();
}

function bindUploadZone() {
  const zone = $("drop-zone");
  $("pick-btn").addEventListener("click", () => $("file-input").click());
  $("file-input").addEventListener("change", (e) => addFiles(e.target.files));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    addFiles(e.dataTransfer.files);
  });
  $("clear-btn").addEventListener("click", () => { pending.clear(); renderPending(); });
  $("upload-btn").addEventListener("click", doUpload);
  $("toggle-publish-btn").addEventListener("click", togglePublish);
}

async function doUpload() {
  setFeedback("upload-feedback", "");
  if (!pending.size) return;
  const fd = new FormData();
  const truths = [];
  for (const item of pending.values()) {
    fd.append("files", item.file);
    truths.push(item.gt);
  }
  fd.append("ground_truths", JSON.stringify(truths));

  $("upload-btn").disabled = true;
  try {
    const res = await fetch(`/api/tasks/${encodeURIComponent(code)}/questions/upload`, {
      method: "POST",
      credentials: "same-origin",
      body: fd,
    });
    if (!res.ok) {
      let msg = `上传失败 (${res.status})`;
      try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
      throw new Error(msg);
    }
    pending.clear();
    renderPending();
    setFeedback("upload-feedback", "图像上传完成", "success");
    await loadTask();
    await loadQuestions();
  } catch (err) {
    setFeedback("upload-feedback", err.message || "上传失败");
  } finally {
    $("upload-btn").disabled = pending.size === 0;
  }
}

async function togglePublish() {
  try {
    await apiPatch(`/api/tasks/${encodeURIComponent(code)}`, { is_published: !task.is_published });
    await loadTask();
  } catch (e) { alert(e.message); }
}

(async function init() {
  if (!(await ensureAuthor())) return;
  try {
    await loadTask();
    bindUploadZone();
    await loadQuestions();
  } catch (e) {
    document.querySelector("main").innerHTML = `<section class="panel"><h2>加载失败</h2><p>${escapeHtml(e.message)}</p></section>`;
  }
})();
