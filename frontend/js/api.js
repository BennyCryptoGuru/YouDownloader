import { errorMessage, t } from "./i18n.js?v=20260831-i18n-settings";

const config = window.YD_CONFIG;

async function request(path, options = {}) {
  const response = await fetch(`${config.apiBase}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Session-Token": config.token,
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = payload.error?.code;
    const message = errorMessage(code, payload.error?.message || t("requestFailed"));
    throw Object.assign(new Error(message), { code });
  }
  return payload;
}

export const api = {
  preview(sourceUrl, scope = "auto") {
    return request("/preview", {
      method: "POST",
      body: JSON.stringify({ sourceUrl, scope }),
    });
  },
  presets() {
    return request("/presets");
  },
  settings() {
    return request("/settings");
  },
  patchSettings(payload) {
    return request("/settings", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
  jobs() {
    return request("/jobs");
  },
  createJob(payload) {
    return request("/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  jobAction(jobId, action) {
    return request(`/jobs/${jobId}/${action}`, { method: "POST" });
  },
  removeJob(jobId) {
    return request(`/jobs/${jobId}`, { method: "DELETE" });
  },
  selectFolder(initialDirectory = null) {
    return request("/dialogs/select-folder", {
      method: "POST",
      body: JSON.stringify({ initialDirectory }),
    });
  },
};

export function eventSocket() {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${scheme}://${window.location.host}${config.apiBase}/events?token=${config.token}`);
}
