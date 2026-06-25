// 平台管理：账号管理 + 判读记录筛选 + 数据导出
import { apiGet, apiPatch, fetchMe } from "./api.js";
import { bindAttemptDetailButtons, formatAuc } from "./admin_attempt_detail.js";

const $ = (id) => document.getElementById(id);

const ROLE_LABELS = { admin: "管理员", author: "任务管理员", doctor: "判读者" };
const CAREER_LABELS = { graduate: "研究生", practitioner: "已入职大夫" };
const STATUS_LABELS = { in_progress: "进行中", submitted: "已提交" };

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fmt(d) { return d ? new Date(d).toLocaleString("zh-CN", { hour12: false }) : "-"; }
function formatPercent(value) { return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "-"; }
function formatAgreement(item) {
  return item.answered ? `${item.correct}/${item.answered} (${formatPercent(item.accuracy)})` : "-";
}
function renderMetricLines(lines) {
  return `<div class="metric-stack">${lines.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${value}</strong></div>
  `).join("")}</div>`;
}
function renderUserCoreMetrics(user) {
  return renderMetricLines([
    ["整体AUC", formatAuc(user.auc)],
    ["Accuracy", formatAgreement(user)],
    ["不确定", `${user.uncertain || 0}`],
  ]);
}
function renderUserDiagnosticMetrics(user) {
  return renderMetricLines([
    ["NPV", formatPercent(user.npv)],
    ["PPV", formatPercent(user.ppv)],
    ["Sensitivity", formatPercent(user.sensitivity)],
    ["Specificity", formatPercent(user.specificity)],
  ]);
}
function renderUserProgress(user) {
  return renderMetricLines([
    ["已提交尝试", `${user.submitted_attempts || 0}`],
    ["已提交已答", `${user.submitted_answered || 0} 题`],
    ["进行中已答", `${user.in_progress_answered || 0} 题`],
  ]);
}
function renderAttemptAgreement(attempt) {
  if (!attempt.answered) return "-";
  return `${attempt.correct}/${attempt.answered} (${formatPercent(attempt.score)})`
    + `<span class="history-subtext">已答 ${attempt.answered}/${attempt.total || 0}</span>`;
}
function renderAttemptSummaryTable(list) {
  if (!list.length) return `<p class="brand-copy">当前筛选下暂无用户汇总。</p>`;
  return `
    <div class="summary-block">
      <div class="panel-head summary-head">
        <div><p class="eyebrow">当前筛选汇总</p><h3>按用户查看</h3></div>
      </div>
      <table class="history-table summary-table">
        <thead><tr><th>用户</th><th>Accuracy</th><th>AUC</th><th>NPV</th><th>PPV</th><th>Sensitivity</th><th>Specificity</th><th>已提交已答</th><th>进行中已答</th><th>不确定</th></tr></thead>
        <tbody>${list.map((user) => `
          <tr>
            <td>${escapeHtml(user.username)}${user.display_name ? `<span class="history-subtext">${escapeHtml(user.display_name)}</span>` : ""}${user.work_hospital ? `<span class="history-subtext">${escapeHtml(user.work_hospital)}</span>` : ""}${user.physician_title ? `<span class="history-subtext">${escapeHtml(user.physician_title)}</span>` : ""}${user.career_stage ? `<span class="history-subtext">${escapeHtml(CAREER_LABELS[user.career_stage] || user.career_stage)}</span>` : ""}</td>
            <td>${formatAgreement(user)}</td>
            <td>${formatAuc(user.auc)}</td>
            <td>${formatPercent(user.npv)}</td>
            <td>${formatPercent(user.ppv)}</td>
            <td>${formatPercent(user.sensitivity)}</td>
            <td>${formatPercent(user.specificity)}</td>
            <td>${user.submitted_answered || 0}</td>
            <td>${user.in_progress_answered || 0}</td>
            <td>${user.uncertain || 0}</td>
          </tr>
        `).join("")}</tbody>
      </table>
    </div>`;
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
      document.querySelectorAll(".tab-pane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== target));
      if (target === "users") loadUsers();
      if (target === "attempts") loadAttempts();
    });
  });
}

async function loadUsers() {
  const root = $("users-root");
  try {
    const list = await apiGet("/api/admin/users");
    root.innerHTML = `
      <table class="history-table">
        <thead><tr><th>ID</th><th>用户</th><th>角色 / 状态</th><th>完成度</th><th>核心指标</th><th>诊断指标</th><th>注册</th><th></th></tr></thead>
        <tbody>${list.map((user) => `
          <tr>
            <td>${user.id}</td>
            <td>${escapeHtml(user.username)}${user.display_name ? `<span class="history-subtext">${escapeHtml(user.display_name)}</span>` : ""}${user.work_hospital ? `<span class="history-subtext">${escapeHtml(user.work_hospital)}</span>` : ""}${user.physician_title ? `<span class="history-subtext">${escapeHtml(user.physician_title)}</span>` : ""}${user.career_stage ? `<span class="history-subtext">${escapeHtml(CAREER_LABELS[user.career_stage] || user.career_stage)}</span>` : ""}</td>
            <td><span class="chip">${ROLE_LABELS[user.role] || user.role}</span><span class="history-subtext">${user.is_active ? "启用" : "停用"}</span></td>
            <td>${renderUserProgress(user)}</td>
            <td>${renderUserCoreMetrics(user)}</td>
            <td>${renderUserDiagnosticMetrics(user)}</td>
            <td>${fmt(user.created_at)}</td>
            <td><button class="btn" data-edit="${user.id}">编辑</button></td>
          </tr>
        `).join("")}</tbody>
      </table>`;
    root.querySelectorAll("button[data-edit]").forEach((button) => {
      button.addEventListener("click", () => openUserModal(list.find((item) => item.id === Number(button.dataset.edit))));
    });
  } catch (e) {
    root.innerHTML = `<p class="feedback" data-kind="error">${escapeHtml(e.message)}</p>`;
  }
}

function openUserModal(user) {
  $("modal-title").textContent = user.username;
  $("m-id").value = user.id;
  $("m-display").value = user.display_name || "";
  $("m-hospital").value = user.work_hospital || "";
  $("m-title").value = user.physician_title || "";
  $("m-career").value = user.career_stage || "";
  $("m-license-years").value = user.license_years ?? "";
  $("m-role").value = user.role;
  $("m-active").checked = !!user.is_active;
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
      work_hospital: $("m-hospital").value || null,
      physician_title: $("m-title").value || null,
      career_stage: $("m-career").value || null,
    };
    const licenseRaw = $("m-license-years").value.trim();
    payload.license_years = licenseRaw === "" ? null : Number(licenseRaw);
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

async function loadAttempts() {
  const params = new URLSearchParams();
  const tc = $("f-task").value.trim();
  const uid = $("f-user").value.trim();
  const st = $("f-status").value;
  if (tc) params.set("task_code", tc);
  if (uid) params.set("user_id", uid);
  if (st) params.set("status", st);
  const q = params.toString();
  const summaryRoot = $("attempts-summary-root");
  const root = $("attempts-root");
  try {
    const [summaryList, list] = await Promise.all([
      apiGet("/api/admin/attempts/user-summaries" + (q ? "?" + q : "")),
      apiGet("/api/admin/attempts" + (q ? "?" + q : "")),
    ]);
    summaryRoot.innerHTML = renderAttemptSummaryTable(summaryList);
    if (!list.length) { root.innerHTML = `<p class="brand-copy">无结果</p>`; return; }
    root.innerHTML = `
      <table class="history-table">
        <thead><tr><th>ID</th><th>用户</th><th>研究任务</th><th>状态</th><th>Accuracy</th><th>AUC</th><th>开始</th><th>提交</th><th></th></tr></thead>
        <tbody>${list.map((attempt) => `
          <tr>
            <td>${attempt.id}</td>
            <td>${escapeHtml(attempt.username)}${attempt.display_name ? ` (${escapeHtml(attempt.display_name)})` : ""}</td>
            <td>${escapeHtml(attempt.task_name)} <code>${escapeHtml(attempt.task_code)}</code></td>
            <td><span class="chip ${attempt.status === "submitted" ? "chip-success" : "chip-muted"}">${STATUS_LABELS[attempt.status] || attempt.status}</span></td>
            <td>${renderAttemptAgreement(attempt)}</td>
            <td>${formatAuc(attempt.auc)}</td>
            <td>${fmt(attempt.started_at)}</td>
            <td>${fmt(attempt.submitted_at)}</td>
            <td><button class="btn" type="button" data-attempt-detail="${attempt.id}">查看</button></td>
          </tr>
        `).join("")}</tbody>
      </table>`;
    bindAttemptDetailButtons(root);
  } catch (e) {
    summaryRoot.innerHTML = "";
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
