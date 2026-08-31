import { api, eventSocket } from "./api.js?v=20260831-english-default";
import {
  LANGUAGE_OPTIONS,
  applyDocumentTranslations,
  eta,
  errorMessage,
  getLanguage,
  itemCount,
  normalizeLanguage,
  presetLabel,
  qualityLabel,
  setLanguage,
  statusLabel,
  t,
  themeOptions,
  views,
} from "./i18n.js?v=20260831-english-default";
import {
  bytesPerSecond,
  duration,
} from "./formatters.js?v=20260831-english-default";

const THEME_STORAGE_KEY = "youdownloader-theme";
const THEME_VALUES = new Set([
  "youtube",
  "youtube-dark",
  "classic-light",
  "classic-dark",
  "system",
]);

const state = {
  preview: null,
  previewJobId: null,
  presets: [],
  settings: null,
  jobs: [],
};

const elements = {
  previewForm: document.querySelector("#previewForm"),
  downloadForm: document.querySelector("#downloadForm"),
  sourceUrl: document.querySelector("#sourceUrl"),
  pasteButton: document.querySelector("#pasteButton"),
  loadButton: document.querySelector("#loadButton"),
  previewPanel: document.querySelector("#previewPanel"),
  previewCard: document.querySelector("#previewCard"),
  thumbnail: document.querySelector("#thumbnail"),
  kindBadge: document.querySelector("#kindBadge"),
  durationLabel: document.querySelector("#durationLabel"),
  videoTitle: document.querySelector("#videoTitle"),
  channelLabel: document.querySelector("#channelLabel"),
  statsLabel: document.querySelector("#statsLabel"),
  playlistList: document.querySelector("#playlistList"),
  playlistItems: document.querySelector("#playlistItems"),
  presetSelect: document.querySelector("#presetSelect"),
  qualitySelect: document.querySelector("#qualitySelect"),
  targetDirectory: document.querySelector("#targetDirectory"),
  chooseTargetDir: document.querySelector("#chooseTargetDir"),
  jobList: document.querySelector("#jobList"),
  refreshJobs: document.querySelector("#refreshJobs"),
  toast: document.querySelector("#toast"),
  settingsToggle: document.querySelector("#settingsToggle"),
  settingsDialog: document.querySelector("#settingsDialog"),
  settingsForm: document.querySelector("#settingsForm"),
  defaultDownloadDir: document.querySelector("#defaultDownloadDir"),
  chooseDefaultDir: document.querySelector("#chooseDefaultDir"),
  defaultPreset: document.querySelector("#defaultPreset"),
  defaultQuality: document.querySelector("#defaultQuality"),
  language: document.querySelector("#language"),
  theme: document.querySelector("#theme"),
};

function normalizeTheme(theme) {
  if (THEME_VALUES.has(theme)) return theme;
  if (theme === "light") return "classic-light";
  if (theme === "dark") return "classic-dark";
  return "youtube";
}

function applyTheme(theme) {
  const normalizedTheme = normalizeTheme(theme);
  document.documentElement.dataset.theme = normalizedTheme;
  window.localStorage.setItem(THEME_STORAGE_KEY, normalizedTheme);
  if (elements.theme) elements.theme.value = normalizedTheme;
}

function applyLanguage(language, { rerender = true } = {}) {
  const normalizedLanguage = setLanguage(language);
  if (elements.language) elements.language.value = normalizedLanguage;
  applyDocumentTranslations();
  refreshLocalizedSelects();
  if (state.preview) renderPreview(state.preview);
  if (rerender) renderJobs();
}

applyTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
applyLanguage(getLanguage(), { rerender: false });

function text(node, value) {
  node.textContent = value || "";
}

async function chooseFolderFor(input, fallback = null) {
  const initialDirectory = input.value || fallback || state.settings?.defaultDownloadDir || null;
  input.disabled = true;
  try {
    const response = await api.selectFolder(initialDirectory);
    if (response.path) input.value = response.path;
  } catch (error) {
    showToast(error.message);
  } finally {
    input.disabled = false;
    input.focus();
  }
}

function showToast(message) {
  text(elements.toast, message);
  elements.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    elements.toast.hidden = true;
  }, 4500);
}

function fillSelect(select, items, selected) {
  if (!select) return;
  select.replaceChildren();
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    option.selected = item.value === selected;
    select.append(option);
  }
}

function presetOptions() {
  return state.presets.map((preset) => ({ value: preset.id, label: presetLabel(preset) }));
}

function refreshLocalizedSelects() {
  const presetValue = elements.presetSelect?.value || state.settings?.defaultPreset;
  const qualityValue = elements.qualitySelect?.value || state.settings?.defaultQuality;
  const defaultPresetValue = elements.defaultPreset?.value || state.settings?.defaultPreset;
  const defaultQualityValue = elements.defaultQuality?.value || state.settings?.defaultQuality;
  fillSelect(elements.presetSelect, presetOptions(), presetValue);
  updateQualitySelect(elements.presetSelect, elements.qualitySelect, qualityValue);
  fillSelect(elements.defaultPreset, presetOptions(), defaultPresetValue);
  updateQualitySelect(elements.defaultPreset, elements.defaultQuality, defaultQualityValue);
  fillSelect(elements.language, LANGUAGE_OPTIONS, getLanguage());
  fillSelect(elements.theme, themeOptions(), normalizeTheme(elements.theme?.value || state.settings?.theme));
}

function updateQualitySelect(presetSelect, qualitySelect, selected) {
  const preset = state.presets.find((item) => item.id === presetSelect.value) || state.presets[0];
  const options = (preset?.qualities || []).map((quality) => ({ value: quality, label: qualityLabel(quality) }));
  fillSelect(qualitySelect, options, selected && options.some((item) => item.value === selected) ? selected : options[0]?.value);
}

function renderPreview(preview) {
  state.preview = preview;
  elements.previewPanel.hidden = false;
  elements.downloadForm.hidden = false;
  elements.kindBadge.textContent = preview.kind === "playlist" ? t("playlist") : t("video");
  text(elements.durationLabel, preview.kind === "playlist" ? itemCount(preview.itemCount) : duration(preview.duration));
  text(elements.videoTitle, preview.title);
  text(elements.channelLabel, preview.channel);
  text(elements.statsLabel, views(preview.viewCount));
  elements.thumbnail.src = preview.thumbnailUrl || "";
  elements.thumbnail.alt = preview.title ? t("thumbnailAlt", { title: preview.title }) : "";
  renderPlaylist(preview.items || []);
}

function restorePreviewFromJob(job) {
  state.previewJobId = job.id;
  elements.sourceUrl.value = job.sourceUrl || "";
  elements.targetDirectory.value = job.targetRoot || "";

  if (job.preset) {
    elements.presetSelect.value = job.preset;
    updateQualitySelect(elements.presetSelect, elements.qualitySelect, job.quality);
  }

  renderPreview({
    kind: job.kind,
    sourceUrl: job.sourceUrl,
    id: job.sourceId,
    title: job.title,
    channel: job.channel,
    thumbnailUrl: job.thumbnailUrl,
    itemCount: job.itemCount,
    scopeOptions: [job.kind === "playlist" ? "playlist" : "single"],
    items: (job.items || []).map((item) => ({
      index: item.playlistIndex,
      id: item.sourceId,
      title: item.title,
      duration: null,
    })),
  });
}

function renderPlaylist(items) {
  elements.playlistList.hidden = items.length === 0;
  elements.playlistItems.replaceChildren();
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = `${item.index || ""}. ${item.title}`;
    elements.playlistItems.append(li);
  }
}

function renderJobs() {
  elements.jobList.replaceChildren();
  if (state.jobs.length === 0) {
    const empty = document.createElement("p");
    empty.className = "stats";
    empty.textContent = t("queueEmpty");
    elements.jobList.append(empty);
    return;
  }

  for (const job of state.jobs) {
    const card = document.createElement("article");
    card.className = "job-card";

    const title = document.createElement("h3");
    title.textContent = job.title;
    card.append(title);

    const details = document.createElement("p");
    const count = job.kind === "playlist" ? `, ${job.completedCount || 0}/${job.itemCount || 0}` : "";
    const attempts =
      job.status === "waiting_for_network"
        ? ` · ${t("attempt")} ${Math.min((job.autoAttempts || 0) + 1, job.maxAttempts || 1)}/${job.maxAttempts || 1}`
        : "";
    const currentItem = currentJobItem(job);
    const speed = bytesPerSecond(job.speedBytesPerSecond ?? currentItem?.speedBytesPerSecond);
    const etaLabel = eta(job.etaSeconds ?? currentItem?.etaSeconds);
    const currentPercent = currentItemPercent(job, currentItem);
    const transfer = transferLabel(job, speed, currentPercent, etaLabel);
    details.textContent = `${statusLabel(job.status)}${count}${attempts} · ${job.preset} ${job.quality}`;
    if (transfer) details.textContent = `${details.textContent} · ${transfer}`;
    if (job.status === "failed" && job.errorMessage) {
      details.className = "danger-text";
      details.textContent = `${details.textContent} · ${errorMessage(job.errorCode, job.errorMessage)}`;
    }
    card.append(details);

    if (currentItem) {
      const item = document.createElement("p");
      item.className = "current-item";
      item.textContent = `${t("now")}: ${String(currentItem.playlistIndex || 1).padStart(3, "0")} - ${currentItem.title}`;
      card.append(item);
    }

    const progress = document.createElement("div");
    progress.className = "progress";
    const bar = document.createElement("span");
    bar.style.width = `${displayProgress(job)}%`;
    progress.append(bar);
    card.append(progress);

    const actions = document.createElement("div");
    actions.className = "job-actions";
    for (const action of actionsFor(job)) {
      const button = document.createElement("button");
      button.className = action.className || "secondary-button";
      button.type = "button";
      button.textContent = action.label;
      button.addEventListener("click", async () => {
        try {
          const payload = await api.jobAction(job.id, action.name);
          mergeJob(payload.job);
        } catch (error) {
          showToast(error.message);
        }
      });
      actions.append(button);
    }
    if (canRemoveJob(job)) {
      const removeButton = document.createElement("button");
      removeButton.className = "ghost-button";
      removeButton.type = "button";
      removeButton.textContent = removeJobLabel(job);
      removeButton.addEventListener("click", async () => {
        try {
          await api.removeJob(job.id);
          state.jobs = state.jobs.filter((item) => item.id !== job.id);
          renderJobs();
          showToast(t("jobRemoved"));
        } catch (error) {
          showToast(error.message);
        }
      });
      actions.append(removeButton);
    }
    card.append(actions);
    elements.jobList.append(card);
  }
}

function canRemoveJob(job) {
  return Boolean(job?.id);
}

function removeJobLabel(job) {
  if (["downloading", "postprocessing", "waiting_for_network", "queued", "paused"].includes(job.status)) {
    return t("stopAndRemove");
  }
  return t("remove");
}

function displayProgress(job) {
  if (job.kind !== "playlist") return clampProgress(job.progress || 0);
  const total = Number(job.itemCount || 0);
  if (!total) return 0;
  const completed = Number(job.completedCount || 0);
  const currentFraction = clampProgress(job.progress || 0) / 100;
  return clampProgress(((completed + currentFraction) / total) * 100);
}

function clampProgress(value) {
  return Math.max(0, Math.min(100, Number(value) || 0));
}

function currentItemPercent(job, currentItem) {
  const progress = clampProgress(currentItem?.progress ?? job.progress ?? 0);
  if (progress > 0) return `${formatPercent(progress)} %`;

  const downloadedBytes = Number(currentItem?.downloadedBytes || 0);
  const totalBytes = Number(currentItem?.totalBytes || 0);
  if (downloadedBytes > 0 && totalBytes > 0) {
    return `${formatPercent((downloadedBytes / totalBytes) * 100)} %`;
  }
  return "";
}

function formatPercent(value) {
  const clamped = clampProgress(value);
  if (clamped >= 10 || Number.isInteger(clamped)) return String(Math.round(clamped));
  return clamped.toFixed(1);
}

function transferLabel(job, speed, currentPercent, etaLabel) {
  const parts = [];
  if (speed) parts.push(speed);
  else if (job.status === "downloading") parts.push(t("speedMeasuring"));
  if (currentPercent) {
    parts.push(t("downloadedPercent").replace("{percent}", currentPercent));
  }
  if (etaLabel) parts.push(`${t("remaining")} ${etaLabel}`);
  return parts.join(" · ");
}

function cancelLabel(job) {
  return job.kind === "playlist" ? t("cancelPlaylist") : t("cancelVideo");
}

function actionsFor(job) {
  if (job.status === "completed" || job.status === "cancelled") return [];
  if (job.status === "waiting_for_network") return [{ name: "cancel", label: cancelLabel(job) }];
  if (job.status === "paused") return [{ name: "resume", label: t("resume") }, { name: "cancel", label: cancelLabel(job) }];
  if (job.status === "failed" || job.status === "interrupted") return [{ name: "retry-failed", label: t("retry") }, { name: "cancel", label: cancelLabel(job) }];
  if (job.status === "downloading" || job.status === "postprocessing") return [{ name: "pause", label: t("pause") }, { name: "cancel", label: cancelLabel(job) }];
  return [{ name: "cancel", label: cancelLabel(job) }];
}

function currentJobItem(job) {
  if (!job.items?.length) return null;
  const currentIndex = job.currentItemIndex || 1;
  return job.items.find((item) => item.playlistIndex === currentIndex) || job.items[0];
}

function mergeJob(job) {
  const index = state.jobs.findIndex((item) => item.id === job.id);
  if (index >= 0) state.jobs[index] = job;
  else state.jobs.unshift(job);
  if (state.previewJobId === job.id) restorePreviewFromJob(job);
  renderJobs();
}

async function refreshJobs() {
  const payload = await api.jobs();
  state.jobs = payload.jobs;
  renderJobs();
}

async function loadInitialData() {
  const [settingsPayload, presetsPayload, jobsPayload] = await Promise.all([
    api.settings(),
    api.presets(),
    api.jobs(),
  ]);
  state.settings = settingsPayload;
  state.presets = presetsPayload.presets;
  state.jobs = jobsPayload.jobs;

  applyLanguage(settingsPayload.language, { rerender: false });
  refreshLocalizedSelects();
  elements.defaultDownloadDir.value = settingsPayload.defaultDownloadDir;
  applyTheme(settingsPayload.theme);
  elements.targetDirectory.placeholder = settingsPayload.defaultDownloadDir;
  renderJobs();
  restoreLatestJobPreview();
}

function restoreLatestJobPreview() {
  const priority = [
    "downloading",
    "postprocessing",
    "waiting_for_network",
    "queued",
    "paused",
    "interrupted",
  ];
  const activeJob = state.jobs
    .filter((job) => priority.includes(job.status))
    .sort((a, b) => priority.indexOf(a.status) - priority.indexOf(b.status))[0];
  const latestJob = activeJob || state.jobs[0];
  if (latestJob) restorePreviewFromJob(latestJob);
}

function selectedScope() {
  return "auto";
}

function connectSocket() {
  let delay = 1000;
  let socket = eventSocket();
  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "job.removed") {
      state.jobs = state.jobs.filter((item) => item.id !== payload.jobId);
      renderJobs();
      return;
    }
    if (payload.job) mergeJob(payload.job);
    if (
      payload.jobId &&
      (
        payload.percent !== undefined ||
        payload.speedBytesPerSecond !== undefined ||
        payload.etaSeconds !== undefined ||
        payload.downloadedBytes !== undefined ||
        payload.totalBytes !== undefined
      )
    ) {
      const job = state.jobs.find((item) => item.id === payload.jobId);
      if (job) {
        if (payload.percent !== undefined && payload.percent !== null) {
          job.progress = payload.percent;
        }
        job.status = payload.status || job.status;
        job.currentItemIndex = payload.itemIndex || job.currentItemIndex;
        job.speedBytesPerSecond = payload.speedBytesPerSecond ?? job.speedBytesPerSecond;
        job.etaSeconds = payload.etaSeconds ?? job.etaSeconds;
        const currentItem = currentJobItem(job);
        if (currentItem) {
          if (payload.percent !== undefined && payload.percent !== null) {
            currentItem.progress = payload.percent;
          }
          currentItem.status = payload.status || currentItem.status;
          currentItem.speedBytesPerSecond =
            payload.speedBytesPerSecond ?? currentItem.speedBytesPerSecond;
          currentItem.etaSeconds = payload.etaSeconds ?? currentItem.etaSeconds;
          currentItem.downloadedBytes = payload.downloadedBytes ?? currentItem.downloadedBytes;
          currentItem.totalBytes = payload.totalBytes ?? currentItem.totalBytes;
        }
        renderJobs();
      }
    }
  });
  socket.addEventListener("close", () => {
    window.setTimeout(() => {
      delay = Math.min(delay * 1.7, 12000);
      connectSocket();
      refreshJobs().catch(() => {});
    }, delay);
  });
}

elements.previewForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  elements.loadButton.disabled = true;
  elements.loadButton.textContent = t("loading");
  try {
    const preview = await api.preview(elements.sourceUrl.value, selectedScope());
    state.previewJobId = null;
    renderPreview(preview);
  } catch (error) {
    showToast(error.message);
  } finally {
    elements.loadButton.disabled = false;
    elements.loadButton.textContent = t("load");
  }
});

elements.downloadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.preview) return;
  try {
    const payload = await api.createJob({
      sourceUrl: state.preview.sourceUrl,
      scope: selectedScope(),
      preset: elements.presetSelect.value,
      quality: elements.qualitySelect.value,
      targetDirectory: elements.targetDirectory.value || null,
      conflictPolicy: "skip",
    });
    mergeJob(payload.job);
    showToast(t("jobAdded"));
  } catch (error) {
    showToast(error.message);
  }
});

elements.presetSelect.addEventListener("change", () => updateQualitySelect(elements.presetSelect, elements.qualitySelect));
elements.defaultPreset.addEventListener("change", () => updateQualitySelect(elements.defaultPreset, elements.defaultQuality));
elements.refreshJobs.addEventListener("click", () => refreshJobs().catch((error) => showToast(error.message)));
elements.chooseTargetDir.addEventListener("click", () => chooseFolderFor(elements.targetDirectory));
elements.chooseDefaultDir.addEventListener("click", () => chooseFolderFor(elements.defaultDownloadDir));
elements.theme.addEventListener("change", () => applyTheme(elements.theme.value));
elements.language.addEventListener("change", () => applyLanguage(elements.language.value));
elements.pasteButton.addEventListener("click", async () => {
  try {
    elements.sourceUrl.value = await navigator.clipboard.readText();
  } catch {
    showToast(t("clipboardError"));
  }
});
elements.settingsToggle.addEventListener("click", () => {
  applyTheme(state.settings?.theme || elements.theme.value);
  applyLanguage(state.settings?.language || elements.language.value);
  elements.settingsDialog.returnValue = "";
  elements.settingsDialog.showModal();
});
elements.settingsDialog.addEventListener("close", () => {
  if (elements.settingsDialog.returnValue === "cancel") {
    applyTheme(state.settings?.theme);
    applyLanguage(state.settings?.language);
  }
});
elements.settingsForm.addEventListener("submit", async (event) => {
  if (event.submitter?.value === "cancel") return;
  event.preventDefault();
  try {
    state.settings = await api.patchSettings({
      defaultDownloadDir: elements.defaultDownloadDir.value,
      defaultPreset: elements.defaultPreset.value,
      defaultQuality: elements.defaultQuality.value,
      theme: normalizeTheme(elements.theme.value),
      language: normalizeLanguage(elements.language.value),
    });
    elements.targetDirectory.placeholder = state.settings.defaultDownloadDir;
    applyTheme(state.settings.theme);
    applyLanguage(state.settings.language);
    elements.settingsDialog.close("saved");
    showToast(t("settingsSaved"));
  } catch (error) {
    showToast(error.message);
  }
});

loadInitialData()
  .then(connectSocket)
  .catch((error) => showToast(error.message));
