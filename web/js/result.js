import { apiGet, fetchMe } from "./api.js";

const $ = (id) => document.getElementById(id);
const attemptId = Number(location.pathname.split("/").filter(Boolean).pop() || 0);

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fmt(d) {
  if (!d) return "-";
  return new Date(d).toLocaleString("zh-CN", { hour12: false });
}

function formatSeconds(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return m ? `${m}分${String(rest).padStart(2, "0")}秒` : `${rest}秒`;
}

function rowLabel(r, i) {
  return Number.isFinite(r.batch_position) ? r.batch_position + 1 : i + 1;
}

async function load() {
  const me = await fetchMe();
  if (!me) { window.location.href = "/login"; return; }

  let res;
  try {
    res = await apiGet(`/api/attempts/${attemptId}/result`);
  } catch (e) {
    document.querySelector("main").innerHTML = `<section class="panel"><h2>无法加载结果</h2><p class="brand-copy">${escapeHtml(e.message)}</p></section>`;
    return;
  }

  const rows = res.rows || [];
  const answered = rows.filter((r) => r.answer_text).length;
  const review = rows.filter((r) => r.review_flag).length;
  const total = rows.length || res.total || 0;
  const pct = total ? (answered / total) * 100 : 0;

  $("task-name").textContent = res.task_name;
  $("task-meta").textContent = `任务编码 ${res.task_code} · 批次 ${(res.batch_index || 0) + 1} · 提交于 ${fmt(res.submitted_at)}`;
  $("answered-pct").textContent = `${pct.toFixed(1)}%`;
  $("answered-num").textContent = answered;
  $("total-num").textContent = total;
  $("review-num").textContent = review;
  $("submitted-at").textContent = fmt(res.submitted_at);

  const root = $("rows-root");
  if (!rows.length) { root.innerHTML = `<p class="brand-copy">暂无题目</p>`; return; }
  root.innerHTML = rows.map((r, i) => `
    <article class="result-row">
      <button class="result-img" data-img="${escapeHtml(r.image_url)}">
        <img src="${escapeHtml(r.image_url)}" loading="lazy" alt="题图">
      </button>
      <div class="result-row-body">
        <div class="result-row-head">
          <p class="eyebrow">第 ${i + 1} 题 · 批内 ${rowLabel(r, i)}</p>
          ${r.review_flag ? `<span class="chip chip-warning">已标记复查</span>` : ""}
        </div>
        <p class="row-line"><span>我的答案</span><strong>${escapeHtml(r.answer_text || "(未答)")}</strong></p>
        <p class="row-line"><span>用时</span><strong>${formatSeconds(r.time_spent_seconds || 0)}</strong></p>
        ${r.note ? `<p class="row-note"><span>备注</span> ${escapeHtml(r.note)}</p>` : ""}
      </div>
    </article>
  `).join("");

  root.querySelectorAll("button.result-img").forEach((btn) => {
    btn.addEventListener("click", () => openLightbox(btn.dataset.img));
  });
  bindLightbox();
}

let lightboxScale = 1;
let lightboxFitScale = 1;
let lightboxOffset = { x: 0, y: 0 };
let lightboxDragging = false;
let lightboxDragStart = { x: 0, y: 0 };

function applyLightboxTransform() {
  const img = $("lightbox-image");
  img.style.transform = `translate(${lightboxOffset.x}px, ${lightboxOffset.y}px) scale(${lightboxScale})`;
  $("lightbox-stage").classList.toggle("is-draggable", lightboxScale > lightboxFitScale + 0.02);
}

function fitLightbox() {
  const img = $("lightbox-image");
  if (!img.naturalWidth || !img.naturalHeight) return;
  const maxW = window.innerWidth * 0.92;
  const maxH = window.innerHeight * 0.82;
  lightboxFitScale = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight, 1);
  lightboxScale = lightboxFitScale;
  lightboxOffset = { x: 0, y: 0 };
  img.style.width = `${img.naturalWidth}px`;
  img.style.height = `${img.naturalHeight}px`;
  applyLightboxTransform();
}

function setActualSize() {
  lightboxScale = 1;
  lightboxOffset = { x: 0, y: 0 };
  applyLightboxTransform();
}

function zoomLightbox(delta) {
  lightboxScale = Math.min(6, Math.max(0.1, lightboxScale + delta));
  applyLightboxTransform();
}

function openLightbox(url) {
  const img = $("lightbox-image");
  img.src = url;
  $("lightbox").classList.remove("hidden");
  if (img.complete) fitLightbox();
}

function closeLightbox() {
  $("lightbox").classList.add("hidden");
}

function bindLightbox() {
  $("lightbox-image").addEventListener("load", fitLightbox);
  $("lightbox-close").addEventListener("click", closeLightbox);
  $("fit-btn").addEventListener("click", fitLightbox);
  $("actual-btn").addEventListener("click", setActualSize);
  $("zoom-in-btn").addEventListener("click", () => zoomLightbox(0.2));
  $("zoom-out-btn").addEventListener("click", () => zoomLightbox(-0.2));
  $("lightbox").addEventListener("click", (e) => {
    if (e.target.id === "lightbox") closeLightbox();
  });
  $("lightbox-stage").addEventListener("wheel", (e) => {
    e.preventDefault();
    zoomLightbox(e.deltaY > 0 ? -0.16 : 0.16);
  }, { passive: false });
  $("lightbox-stage").addEventListener("pointerdown", (e) => {
    lightboxDragging = true;
    lightboxDragStart = { x: e.clientX - lightboxOffset.x, y: e.clientY - lightboxOffset.y };
    $("lightbox-stage").setPointerCapture(e.pointerId);
  });
  $("lightbox-stage").addEventListener("pointermove", (e) => {
    if (!lightboxDragging) return;
    lightboxOffset = { x: e.clientX - lightboxDragStart.x, y: e.clientY - lightboxDragStart.y };
    applyLightboxTransform();
  });
  $("lightbox-stage").addEventListener("pointerup", (e) => {
    lightboxDragging = false;
    $("lightbox-stage").releasePointerCapture(e.pointerId);
  });
  window.addEventListener("resize", () => {
    if (!$("lightbox").classList.contains("hidden")) fitLightbox();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeLightbox();
  });
}

load();
