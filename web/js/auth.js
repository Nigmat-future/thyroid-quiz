// 登录页 + 注册页共用的脚本。靠 DOM 上的表单 id 区分行为。
import { apiPost } from "./api.js";
import { bindCareerStageField, readCareerFields } from "./career.js";

const $ = (id) => document.getElementById(id);

function showFeedback(text, kind = "error") {
  const el = $("feedback");
  if (!el) return;
  el.textContent = text || "";
  el.dataset.kind = kind;
}

function disable(form, on) {
  const btn = $("submit-btn");
  if (btn) btn.disabled = on;
  Array.from(form.elements).forEach((el) => {
    if (el !== btn) el.disabled = on;
  });
}

function readProfileFields() {
  const display_name = $("display_name").value.trim();
  const work_hospital = $("work_hospital").value.trim();
  const physician_title = $("physician_title").value.trim();
  const licenseRaw = $("license_years").value.trim();
  const license_years = licenseRaw === "" ? null : Number(licenseRaw);
  const career = readCareerFields($("career_stage"), $("career_stage_other"));

  if (!display_name) return { error: "请填写真名" };
  if (!work_hospital) return { error: "请填写工作医院" };
  if (!physician_title) return { error: "请填写医师职称" };
  if (career.error) return career;
  if (license_years === null || Number.isNaN(license_years) || license_years < 0 || license_years > 80) {
    return { error: "请填写取得执业医师资格证后的时间（0-80 年，未取得填 0）" };
  }

  return {
    display_name,
    work_hospital,
    physician_title,
    career_stage: career.career_stage,
    career_stage_other: career.career_stage_other,
    license_years,
  };
}

function bindLogin() {
  const form = $("login-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showFeedback("");
    const payload = {
      username: $("username").value.trim(),
      password: $("password").value,
    };
    if (!payload.username || !payload.password) {
      showFeedback("请填写用户名和密码");
      return;
    }
    disable(form, true);
    try {
      await apiPost("/api/auth/login", payload);
      showFeedback("登录成功，跳转中…", "success");
      window.location.href = "/";
    } catch (err) {
      showFeedback(err.message || "登录失败");
      disable(form, false);
    }
  });
}

function bindRegister() {
  const form = $("register-form");
  if (!form) return;
  bindCareerStageField({
    stageId: "career_stage",
    otherWrapId: "career-other-wrap",
    otherInputId: "career_stage_other",
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showFeedback("");
    const username = $("username").value.trim();
    const password = $("password").value;
    const password2 = $("password2").value;
    const profile = readProfileFields();

    if (profile.error) {
      showFeedback(profile.error);
      return;
    }
    if (password !== password2) {
      showFeedback("两次输入的密码不一致");
      return;
    }
    if (!/^[A-Za-z0-9_]{3,32}$/.test(username)) {
      showFeedback("用户名仅允许 3-32 位字母数字下划线");
      return;
    }
    if (password.length < 6) {
      showFeedback("密码至少 6 位");
      return;
    }

    disable(form, true);
    try {
      await apiPost("/api/auth/register", { username, password, ...profile });
      showFeedback("注册成功，跳转中…", "success");
      window.location.href = "/";
    } catch (err) {
      showFeedback(err.message || "注册失败");
      disable(form, false);
    }
  });
}

bindLogin();
bindRegister();
