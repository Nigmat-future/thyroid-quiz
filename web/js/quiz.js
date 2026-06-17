// 答题主逻辑：load attempt -> 渲染图像 -> 自动保存 -> 提交。
import { api, apiGet, apiPost, fetchMe } from "./api.js";
import { preloadNextQuestionImage } from "./image_preload.js";

const $ = (id) => document.getElementById(id);
const attemptId = Number(location.pathname.split("/").filter(Boolean).pop() || 0);

let attempt = null;
let optionsForDisplay = [];
let answersMap = new Map(); // q_id -> { answer_text, note, review_flag, time_spent_seconds, dirty }
let currentIdx = 0;
let saveTimer = null;
let questionEnterAt = Date.now();
let timeTicker = null;
let isSubmitting = false;
let imagePreloadToken = 0;

const SAVE_DEBOUNCE_MS = 600;

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function shuffleCopy(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function ensureAnswer(questionId) {
  if (!answersMap.has(questionId)) {
    answersMap.set(questionId, {
      answer_text: "",
      note: "",
      review_flag: false,
      time_spent_seconds: 0,
      dirty: false,
    });
  }
  return answersMap.get(questionId);
}

function currentQuestion() {
  return attempt.questions[currentIdx];
}

function formatSeconds(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const m = Math.floor(s / 60);
  const rest = s % 60;
  return m ? `${m}分${String(rest).padStart(2, "0")}秒` : `${rest}秒`;
}

function elapsedOnCurrent() {
  return Math.max(0, Math.floor((Date.now() - questionEnterAt) / 1000));
}

function accrueCurrentTime() {
  if (!attempt || !attempt.questions.length) return;
  const q = currentQuestion();
  const cur = ensureAnswer(q.id);
  const elapsed = elapsedOnCurrent();
  if (elapsed > 0) {
    cur.time_spent_seconds = Math.max(0, cur.time_spent_seconds || 0) + elapsed;
    cur.dirty = true;
    questionEnterAt = Date.now();
  }
  updateTimeLabel();
}

function updateTimeLabel() {
  if (!attempt || !$("meta-time")) return;
  const q = currentQuestion();
  const cur = ensureAnswer(q.id);
  $("meta-time").textContent = formatSeconds((cur.time_spent_seconds || 0) + elapsedOnCurrent());
}

function setSaveState(label, kind = "muted") {
  $("save-state").textContent = label;
  $("save-state").className = "chip " + (kind === "success" ? "chip-success" : kind === "error" ? "chip-danger" : "chip-muted");
  $("meta-save").textContent = label;
}

function questionLabel(q, idx) {
  const pos = Number.isFinite(q.batch_position) ? q.batch_position + 1 : idx + 1;
  return String(pos);
}

async function load() {
  const me = await fetchMe();
  if (!me) { window.location.href = "/login"; return; }
  try {
    attempt = await apiGet(`/api/attempts/${attemptId}`);
  } catch (e) {
    if (e.status === 409) {
      window.location.href = `/result/${attemptId}`;
      return;
    }
    document.querySelector("main")?.replaceWith(Object.assign(document.createElement("div"), {
      className: "panel",
      innerHTML: `<h2>无法加载判读任务</h2><p class="brand-copy">${escapeHtml(e.message)}</p>`,
    }));
    return;
  }

  if (!attempt.questions.length) {
    document.querySelector("main").innerHTML = `<section class="panel"><h2>该任务暂无图像</h2><a class="btn" href="/">返回首页</a></section>`;
    return;
  }

  try {
    const task = await apiGet(`/api/tasks/${encodeURIComponent(attempt.task_code)}`);
    optionsForDisplay = task.randomize_options ? shuffleCopy(attempt.answer_options) : attempt.answer_options;
  } catch {
    optionsForDisplay = attempt.answer_options;
  }

  for (const a of attempt.answers) {
    answersMap.set(a.question_id, {
      answer_text: a.answer_text || "",
      note: a.note || "",
      review_flag: Boolean(a.review_flag),
      time_spent_seconds: Math.max(0, a.time_spent_seconds || 0),
      dirty: false,
    });
  }

  $("task-name").textContent = attempt.task_name;
  $("task-eyebrow").textContent = `图像判读中 · ${attempt.task_code}`;
  $("total-count").textContent = String(attempt.questions.length);
  $("batch-label").textContent = `${(attempt.batch_index || 0) + 1} / ${attempt.batch_total || 1}`;
  $("quiz-shell").hidden = false;

  bindControls();
  bindLightbox();
  renderNav();
  renderQuestion(0);
}

function answeredCount() {
  let n = 0;
  for (const q of attempt.questions) {
    if (ensureAnswer(q.id).answer_text) n++;
  }
  return n;
}

function reviewCount() {
  let n = 0;
  for (const q of attempt.questions) {
    if (ensureAnswer(q.id).review_flag) n++;
  }
  return n;
}

function navButton(q, i) {
  const a = ensureAnswer(q.id);
  const cls = ["nav-pill"];
  if (i === currentIdx) cls.push("active");
  if (a.answer_text) cls.push("answered");
  if (a.review_flag) cls.push("reviewed");
  return `<button class="${cls.join(" ")}" data-idx="${i}" title="第 ${questionLabel(q, i)} 题">${questionLabel(q, i)}</button>`;
}

function renderNav() {
  const nav = $("question-nav");
  const review = [];
  const todo = [];
  const done = [];

  attempt.questions.forEach((q, i) => {
    const a = ensureAnswer(q.id);
    if (a.review_flag) review.push([q, i]);
    else if (a.answer_text) done.push([q, i]);
    else todo.push([q, i]);
  });

  const groups = [
    ["待作答", todo],
    ["已作答", done],
    ["复查", review],
  ];

  nav.innerHTML = groups.map(([name, rows]) => `
    <section class="nav-group">
      <div class="nav-group-title"><span>${name}</span><strong>${rows.length}</strong></div>
      <div class="nav-group-grid">
        ${rows.length ? rows.map(([q, i]) => navButton(q, i)).join("") : `<span class="nav-empty">无</span>`}
      </div>
    </section>
  `).join("");

  nav.querySelectorAll("button[data-idx]").forEach((b) => {
    b.addEventListener("click", () => goTo(Number(b.dataset.idx)));
  });

  const total = attempt.questions.length;
  const ans = answeredCount();
  const rev = reviewCount();
  $("answered-count").textContent = String(ans);
  $("review-count").textContent = String(rev);
  $("progress-label").textContent = `${ans} / ${total}`;
  $("progress-caption").textContent = `已评估 ${ans} / ${total}`;
  $("progress-fill").style.width = total ? `${(ans / total) * 100}%` : "0%";
}

function renderQuestion(idx) {
  currentIdx = idx;
  questionEnterAt = Date.now();
  const q = currentQuestion();
  const cur = ensureAnswer(q.id);

  $("question-counter").textContent = `第 ${idx + 1} / ${attempt.questions.length} 题`;
  $("question-title").textContent = `题号 #${q.order_index + 1}`;
  $("meta-order").textContent = String(q.order_index + 1);
  $("meta-batch-pos").textContent = `${questionLabel(q, idx)} / ${attempt.questions.length}`;
  $("question-image").src = q.image_url;
  preloadNextWhenCurrentImageReady(idx);
  $("note-input").value = cur.note || "";
  $("review-toggle").classList.toggle("is-on", Boolean(cur.review_flag));
  $("review-toggle").setAttribute("aria-pressed", cur.review_flag ? "true" : "false");
  $("review-toggle").textContent = cur.review_flag ? "已标记复查" : "标记复查";
  setSaveState(cur.dirty ? "待保存" : (cur.answer_text || cur.note || cur.review_flag ? "已保存" : "未保存"), cur.dirty ? "muted" : (cur.answer_text || cur.note || cur.review_flag ? "success" : "muted"));

  const optsEl = $("answer-options");
  optsEl.innerHTML = optionsForDisplay.map((opt, i) => `
    <label class="option-pill scale-option ${cur.answer_text === opt ? "selected" : ""}">
      <input type="radio" name="answer" value="${escapeHtml(opt)}" ${cur.answer_text === opt ? "checked" : ""}>
      <span class="option-key">${i + 1}</span>
      <span>${escapeHtml(opt)}</span>
    </label>`).join("");
  optsEl.querySelectorAll("input[name=answer]").forEach((inp) => {
    inp.addEventListener("change", (e) => chooseAnswer(e.target.value));
  });

  $("note-input").oninput = () => {
    const ans = ensureAnswer(q.id);
    ans.note = $("note-input").value;
    ans.dirty = true;
    scheduleSave();
  };

  $("prev-btn").disabled = idx === 0;
  $("next-btn").disabled = idx === attempt.questions.length - 1;
  renderNav();
  updateTimeLabel();
  if (timeTicker) clearInterval(timeTicker);
  timeTicker = setInterval(updateTimeLabel, 1000);
}

function preloadNextWhenCurrentImageReady(idx) {
  const token = ++imagePreloadToken;
  const img = $("question-image");
  const preload = () => {
    if (token === imagePreloadToken) preloadNextQuestionImage(attempt.questions, idx);
  };
  if (img.complete) {
    preload();
  } else {
    img.addEventListener("load", preload, { once: true });
  }
}

function chooseAnswer(value) {
  const q = currentQuestion();
  const ans = ensureAnswer(q.id);
  ans.answer_text = value;
  ans.dirty = true;
  answersMap.set(q.id, ans);

  const optsEl = $("answer-options");
  optsEl.querySelectorAll(".option-pill").forEach((p) => {
    const inp = p.querySelector("input[name=answer]");
    const selected = inp.value === value;
    inp.checked = selected;
    p.classList.toggle("selected", selected);
  });
  setSaveState("保存中...", "muted");
  scheduleSave();
  renderNav();
}

function chooseAnswerByIndex(idx) {
  if (idx < 0 || idx >= optionsForDisplay.length) return;
  chooseAnswer(optionsForDisplay[idx]);
}

function toggleReview() {
  const q = currentQuestion();
  const ans = ensureAnswer(q.id);
  ans.review_flag = !ans.review_flag;
  ans.dirty = true;
  $("review-toggle").classList.toggle("is-on", ans.review_flag);
  $("review-toggle").setAttribute("aria-pressed", ans.review_flag ? "true" : "false");
  $("review-toggle").textContent = ans.review_flag ? "已标记复查" : "标记复查";
  setSaveState("保存中...", "muted");
  scheduleSave();
  renderNav();
}

async function goTo(idx) {
  if (idx < 0 || idx >= attempt.questions.length || idx === currentIdx) return;
  await flushSave({ includeTime: true });
  renderQuestion(idx);
}

function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { flushSave({ includeTime: true }).catch(() => {}); }, SAVE_DEBOUNCE_MS);
}

async function flushSave({ includeTime = false } = {}) {
  if (!attempt || !attempt.questions.length) return true;
  if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
  if (includeTime) accrueCurrentTime();

  const q = currentQuestion();
  const cur = ensureAnswer(q.id);
  if (!cur.dirty) return true;

  try {
    const saved = await api("PUT", `/api/attempts/${attempt.id}/answers/${q.id}`, {
      answer_text: cur.answer_text || "",
      note: cur.note || "",
      review_flag: Boolean(cur.review_flag),
      time_spent_seconds: Math.max(0, cur.time_spent_seconds || 0),
    });
    cur.answer_text = saved.answer_text || "";
    cur.note = saved.note || "";
    cur.review_flag = Boolean(saved.review_flag);
    cur.time_spent_seconds = Math.max(cur.time_spent_seconds || 0, saved.time_spent_seconds || 0);
    cur.dirty = false;
    setSaveState("已保存", "success");
    renderNav();
    updateTimeLabel();
    return true;
  } catch (e) {
    setSaveState("保存失败：" + e.message, "error");
    return false;
  }
}

function isEditableTarget(target) {
  const tag = target?.tagName?.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target?.isContentEditable;
}

function bindControls() {
  $("prev-btn").addEventListener("click", () => goTo(currentIdx - 1));
  $("next-btn").addEventListener("click", () => goTo(currentIdx + 1));
  $("save-btn").addEventListener("click", () => flushSave({ includeTime: true }));
  $("review-toggle").addEventListener("click", toggleReview);
  $("submit-btn").addEventListener("click", openSubmitReview);
  $("submit-cancel-btn").addEventListener("click", closeSubmitReview);
  $("submit-confirm-btn").addEventListener("click", doSubmit);
  $("submit-modal").addEventListener("click", (e) => {
    if (e.target.id === "submit-modal") closeSubmitReview();
  });
  window.addEventListener("beforeunload", () => { accrueCurrentTime(); flushSave(); });
  document.addEventListener("keydown", (e) => {
    if (isEditableTarget(e.target) || e.altKey || e.ctrlKey || e.metaKey) return;
    if (!$("lightbox").classList.contains("hidden")) {
      if (e.key === "Escape") closeLightbox();
      return;
    }
    if (!$("submit-modal").classList.contains("hidden")) {
      if (e.key === "Escape") closeSubmitReview();
      return;
    }
    if (/^[1-5]$/.test(e.key)) {
      e.preventDefault();
      chooseAnswerByIndex(Number(e.key) - 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      goTo(currentIdx - 1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      goTo(currentIdx + 1);
    }
  });
}

function submitStats() {
  const total = attempt.questions.length;
  const unanswered = [];
  const review = [];
  let answered = 0;
  let totalSeconds = 0;

  attempt.questions.forEach((q, i) => {
    const a = ensureAnswer(q.id);
    if (a.answer_text) answered++;
    else unanswered.push([q, i]);
    if (a.review_flag) review.push([q, i]);
    totalSeconds += Math.max(0, a.time_spent_seconds || 0);
  });

  return { total, answered, unanswered, review, totalSeconds };
}

function openSubmitReview() {
  accrueCurrentTime();
  const stats = submitStats();
  $("submit-review-grid").innerHTML = `
    <div class="summary-card"><span>已评估</span><strong>${stats.answered}</strong></div>
    <div class="summary-card"><span>未答</span><strong>${stats.unanswered.length}</strong></div>
    <div class="summary-card"><span>复查</span><strong>${stats.review.length}</strong></div>
    <div class="summary-card"><span>累计用时</span><strong>${formatSeconds(stats.totalSeconds)}</strong></div>
  `;

  const makeList = (title, rows, empty) => `
    <div class="submit-review-section">
      <h3>${title}</h3>
      ${rows.length ? `<div class="submit-review-pills">${rows.map(([q, i]) => `<button type="button" class="nav-pill ${ensureAnswer(q.id).review_flag ? "reviewed" : ""}" data-jump="${i}">${questionLabel(q, i)}</button>`).join("")}</div>` : `<p class="brand-copy">${empty}</p>`}
    </div>
  `;
  $("submit-review-list").innerHTML =
    makeList("未评估病例", stats.unanswered, "无未评估病例。") +
    makeList("已标记复查", stats.review, "无复查标记。");

  $("submit-review-list").querySelectorAll("button[data-jump]").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeSubmitReview();
      goTo(Number(btn.dataset.jump));
    });
  });
  $("submit-modal").classList.remove("hidden");
}

function closeSubmitReview() {
  $("submit-modal").classList.add("hidden");
}

async function doSubmit() {
  if (isSubmitting) return;
  isSubmitting = true;
  $("submit-confirm-btn").disabled = true;
  $("submit-btn").disabled = true;
  const saved = await flushSave({ includeTime: true });
  if (!saved) {
    $("quiz-feedback").textContent = "当前题保存失败，请稍后重试后再提交。";
    $("submit-confirm-btn").disabled = false;
    $("submit-btn").disabled = false;
    isSubmitting = false;
    return;
  }
  try {
    await apiPost(`/api/attempts/${attempt.id}/submit`);
    window.location.href = `/result/${attempt.id}`;
  } catch (e) {
    $("quiz-feedback").textContent = "提交失败：" + e.message;
    $("submit-confirm-btn").disabled = false;
    $("submit-btn").disabled = false;
    isSubmitting = false;
  }
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
  const next = Math.min(6, Math.max(0.1, lightboxScale + delta));
  lightboxScale = next;
  applyLightboxTransform();
}

function openLightbox(url) {
  const img = $("lightbox-image");
  img.src = url;
  $("lightbox").classList.remove("hidden");
  $("lightbox").setAttribute("aria-hidden", "false");
  if (img.complete) fitLightbox();
}

function closeLightbox() {
  $("lightbox").classList.add("hidden");
  $("lightbox").setAttribute("aria-hidden", "true");
}

function bindLightbox() {
  $("image-tile").addEventListener("click", () => openLightbox($("question-image").src));
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
}

load();
