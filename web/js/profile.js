// 全站资料补填：不完整时注入弹窗并阻塞，直到 PATCH /api/me 成功。
import { apiPatch, fetchMe } from "./api.js";

const $ = (id) => document.getElementById(id);

let pendingProfilePromise = null;

const PROFILE_MODAL_HTML = `
  <div class="modal hidden" id="profile-modal" role="dialog" aria-modal="true" aria-labelledby="profile-title">
    <div class="modal-card panel">
      <div class="panel-head">
        <div>
          <p class="eyebrow">完善资料</p>
          <h2 id="profile-title">请补充个人信息</h2>
        </div>
      </div>
      <p class="brand-copy">资料不完整时，需补充以下信息后才能继续使用工作台。</p>
      <form class="form-grid" id="profile-form">
        <label class="field">
          <span>真名 *</span>
          <input id="p-display-name" name="display_name" type="text" autocomplete="name" required maxlength="128" placeholder="例如：张三">
        </label>
        <label class="field">
          <span>工作医院 *</span>
          <input id="p-work-hospital" name="work_hospital" type="text" required maxlength="256" placeholder="例如：北京协和医院">
        </label>
        <label class="field">
          <span>医师职称 *</span>
          <input id="p-physician-title" name="physician_title" type="text" required maxlength="64" placeholder="例如：主治医师（研究生可填「无」）">
        </label>
        <label class="field">
          <span>身份类型 *</span>
          <select id="p-career-stage" name="career_stage" required>
            <option value="">请选择</option>
            <option value="graduate">研究生</option>
            <option value="practitioner">已入职大夫</option>
          </select>
        </label>
        <label class="field">
          <span>取得执业医师资格证后的时间（年） *</span>
          <input id="p-license-years" name="license_years" type="number" min="0" max="80" required placeholder="未取得填 0">
        </label>
        <div class="actions field-wide">
          <button type="submit" class="btn btn-primary" id="profile-submit-btn">保存并继续</button>
        </div>
        <p class="feedback" id="profile-feedback"></p>
      </form>
    </div>
  </div>`;

export function isProfileIncomplete(me) {
  if (!me) return true;
  return !(
    String(me.display_name || "").trim()
    && String(me.work_hospital || "").trim()
    && String(me.physician_title || "").trim()
    && (me.career_stage === "graduate" || me.career_stage === "practitioner")
    && me.license_years !== null
    && me.license_years !== undefined
  );
}

function ensureProfileModalDom() {
  if ($("profile-modal")) return;
  document.body.insertAdjacentHTML("beforeend", PROFILE_MODAL_HTML);
}

function readProfileForm() {
  const display_name = $("p-display-name").value.trim();
  const work_hospital = $("p-work-hospital").value.trim();
  const physician_title = $("p-physician-title").value.trim();
  const career_stage = $("p-career-stage").value;
  const licenseRaw = $("p-license-years").value.trim();
  const license_years = licenseRaw === "" ? null : Number(licenseRaw);

  if (!display_name) return { error: "请填写真名" };
  if (!work_hospital) return { error: "请填写工作医院" };
  if (!physician_title) return { error: "请填写医师职称" };
  if (!career_stage) return { error: "请选择身份类型" };
  if (license_years === null || Number.isNaN(license_years) || license_years < 0 || license_years > 80) {
    return { error: "请填写取得执业医师资格证后的时间（0-80 年，未取得填 0）" };
  }
  return { display_name, work_hospital, physician_title, career_stage, license_years };
}

function fillProfileForm(me) {
  $("p-display-name").value = me.display_name || "";
  $("p-work-hospital").value = me.work_hospital || "";
  $("p-physician-title").value = me.physician_title || "";
  $("p-career-stage").value = me.career_stage || "";
  $("p-license-years").value = me.license_years ?? "";
  $("profile-feedback").textContent = "";
}

function showProfileModal(me) {
  ensureProfileModalDom();
  const modal = $("profile-modal");
  if (!modal) return Promise.resolve(me);

  if (pendingProfilePromise && !modal.classList.contains("hidden")) {
    return pendingProfilePromise;
  }
  pendingProfilePromise = null;

  fillProfileForm(me);
  modal.classList.remove("hidden");
  document.body.classList.add("profile-gate-active");
  $("body-after-auth")?.classList.add("hidden");

  pendingProfilePromise = new Promise((resolve) => {
    const form = $("profile-form");
    const submitBtn = $("profile-submit-btn");

    async function onSubmit(e) {
      e.preventDefault();
      const profile = readProfileForm();
      const feedback = $("profile-feedback");
      if (profile.error) {
        feedback.textContent = profile.error;
        feedback.dataset.kind = "error";
        return;
      }
      submitBtn.disabled = true;
      feedback.textContent = "";
      try {
        const updated = await apiPatch("/api/me", profile);
        modal.classList.add("hidden");
        document.body.classList.remove("profile-gate-active");
        $("body-after-auth")?.classList.remove("hidden");
        form.removeEventListener("submit", onSubmit);
        pendingProfilePromise = null;
        resolve(updated);
      } catch (err) {
        feedback.textContent = err.message || "保存失败";
        feedback.dataset.kind = "error";
        submitBtn.disabled = false;
      }
    }

    form.addEventListener("submit", onSubmit);
  });

  return pendingProfilePromise;
}

export async function ensureProfileComplete(me) {
  if (!isProfileIncomplete(me)) return me;
  return showProfileModal(me);
}

export async function requireLoggedInWithProfile() {
  const me = await fetchMe();
  if (!me) {
    window.location.href = "/login";
    return null;
  }
  return ensureProfileComplete(me);
}

export async function recoverFromProfileApiError(error) {
  if (error?.status !== 403 || error.message !== "请先完善个人资料") return null;
  const me = await fetchMe();
  if (!me) return null;
  return ensureProfileComplete(me);
}

window.addEventListener("profile:required", () => {
  fetchMe()
    .then((me) => {
      if (me && isProfileIncomplete(me)) return showProfileModal(me);
      return me;
    })
    .catch(() => {});
});
