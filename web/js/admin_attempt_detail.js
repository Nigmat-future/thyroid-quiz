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

function calculateAuc(points) {
  const positives = points.filter((point) => point.truth === 1).map((point) => point.score);
  const negatives = points.filter((point) => point.truth === 0).map((point) => point.score);
  if (!positives.length || !negatives.length) return null;

  let wins = 0;
  positives.forEach((positive) => {
    negatives.forEach((negative) => {
      if (positive > negative) wins += 1;
      if (positive === negative) wins += 0.5;
    });
  });
  return wins / (positives.length * negatives.length);
}

function buildAucCurve(rows) {
  const sortedRows = [...rows].sort((a, b) => {
    const left = a.batch_position ?? a.order_index ?? 0;
    const right = b.batch_position ?? b.order_index ?? 0;
    return left - right;
  });
  const usablePoints = [];
  return sortedRows.map((row, index) => {
    if (
      typeof row.truth_binary === "number"
      && typeof row.doctor_malignancy_score === "number"
    ) {
      usablePoints.push({
        truth: row.truth_binary,
        score: row.doctor_malignancy_score,
      });
    }
    const positives = usablePoints.filter((point) => point.truth === 1).length;
    const negatives = usablePoints.filter((point) => point.truth === 0).length;
    return {
      questionNumber: index + 1,
      auc: calculateAuc(usablePoints),
      positives,
      negatives,
    };
  });
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

function renderAucCurve(rows) {
  const curve = buildAucCurve(rows);
  const points = curve.filter((point) => typeof point.auc === "number");
  if (!points.length) {
    return `
      <section class="auc-curve-card">
        <div class="auc-curve-head">
          <h3>实时AUC曲线</h3>
          <span>至少需要 1 个癌样本和 1 个非癌样本</span>
        </div>
        <div class="auc-empty">当前样本不足，暂时无法形成 AUC 曲线。</div>
      </section>`;
  }

  const width = 720;
  const height = 220;
  const padLeft = 44;
  const padRight = 18;
  const padTop = 18;
  const padBottom = 34;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;
  const maxQuestion = Math.max(...curve.map((point) => point.questionNumber), 1);
  const toX = (questionNumber) => padLeft + ((questionNumber - 1) / Math.max(maxQuestion - 1, 1)) * plotWidth;
  const toY = (auc) => padTop + (1 - auc) * plotHeight;
  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${toX(point.questionNumber).toFixed(1)} ${toY(point.auc).toFixed(1)}`)
    .join(" ");
  const latest = points.at(-1);
  const latestLabel = latest
    ? `第 ${latest.questionNumber} 题：AUC ${formatAuc(latest.auc)}，样本 ${latest.positives}/${latest.negatives}`
    : "-";

  return `
    <section class="auc-curve-card">
      <div class="auc-curve-head">
        <h3>实时AUC曲线</h3>
        <span>${latestLabel}</span>
      </div>
      <svg class="auc-curve" viewBox="0 0 ${width} ${height}" role="img" aria-label="实时AUC曲线">
        <line x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${height - padBottom}" />
        <line x1="${padLeft}" y1="${height - padBottom}" x2="${width - padRight}" y2="${height - padBottom}" />
        ${[0, 0.25, 0.5, 0.75, 1].map((tick) => `
          <g class="auc-grid">
            <line x1="${padLeft}" y1="${toY(tick)}" x2="${width - padRight}" y2="${toY(tick)}" />
            <text x="8" y="${toY(tick) + 4}">${tick.toFixed(2)}</text>
          </g>
        `).join("")}
        <path class="auc-line" d="${path}" pathLength="1" />
        ${points.map((point) => `
          <circle class="auc-point" cx="${toX(point.questionNumber).toFixed(1)}" cy="${toY(point.auc).toFixed(1)}" r="3.5">
            <title>第 ${point.questionNumber} 题：AUC ${formatAuc(point.auc)}，样本 ${point.positives}/${point.negatives}</title>
          </circle>
        `).join("")}
        <text class="auc-axis-label" x="${width / 2}" y="${height - 7}">答题进度</text>
        <text class="auc-axis-label" x="${padLeft}" y="12">AUC</text>
      </svg>
    </section>`;
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
      ${renderAucCurve(detail.rows)}
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
