import { apiGet } from "./api.js";

const DETAIL_COLSPAN = 9;

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function formatPercent(value) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "-";
}

export function formatAuc(value) {
  return typeof value === "number" ? value.toFixed(3) : "-";
}

function formatMetricCount(value) {
  return typeof value === "number" ? String(value) : "-";
}

function correctnessChip(row) {
  if (!row.answer_text) return `<span class="chip chip-muted">未答</span>`;
  return row.is_correct
    ? `<span class="chip chip-success">正确</span>`
    : `<span class="chip chip-danger">错误</span>`;
}

function renderMetrics(metrics) {
  return `
    <div class="attempt-metrics">
      <div><span>题数</span><strong>${metrics.total}</strong></div>
      <div><span>已答</span><strong>${metrics.answered}</strong></div>
      <div><span>正确</span><strong>${metrics.correct}</strong></div>
      <div><span>正确率</span><strong>${formatPercent(metrics.accuracy)}</strong></div>
      <div><span>AUC</span><strong>${formatAuc(metrics.auc)}</strong></div>
      <div><span>AUC样本</span><strong>${metrics.auc_positive}/${metrics.auc_negative}</strong></div>
    </div>`;
}

function renderDetailRows(rows) {
  return rows.map((row) => `
    <tr>
      <td>${row.batch_position + 1}</td>
      <td><img class="attempt-thumb" src="${escapeHtml(row.image_url)}" alt=""></td>
      <td>${escapeHtml(row.answer_text || "未答")}</td>
      <td>${escapeHtml(row.ground_truth)}</td>
      <td>${correctnessChip(row)}</td>
      <td>${formatMetricCount(row.doctor_malignancy_score)}</td>
      <td>${formatMetricCount(row.truth_binary)}</td>
      <td>
        ${escapeHtml(row.source_center || "-")}
        <span class="history-subtext">${escapeHtml(row.source_file_path || "")}</span>
      </td>
      <td>
        ${row.time_spent_seconds || 0}s
        ${row.review_flag ? `<span class="history-subtext">需复核</span>` : ""}
      </td>
    </tr>
  `).join("");
}

function renderAttemptDetail(detail) {
  return `
    <div class="attempt-detail">
      ${renderMetrics(detail.metrics)}
      <table class="history-table attempt-detail-table">
        <thead>
          <tr>
            <th>题号</th><th>图像</th><th>用户答案</th><th>标准答案</th>
            <th>结果</th><th>恶性评分</th><th>真值</th><th>来源</th><th>用时</th>
          </tr>
        </thead>
        <tbody>${renderDetailRows(detail.rows)}</tbody>
      </table>
    </div>`;
}

async function toggleAttemptDetail(button, root) {
  const id = button.dataset.attemptDetail;
  const existing = root.querySelector(`tr[data-detail-for="${id}"]`);
  if (existing) {
    existing.remove();
    button.textContent = "查看";
    return;
  }

  root.querySelectorAll("tr.attempt-detail-row").forEach((row) => row.remove());
  root.querySelectorAll("button[data-attempt-detail]").forEach((btn) => {
    btn.textContent = "查看";
  });

  const parent = button.closest("tr");
  const detailRow = document.createElement("tr");
  detailRow.className = "attempt-detail-row";
  detailRow.dataset.detailFor = id;
  detailRow.innerHTML = `<td colspan="${DETAIL_COLSPAN}"><p class="brand-copy">加载中…</p></td>`;
  parent.after(detailRow);
  root.scrollLeft = 0;
  button.textContent = "收起";

  try {
    const detail = await apiGet(`/api/admin/attempts/${id}`);
    detailRow.innerHTML = `<td colspan="${DETAIL_COLSPAN}">${renderAttemptDetail(detail)}</td>`;
  } catch (error) {
    detailRow.innerHTML = `<td colspan="${DETAIL_COLSPAN}"><p class="feedback" data-kind="error">${escapeHtml(error.message)}</p></td>`;
  }
}

export function bindAttemptDetailButtons(root) {
  root.querySelectorAll("button[data-attempt-detail]").forEach((button) => {
    button.addEventListener("click", () => toggleAttemptDetail(button, root));
  });
}
