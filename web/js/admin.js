// 平台管理：账号管理 + 判读记录筛选 + 数据导出
import { apiGet, apiPatch, fetchMe } from "./api.js";
import { bindAttemptDetailButtons, formatAuc } from "./admin_attempt_detail.js";

const $ = (id) => document.getElementById(id);

const ROLE_LABELS = { admin: "管理员", author: "任务管理员", doctor: "判读者" };
const STATUS_LABELS = { in_progress: "进行中", submitted: "已提交" };

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fmt(d) { return d ? new Date(d).toLocaleString("zh-CN", { hour12: false }) : "-"; }
function formatPercent(value) { return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "-"; }
function renderUserAgreement(user) {
  return user.total ? `${user.correct}/${user.total} (${formatPercent(user.accuracy)})` : "-";
}
function renderUserAuc(user) {
  if (typeof user.auc !== "number") return "-";
  return `${formatAuc(user.auc)}<span class="history-subtext">样本 ${user.auc_positive}/${user.auc_negative}</span>`;
}

let me = null;

async function ensureAdmin() {
  me = await fetchMe();
  if (!me) { window.location.href = "/login"; return false; }
  if (me.role !== "admin") {
    document.querySelector("main").innerHTML = `<section class="panel"><h2>权限不足</h2><p class="brand-copy">仅管理员可访问。</p></section>`;
    return false;
  }
  return true;
}

function bindTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const target = btn.dataset.tab;
      document.querySelectorAll(".tab-pane").forEach((p) => {
        p.classList.toggle("hidden", p.dataset.pane !== target);
      });
      if (target === "users") loadUsers();
      if (target === "attempts") loadAttempts();
    });
  });
}

// ---------- users ----------

async function loadUsers() {
  const root = $("users-root");
  try {
    const list = await apiGet("/api/admin/users");
    root.innerHTML = `
      <table class="history-table">
        <thead><tr><th>ID</th><th>用户名</th><th>显示名</th><th>角色</th><th>状态</th><th>已提交</th><th>整体一致性</th><th>整体AUC</th><th>注册</th><th></th></tr></thead>
        <tbody>${list.map((u) => `
          <tr>
            <td>${u.id}</td>
            <td>${escapeHtml(u.username)}</td>
            <td>${escapeHtml(u.display_name || "-")}</td>
            <td><span class="chip">${ROLE_LABELS[u.role] || u.role}</span></td>
            <td><span class="chip ${u.is_active ? "chip-success" : "chip-muted"}">${u.is_active ? "启用" : "停用"}</span></td>
            <td>${u.submitted_attempts || 0}</td>
            <td>${renderUserAgreement(u)}</td>
            <td>${renderUserAuc(u)}</td>
            <td>${fmt(u.created_at)}</td>
            <td><button class="btn" data-edit="${u.id}">编辑</button></td>
          </tr>
        `).join("")}</tbody>
      </table>`;
    root.querySelectorAll("button[data-edit]").forEach((b) => {
      b.addEventListener("click", () => openUserModal(list.find((x) => x.id === Number(b.dataset.edit))));
    });
  } catch (e) {
    root.innerHTML = `<p class="feedback" data-kind="error">${escapeHtml(e.message)}</p>`;
  }
}

function openUserModal(u) {
  $("modal-title").textContent = u.username;
  $("m-id").value = u.id;
  $("m-display").value = u.display_name || "";
  $("m-role").value = u.role;
  $("m-active").checked = !!u.is_active;
  $("m-password").value = "";
  $("modal-feedback").textContent = "";
  $("user-modal").classList.remove("hidden");
}

function bindUserModal() {
  $("modal-close").addEventListener("click", () => $("user-modal").classList.add("hidden"));
  $("user-modal").addEventListener("click", (e) => {
    if (e.target.id === "user-modal") $("user-modal").classList.add("hidden");
  });
  $("user-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = Number($("m-id").value);
    const payload = {
      role: $("m-role").value,
      is_active: $("m-active").checked ? 1 : 0,
      display_name: $("m-display").value || null,
    };
    const pw = $("m-password").value;
    if (pw) {
      if (pw.length < 6) { $("modal-feedback").textContent = "密码至少 6 位"; return; }
      payload.new_password = pw;
    }
    try {
      await apiPatch(`/api/admin/users/${id}`, payload);
      $("modal-feedback").dataset.kind = "success";
      $("modal-feedback").textContent = "已保存";
      await loadUsers();
      setTimeout(() => $("user-modal").classList.add("hidden"), 600);
    } catch (err) {
      $("modal-feedback").dataset.kind = "error";
      $("modal-feedback").textContent = err.message;
    }
  });
}

// ---------- attempts ----------

async function loadAttempts() {
  const params = new URLSearchParams();
  const tc = $("f-task").value.trim();
  const uid = $("f-user").value.trim();
  const st = $("f-status").value;
  if (tc) params.set("task_code", tc);
  if (uid) params.set("user_id", uid);
  if (st) params.set("status", st);
  const q = params.toString();
  const root = $("attempts-root");
  try {
    const list = await apiGet("/api/admin/attempts" + (q ? "?" + q : ""));
    if (!list.length) { root.innerHTML = `<p class="brand-copy">无结果</p>`; return; }
    root.innerHTML = `
      <table class="history-table">
        <thead><tr><th>ID</th><th>用户</th><th>研究任务</th><th>状态</th><th>参考一致性</th><th>AUC</th><th>开始</th><th>提交</th><th></th></tr></thead>
        <tbody>${list.map((a) => `
          <tr>
            <td>${a.id}</td>
            <td>${escapeHtml(a.username)}${a.display_name ? ` (${escapeHtml(a.display_name)})` : ""}</td>
            <td>${escapeHtml(a.task_name)} <code>${escapeHtml(a.task_code)}</code></td>
            <td><span class="chip ${a.status === "submitted" ? "chip-success" : "chip-muted"}">${STATUS_LABELS[a.status] || a.status}</span></td>
            <td>${a.score != null ? `${a.correct}/${a.total} (${(a.score * 100).toFixed(1)}%)` : "-"}</td>
            <td>${formatAuc(a.auc)}</td>
            <td>${fmt(a.started_at)}</td>
            <td>${fmt(a.submitted_at)}</td>
            <td><button class="btn" type="button" data-attempt-detail="${a.id}">查看</button></td>
          </tr>
        `).join("")}</tbody>
      </table>`;
    bindAttemptDetailButtons(root);
  } catch (e) {
    root.innerHTML = `<p class="feedback" data-kind="error">${escapeHtml(e.message)}</p>`;
  }
}

function bindFilter() {
  $("attempt-filter").addEventListener("submit", (e) => { e.preventDefault(); loadAttempts(); });
  $("reset-filter").addEventListener("click", () => {
    $("f-task").value = ""; $("f-user").value = ""; $("f-status").value = "";
    loadAttempts();
  });
}

(async function init() {
  if (!(await ensureAdmin())) return;
  bindTabs();
  bindUserModal();
  bindFilter();
  await loadUsers();
})();
