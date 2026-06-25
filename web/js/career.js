export const CAREER_LABELS = {
  graduate: "研究生",
  practitioner: "已入职大夫",
  other: "其他",
};

export function formatCareerLabel(user) {
  if (!user?.career_stage) return "";
  if (user.career_stage === "other") {
    return user.career_stage_other || CAREER_LABELS.other;
  }
  return CAREER_LABELS[user.career_stage] || user.career_stage;
}

export function isCareerComplete(user) {
  if (!user?.career_stage) return false;
  if (user.career_stage === "graduate" || user.career_stage === "practitioner") return true;
  if (user.career_stage === "other") return Boolean(String(user.career_stage_other || "").trim());
  return false;
}

export function bindCareerStageField({ stageId, otherWrapId, otherInputId }) {
  const stage = document.getElementById(stageId);
  const wrap = document.getElementById(otherWrapId);
  const other = document.getElementById(otherInputId);
  if (!stage || !wrap || !other) return;

  const sync = () => {
    const isOther = stage.value === "other";
    wrap.classList.toggle("hidden", !isOther);
    other.required = isOther;
    if (!isOther) other.value = "";
  };

  stage.addEventListener("change", sync);
  sync();
}

export function readCareerFields(stageEl, otherEl) {
  const career_stage = stageEl.value;
  if (!career_stage) return { error: "请选择身份类型" };

  if (career_stage === "other") {
    const career_stage_other = otherEl.value.trim();
    if (!career_stage_other) return { error: "请填写身份说明" };
    return { career_stage, career_stage_other };
  }

  return { career_stage, career_stage_other: null };
}

export function fillCareerFields(user, stageEl, otherEl, otherWrapEl) {
  stageEl.value = user.career_stage || "";
  otherEl.value = user.career_stage_other || "";
  const isOther = user.career_stage === "other";
  if (otherWrapEl) otherWrapEl.classList.toggle("hidden", !isOther);
  otherEl.required = isOther;
}

export const CAREER_STAGE_OPTIONS = `
  <option value="">请选择</option>
  <option value="graduate">研究生</option>
  <option value="practitioner">已入职大夫</option>
  <option value="other">其他</option>`;

export const CAREER_OTHER_FIELD = `
  <label class="field hidden" id="career-other-wrap">
    <span>请说明身份 *</span>
    <input id="career-other" name="career_stage_other" type="text" maxlength="128" placeholder="例如：进修医师 / 规培生">
  </label>`;
