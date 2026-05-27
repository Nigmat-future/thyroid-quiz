// 统一的 fetch 封装：自动带 cookie + 抛业务错误。
// 所有页面通过 ESM import 复用。

export async function api(method, path, body) {
  const opts = {
    method,
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  const ct = res.headers.get("Content-Type") || "";
  if (ct.includes("application/json")) {
    try {
      data = await res.json();
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const detail = data && (data.detail || data.message);
    const msg = typeof detail === "string" ? detail : `请求失败 (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

export const apiGet = (path) => api("GET", path);
export const apiPost = (path, body) => api("POST", path, body);
export const apiPatch = (path, body) => api("PATCH", path, body);
export const apiDelete = (path) => api("DELETE", path);

export async function fetchMe() {
  try {
    return await apiGet("/api/me");
  } catch (e) {
    if (e.status === 401) return null;
    throw e;
  }
}
