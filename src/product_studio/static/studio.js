const CUSTOM_PRESETS_KEY = "product_studio_custom_presets_v1";
const ADVANCED_STORAGE_KEY = "product_studio_advanced_v1";
const INSPECT_STORAGE_KEY = "product_studio_inspect_v1";
const BLANK_IMG = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
const UI = window.ProductStudioUI;

const BUTTON_VARIANT_CLASS = {
  primary: "btn btn-primary",
  danger: "btn btn-danger",
  secondary: "btn",
};

const ADVANCED_FIELDS = [
  { key: "model", id: "modelSelect", prop: "value" },
  { key: "quality", id: "qualitySelect", prop: "value" },
  { key: "concurrency", id: "concurrencySelect", prop: "value" },
  { key: "exportSize", id: "exportSizeSelect", prop: "value" },
  { key: "exportFormat", id: "exportFormatSelect", prop: "value" },
  { key: "autoCrop", id: "optAutoCrop", prop: "checked" },
  { key: "maxEdge", id: "optMaxEdge", prop: "checked" },
  { key: "enhanceSmall", id: "optEnhanceSmall", prop: "checked" },
];

const advancedDefaults = {
  model: "gpt-image-2.5-sunburst",
  quality: "medium",
  concurrency: "2",
  exportSize: "1000x1000",
  exportFormat: "png",
  autoCrop: true,
  maxEdge: true,
  enhanceSmall: true,
};

let builtInPresets = [];
let customPresets = [];
let activePresetId = "aliexpress_white";
let queueItems = [];
let historyItems = [];
let isBatchRunning = false;
let stopRequested = false;
let balanceState = null;
let pasteCounter = 0;
let inspectBg = "white";
let safeFrameOn = false;
let activeCompareUid = null;
let activeCompareMode = "queue";
let activeDialogResolver = null;
let activeDialogMode = "confirm";
let focusReturnEl = null;
let pendingUndoAction = null;
let elapsedTickTimer = null;

function syncHeaderHeight() {
  const headerEl = document.getElementById("studioHeader");
  if (!headerEl) return;
  document.documentElement.style.setProperty("--header-height", `${headerEl.offsetHeight}px`);
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
}

function formatUsd(amount, digits = 2) {
  const num = Number(amount);
  if (!Number.isFinite(num)) return "$0.00";
  return `$${num.toFixed(digits)}`;
}

function isGenerationDisabled() {
  return Boolean(balanceState && balanceState.disabled);
}

function guardGenerationAllowed() {
  if (!isGenerationDisabled()) return true;
  showToast((balanceState && balanceState.disabled_reason) || "余额低于阈值，已禁用生图");
  return false;
}

function formatResetTime(isoString, timezoneName) {
  if (!isoString) return "-";
  const parsed = new Date(isoString);
  if (Number.isNaN(parsed.getTime())) return isoString;
  const targetTz = timezoneName || "UTC";
  try {
    return `${parsed.toLocaleString(undefined, { timeZone: targetTz })} (${targetTz})`;
  } catch {
    return `${parsed.toISOString()} (${targetTz})`;
  }
}

function getFocusableElements(container) {
  return Array.from(
    container.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  ).filter((el) => !el.hidden && el.offsetParent !== null);
}

function trapDialogTab(event, container) {
  if (event.key !== "Tab") return;
  const focusables = getFocusableElements(container);
  if (!focusables.length) return;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function openAppDialog({ title, message, detail = "", mode = "confirm", defaultValue = "", confirmLabel = "确认", confirmVariant = "primary" }) {
  return new Promise((resolve) => {
    focusReturnEl = document.activeElement;
    activeDialogResolver = resolve;
    activeDialogMode = mode;

    document.getElementById("appDialogTitle").textContent = title;
    document.getElementById("appDialogMessage").textContent = message;

    const detailEl = document.getElementById("appDialogDetail");
    detailEl.hidden = !detail;
    detailEl.textContent = detail;

    const inputWrap = document.getElementById("appDialogInputWrap");
    const inputEl = document.getElementById("appDialogInput");
    inputWrap.hidden = mode !== "prompt";
    inputEl.value = defaultValue;

    const confirmBtn = document.getElementById("appDialogConfirmBtn");
    confirmBtn.textContent = confirmLabel;
    confirmBtn.className = confirmVariant === "danger" ? "btn btn-sm btn-danger" : "btn btn-sm btn-primary";

    const dialog = document.getElementById("appDialog");
    dialog.classList.add("open");
    requestAnimationFrame(() => {
      if (mode === "prompt") {
        inputEl.focus();
        inputEl.select();
      } else {
        confirmBtn.focus();
      }
    });
  });
}

function confirmAppDialog() {
  if (activeDialogMode === "prompt") {
    const val = document.getElementById("appDialogInput").value.trim();
    if (!val) {
      showToast("请输入模板名称");
      document.getElementById("appDialogInput").focus();
      return;
    }
    resolveAppDialog(val);
  } else {
    resolveAppDialog(true);
  }
}

function resolveAppDialog(result) {
  const dialog = document.getElementById("appDialog");
  dialog.classList.remove("open");
  const resolver = activeDialogResolver;
  activeDialogResolver = null;
  if (focusReturnEl && typeof focusReturnEl.focus === "function") {
    focusReturnEl.focus();
    focusReturnEl = null;
  }
  if (resolver) resolver(result);
}

function showToast(message, options = {}) {
  const toastEl = document.getElementById("toast");
  const textEl = document.getElementById("toastText");
  const actionBtn = document.getElementById("toastActionBtn");
  textEl.textContent = message;
  pendingUndoAction = typeof options.onAction === "function" ? options.onAction : null;

  if (options.actionLabel && pendingUndoAction) {
    actionBtn.textContent = options.actionLabel;
    actionBtn.hidden = false;
    actionBtn.onclick = () => {
      const fn = pendingUndoAction;
      pendingUndoAction = null;
      toastEl.classList.remove("show");
      actionBtn.hidden = true;
      clearTimeout(showToast.timer);
      if (fn) fn();
    };
  } else {
    actionBtn.hidden = true;
    actionBtn.onclick = null;
  }

  toastEl.classList.add("show");
  clearTimeout(showToast.timer);
  const duration = options.duration || (pendingUndoAction ? 5000 : 2800);
  showToast.timer = setTimeout(() => {
    toastEl.classList.remove("show");
    pendingUndoAction = null;
  }, duration);
}

function setInspectBg(bg) {
  if (!["white", "checker", "dark"].includes(bg)) return;
  inspectBg = bg;
  document.body.dataset.inspectBg = bg;
  document.getElementById("sliderStage").dataset.inspectBg = bg;
  document.querySelectorAll(".seg-btn[data-bg]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.bg === bg);
  });
  saveInspectPreferences();
}

function toggleSafeFrame() {
  safeFrameOn = !safeFrameOn;
  const state = safeFrameOn ? "on" : "off";
  document.body.dataset.safeFrame = state;
  document.getElementById("sliderStage").dataset.safeFrame = state;
  ["safeFrameToggle", "historySafeFrameToggle", "modalSafeFrameToggle"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.setAttribute("aria-pressed", safeFrameOn ? "true" : "false");
  });
  saveInspectPreferences();
}

function loadInspectPreferences() {
  try {
    const raw = localStorage.getItem(INSPECT_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (parsed.bg) setInspectBg(parsed.bg);
    if (parsed.safeFrame) {
      safeFrameOn = false;
      toggleSafeFrame();
    }
  } catch {}
}

function saveInspectPreferences() {
  try {
    localStorage.setItem(INSPECT_STORAGE_KEY, JSON.stringify({ bg: inspectBg, safeFrame: safeFrameOn }));
  } catch {}
}

function togglePromptSize() {
  const textarea = document.getElementById("promptInput");
  const btn = document.getElementById("togglePromptSizeBtn");
  const expanded = textarea.classList.toggle("expanded");
  btn.textContent = expanded ? "收起高度" : "展开编辑区";
  btn.setAttribute("aria-expanded", expanded ? "true" : "false");
}

function isStaleBalanceSnapshot(current, incoming) {
  if (!current || !incoming) return false;
  if (!current.configured || !incoming.configured) return false;
  if (
    current.key_fingerprint !== incoming.key_fingerprint ||
    current.billing_month !== incoming.billing_month
  ) {
    return false;
  }
  const curCount = Number(current.request_count || 0);
  const nextCount = Number(incoming.request_count || 0);
  if (nextCount < curCount) return true;
  if (nextCount === curCount && Number(incoming.used_usd || 0) < Number(current.used_usd || 0)) {
    return true;
  }
  return false;
}

function renderBalancePopover(nextBalance) {
  const listEl = document.getElementById("balancePopoverList");
  if (!nextBalance || !nextBalance.configured) {
    listEl.innerHTML = `<dt>状态</dt><dd>${escapeHtml((nextBalance && nextBalance.disabled_reason) || "未检测到 API_KEY")}</dd>`;
    return;
  }
  const rows = [
    ["当前账期", `${nextBalance.billing_month} (${nextBalance.timezone || "UTC"})`],
    ["本月已用", `${formatUsd(nextBalance.used_usd, 3)} / ${formatUsd(nextBalance.monthly_budget_usd, 2)}`],
    ["累计调用", `${nextBalance.request_count || 0} 次`],
    ["预警 / 禁用阈值", `${formatUsd(nextBalance.warn_threshold_usd, 2)} / ${formatUsd(nextBalance.disable_threshold_usd, 2)}`],
    ["下次重置", formatResetTime(nextBalance.next_reset_at, nextBalance.timezone)],
  ];
  if (nextBalance.offset_used_usd > 0) {
    rows.splice(2, 0, ["外部校准偏移", formatUsd(nextBalance.offset_used_usd, 2)]);
  }
  listEl.innerHTML = rows
    .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`)
    .join("");
}

function toggleBalancePopover(forceOpen) {
  const btn = document.getElementById("balanceStatus");
  const pop = document.getElementById("balancePopover");
  const nextOpen = typeof forceOpen === "boolean" ? forceOpen : pop.hidden;
  pop.hidden = !nextOpen;
  btn.setAttribute("aria-expanded", nextOpen ? "true" : "false");
}

function updateBalanceUI(nextBalance, options = {}) {
  if (!nextBalance || typeof nextBalance !== "object") return;
  if (!options.authoritative && isStaleBalanceSnapshot(balanceState, nextBalance)) {
    return;
  }
  balanceState = nextBalance;
  const pillEl = document.getElementById("balanceStatus");
  const pillTextEl = document.getElementById("balanceStatusText");
  const bannerEl = document.getElementById("balanceBanner");
  const bannerTextEl = document.getElementById("balanceBannerText");

  renderBalancePopover(nextBalance);

  if (!nextBalance.configured) {
    pillEl.className = "pill balance-pill err";
    pillTextEl.textContent = "未配置 API_KEY";
    bannerEl.classList.remove("show");
    syncToolbarUI();
    return;
  }

  const remaining = formatUsd(nextBalance.remaining_usd, 2);
  const budget = formatUsd(nextBalance.monthly_budget_usd, 2);
  const disableThreshold = formatUsd(nextBalance.disable_threshold_usd, 2);

  if (nextBalance.disabled || nextBalance.status === "disabled") {
    pillEl.className = "pill balance-pill err";
    pillTextEl.textContent = `余额不足 ${remaining}（已禁用）`;
    bannerTextEl.innerHTML =
      `<strong>生图功能已暂停：</strong>${escapeHtml(nextBalance.disabled_reason || `当前估算余额 ${remaining} 已触及禁用阈值 ${disableThreshold}。`)}` +
      `<span>历史记录浏览与图片 / ZIP 下载仍可正常使用。</span>`;
    bannerEl.classList.add("show");
  } else if (nextBalance.status === "warn") {
    pillEl.className = "pill balance-pill warn";
    pillTextEl.textContent = `余额 ${remaining} / ${budget}`;
    bannerEl.classList.remove("show");
  } else {
    pillEl.className = "pill balance-pill ok";
    pillTextEl.textContent = `余额 ${remaining} / ${budget}`;
    bannerEl.classList.remove("show");
  }
  syncToolbarUI();
  updateAllCardButtons();
}

async function refreshBalance() {
  try {
    const response = await fetch("/api/balance");
    if (!response.ok) return;
    const data = await response.json();
    updateBalanceUI(data, { authoritative: true });
  } catch {}
}

function loadCustomPresets() {
  try {
    const saved = localStorage.getItem(CUSTOM_PRESETS_KEY);
    customPresets = saved ? JSON.parse(saved) : [];
  } catch {
    customPresets = [];
  }
}

function saveCustomPresetsToStorage() {
  localStorage.setItem(CUSTOM_PRESETS_KEY, JSON.stringify(customPresets));
}

function getAllPresets() {
  return [...builtInPresets, ...customPresets];
}

function getActivePreset() {
  return getAllPresets().find((item) => item.id === activePresetId) || null;
}

function renderPresets() {
  const container = document.getElementById("presetGrid");
  container.innerHTML = "";
  for (const preset of getAllPresets()) {
    const wrapper = document.createElement("div");
    wrapper.className = "preset-item" + (preset.custom ? " is-custom" : "");

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "preset-card" + (preset.id === activePresetId ? " active" : "");
    btn.setAttribute("aria-pressed", preset.id === activePresetId ? "true" : "false");
    btn.onclick = () => selectPreset(preset.id);

    const nameEl = document.createElement("span");
    nameEl.className = "preset-card-name";
    nameEl.textContent = preset.name;
    btn.appendChild(nameEl);

    if (preset.tag) {
      const tagEl = document.createElement("span");
      tagEl.className = "preset-card-tag";
      tagEl.textContent = preset.tag;
      btn.appendChild(tagEl);
    }

    if (preset.description) {
      const descEl = document.createElement("span");
      descEl.className = "preset-card-desc";
      descEl.textContent = preset.description;
      btn.appendChild(descEl);
    }

    wrapper.appendChild(btn);

    if (preset.custom) {
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "preset-del-btn";
      delBtn.setAttribute("aria-label", `删除模板 ${preset.name}`);
      delBtn.title = "删除模板";
      delBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
      delBtn.onclick = () => deleteCustomPreset(preset);
      wrapper.appendChild(delBtn);
    }

    container.appendChild(wrapper);
  }
}

function deleteCustomPreset(preset) {
  const prevList = [...customPresets];
  const prevActive = activePresetId;
  customPresets = customPresets.filter((item) => item.id !== preset.id);
  saveCustomPresetsToStorage();
  if (activePresetId === preset.id && builtInPresets.length) {
    applyPresetImmediate(builtInPresets[0]);
  } else {
    renderPresets();
  }
  showToast(`已删除模板“${preset.name}”`, {
    actionLabel: "撤销",
    onAction: () => {
      customPresets = prevList;
      saveCustomPresetsToStorage();
      activePresetId = prevActive;
      renderPresets();
      syncPromptEditorState();
      showToast("已恢复模板");
    },
  });
}

function applyPresetImmediate(found) {
  activePresetId = found.id;
  document.getElementById("promptInput").value = found.prompt;
  document.getElementById("activePresetDesc").textContent =
    found.description || "可直接修改下方提示词或输入自定义要求";
  syncPromptEditorState();
  renderPresets();
}

async function selectPreset(presetId, options = {}) {
  const found = getAllPresets().find((item) => item.id === presetId);
  if (!found) return;
  if (!options.force && found.id !== activePresetId) {
    const active = getActivePreset();
    const currentText = document.getElementById("promptInput").value;
    if (active && UI.isPromptModified(currentText, active.prompt)) {
      const confirmed = await openAppDialog({
        title: "覆盖已修改的提示词？",
        message: `你修改了当前提示词，切换到“${found.name}”将覆盖已编辑的内容。`,
        confirmLabel: "覆盖并切换",
      });
      if (!confirmed) return;
    }
  }
  applyPresetImmediate(found);
}

function resetPromptToPreset() {
  const found = getActivePreset();
  if (!found) return;
  applyPresetImmediate(found);
  showToast("已恢复当前场景默认提示词");
}

async function saveCustomPreset() {
  const text = document.getElementById("promptInput").value.trim();
  if (!text) {
    showToast("提示词不能为空");
    return;
  }
  const name = await openAppDialog({
    title: "保存为自定义模板",
    message: "给当前提示词起一个便于识别的名称，后续可一键复用：",
    mode: "prompt",
    defaultValue: "我的白底模板",
    confirmLabel: "保存模板",
  });
  if (!name) return;
  const newPreset = {
    id: "custom_" + Date.now(),
    name,
    tag: "自定义模板",
    description: text.slice(0, 64) + (text.length > 64 ? "…" : ""),
    prompt: text,
    custom: true,
  };
  customPresets.push(newPreset);
  saveCustomPresetsToStorage();
  activePresetId = newPreset.id;
  document.getElementById("activePresetDesc").textContent = newPreset.description;
  renderPresets();
  syncPromptEditorState();
  showToast(`已保存模板“${name}”`);
}

function syncPromptEditorState() {
  const text = document.getElementById("promptInput").value;
  document.getElementById("promptCharCount").textContent = `${text.length} 字符`;
  const activePreset = getActivePreset();
  const modified = activePreset
    ? UI.isPromptModified(text, activePreset.prompt)
    : text.trim().length > 0;
  document.getElementById("promptModifiedBadge").hidden = !modified;
  document.getElementById("resetPromptBtn").disabled = !modified || !activePreset;
}

function readAdvancedSettings() {
  const settings = {};
  for (const field of ADVANCED_FIELDS) {
    const el = document.getElementById(field.id);
    if (field.key === "model" && el.options.length === 0) {
      settings[field.key] = advancedDefaults.model;
      continue;
    }
    settings[field.key] = el[field.prop];
  }
  return settings;
}

function persistAdvancedSettings() {
  try {
    localStorage.setItem(ADVANCED_STORAGE_KEY, JSON.stringify(readAdvancedSettings()));
  } catch {}
}

function restoreAdvancedSettingsFromStorage() {
  try {
    const raw = localStorage.getItem(ADVANCED_STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    for (const field of ADVANCED_FIELDS) {
      if (!(field.key in saved)) continue;
      const el = document.getElementById(field.id);
      if (field.key === "model") {
        const exists = Array.from(el.options).some((opt) => opt.value === saved[field.key]);
        if (!exists) continue;
      }
      el[field.prop] = saved[field.key];
    }
  } catch {}
}

function updateParamSummary() {
  const summaryBtn = document.getElementById("paramSummaryBtn");
  if (!summaryBtn) return;
  const s = readAdvancedSettings();
  const sizeLabel = s.exportSize === "native" ? "1024×1024" : s.exportSize;
  summaryBtn.textContent = `${s.quality} · ${sizeLabel} ${String(s.exportFormat).toUpperCase()} · ${s.concurrency}路并发`;
}

function syncAdvancedDirtyIndicator() {
  const isDirty = UI.hasCustomAdvancedSettings(readAdvancedSettings(), advancedDefaults);
  document.getElementById("advancedDirtyDot").hidden = !isDirty;
  document.getElementById("advancedSettingsBtn").classList.toggle("has-custom", isDirty);
  updateParamSummary();
  syncToolbarUI();
}

function resetAdvancedSettings() {
  for (const field of ADVANCED_FIELDS) {
    document.getElementById(field.id)[field.prop] = advancedDefaults[field.key];
  }
  persistAdvancedSettings();
  syncAdvancedDirtyIndicator();
  showToast("已恢复默认高级设置");
}

function openAdvancedDrawer() {
  focusReturnEl = document.activeElement;
  toggleBalancePopover(false);
  document.getElementById("advancedDrawerBackdrop").classList.add("open");
  requestAnimationFrame(() => document.getElementById("closeAdvancedBtn").focus());
}

function closeAdvancedDrawer() {
  const backdrop = document.getElementById("advancedDrawerBackdrop");
  if (!backdrop.classList.contains("open")) return;
  backdrop.classList.remove("open");
  if (focusReturnEl && typeof focusReturnEl.focus === "function") {
    focusReturnEl.focus();
    focusReturnEl = null;
  }
}

function setGatewayError(message) {
  const statusEl = document.getElementById("gatewayStatus");
  if (!message) {
    statusEl.hidden = true;
    return;
  }
  statusEl.className = "pill err";
  statusEl.innerHTML = `<span class="dot" aria-hidden="true"></span>${escapeHtml(message)}`;
  statusEl.hidden = false;
}

async function initApp() {
  loadCustomPresets();
  const initBanner = document.getElementById("initErrorBanner");
  initBanner.hidden = true;
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    builtInPresets = config.presets || [];
    if (config.default_model) advancedDefaults.model = config.default_model;
    if (config.default_quality) advancedDefaults.quality = config.default_quality;

    const modelSelect = document.getElementById("modelSelect");
    modelSelect.innerHTML = "";
    for (const modelInfo of config.models || []) {
      const option = document.createElement("option");
      option.value = modelInfo.id;
      option.textContent = modelInfo.label;
      if (modelInfo.id === advancedDefaults.model) option.selected = true;
      modelSelect.appendChild(option);
    }
    document.getElementById("qualitySelect").value = advancedDefaults.quality;
    restoreAdvancedSettingsFromStorage();
    syncAdvancedDirtyIndicator();

    setGatewayError(config.api_configured ? "" : "未检测到 API_KEY");
    if (config.balance) {
      updateBalanceUI(config.balance, { authoritative: true });
    }
    if (builtInPresets.length > 0) {
      applyPresetImmediate(builtInPresets[0]);
    }
  } catch {
    setGatewayError("后端连接失败");
    const balanceEl = document.getElementById("balanceStatus");
    balanceEl.className = "pill balance-pill err";
    document.getElementById("balanceStatusText").textContent = "余额读取失败";
    document.getElementById("initErrorText").textContent =
      "无法连接到后端服务（请确认本地服务已启动并已完成访问验证），预设场景与预算暂不可用。";
    initBanner.hidden = false;
  } finally {
    syncHeaderHeight();
  }
}

function addFiles(fileList) {
  const validFiles = Array.from(fileList).filter((file) => file.type.startsWith("image/"));
  if (!validFiles.length) {
    showToast("请选择有效的图片文件（JPG / PNG / WEBP）");
    return;
  }
  const grid = document.getElementById("cardGrid");
  for (const file of validFiles) {
    const previewUrl = URL.createObjectURL(file);
    const name = file.name || `粘贴图片_${++pasteCounter}.png`;
    const item = {
      uid: "item_" + Math.random().toString(36).slice(2, 10),
      file,
      name,
      previewUrl,
      status: "pending",
      startedAt: null,
      result: null,
      error: "",
    };
    queueItems.push(item);
    grid.appendChild(createCardElement(item));
  }
  syncToolbarUI();
  showToast(`已加入 ${validFiles.length} 张图片`);
}

function getStatusBadgeInfo(item) {
  if (item.status === "running") {
    const sec = item.startedAt ? Math.max(0, Math.floor((Date.now() - item.startedAt) / 1000)) : 0;
    return [`生成中 ${sec}s`, "badge-running"];
  }
  if (item.status === "done") return ["已完成", "badge-done"];
  if (item.status === "error") return ["失败", "badge-error"];
  return ["待生成", "badge-pending"];
}

function buildCardInnerHtml(item) {
  const generationDisabled = isGenerationDisabled();
  const [badgeText, badgeClass] = getStatusBadgeInfo(item);

  let resultHtml = "";
  if (item.status === "done" && item.result) {
    resultHtml = `
      <button type="button" class="img-pane-trigger" aria-label="打开 ${escapeHtml(item.name)} 原图与白底成品对比" onclick="openCompareModal('${item.uid}')">
        <img src="${item.result.url}?t=${item.result.created_at}" alt="${escapeHtml(item.name)} 白底成品" />
        <span class="safe-frame-guide" aria-hidden="true"></span>
        <span class="pane-label">白底成品</span>
      </button>
    `;
  } else if (item.status === "running") {
    const sec = item.startedAt ? Math.max(0, Math.floor((Date.now() - item.startedAt) / 1000)) : 0;
    resultHtml = `<div class="placeholder-state"><div class="spinner"></div><span>棚拍白底生成中（${sec}s）...</span></div>`;
  } else if (item.status === "error") {
    resultHtml = `<div class="placeholder-state"><span style="color:var(--danger);font-weight:700;">生成失败</span><span>可点击下方重试</span></div>`;
  } else {
    resultHtml = `<div class="placeholder-state"><span>等待开始</span></div>`;
  }

  let metaHtml = "";
  if (item.result) {
    const tags = UI.formatPreprocessTags(item.result.preprocess);
    const tagHtml = tags.length
      ? `<div class="meta-tags">${tags.map((t) => `<span class="meta-tag">${escapeHtml(t)}</span>`).join("")}</div>`
      : "";
    metaHtml = `<div>成品：${escapeHtml(UI.formatResultSummary(item.result))}</div>${tagHtml}`;
  } else if (item.error) {
    metaHtml = `<div class="error-msg">${escapeHtml(item.error)}</div>`;
  } else {
    metaHtml = `<div>原图大小：${(item.file.size / 1024).toFixed(1)} KB</div>`;
  }

  return `
    <div class="item-header">
      <span class="item-title" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</span>
      <span class="badge ${badgeClass}">${badgeText}</span>
    </div>
    <div class="compare-pair">
      <div class="img-pane">
        <img src="${item.previewUrl}" alt="${escapeHtml(item.name)} 原图" />
        <span class="pane-label">原图</span>
      </div>
      <div class="img-pane result-pane">
        ${resultHtml}
      </div>
    </div>
    <div class="item-meta">${metaHtml}</div>
    <div class="item-footer">
      <div class="item-footer-group">
        ${item.result ? `<button class="btn btn-sm" type="button" onclick="openCompareModal('${item.uid}')">滑块对比</button>` : ""}
        <button class="btn btn-sm" type="button" data-role="single-run" onclick="runSingleItem('${item.uid}')" ${(item.status === "running" || generationDisabled) ? "disabled" : ""}>${item.result ? "重生成" : "单张生成"}</button>
      </div>
      <div class="item-footer-group">
        ${item.result ? `<a class="btn btn-sm btn-primary" href="${item.result.url}" download="${escapeHtml(item.result.filename)}">下载</a>` : ""}
        <button class="btn btn-sm btn-subtle-danger" type="button" onclick="removeItem('${item.uid}')" ${item.status === "running" ? "disabled" : ""}>移除</button>
      </div>
    </div>
  `;
}

function createCardElement(item) {
  const card = document.createElement("article");
  card.className = "item-card";
  card.dataset.uid = item.uid;
  card.innerHTML = buildCardInnerHtml(item);
  return card;
}

function patchCardElement(item) {
  const card = document.querySelector(`.item-card[data-uid="${item.uid}"]`);
  if (card) {
    card.innerHTML = buildCardInnerHtml(item);
  } else {
    document.getElementById("cardGrid").appendChild(createCardElement(item));
  }
}

function updateAllCardButtons() {
  const disabled = isGenerationDisabled();
  for (const item of queueItems) {
    const btn = document.querySelector(`.item-card[data-uid="${item.uid}"] button[data-role="single-run"]`);
    if (btn) btn.disabled = item.status === "running" || disabled;
  }
}

function syncRunningTimer() {
  const hasRunning = queueItems.some((item) => item.status === "running");
  if (hasRunning && !elapsedTickTimer) {
    elapsedTickTimer = setInterval(() => {
      for (const item of queueItems) {
        if (item.status !== "running" || !item.startedAt) continue;
        const sec = Math.max(0, Math.floor((Date.now() - item.startedAt) / 1000));
        const card = document.querySelector(`.item-card[data-uid="${item.uid}"]`);
        if (!card) continue;
        const badge = card.querySelector(".badge-running");
        if (badge) badge.textContent = `生成中 ${sec}s`;
        const hint = card.querySelector(".placeholder-state span");
        if (hint) hint.textContent = `棚拍白底生成中（${sec}s）...`;
      }
    }, 1000);
  } else if (!hasRunning && elapsedTickTimer) {
    clearInterval(elapsedTickTimer);
    elapsedTickTimer = null;
  }
}

function syncToolbarUI() {
  const dropzone = document.getElementById("dropzone");
  const toolbar = document.getElementById("toolbar");
  const runBtn = document.getElementById("runBatchBtn");

  if (queueItems.length > 0) {
    dropzone.classList.add("compact");
    toolbar.style.display = "flex";
  } else {
    dropzone.classList.remove("compact");
    toolbar.style.display = "none";
  }

  const total = queueItems.length;
  const doneCount = queueItems.filter((item) => item.status === "done").length;
  const runningCount = queueItems.filter((item) => item.status === "running").length;
  const errorCount = queueItems.filter((item) => item.status === "error").length;
  const pendingCount = queueItems.filter((item) => item.status === "pending").length;
  const runnableCount = pendingCount + errorCount;
  const nextChargeCount = runnableCount > 0 ? runnableCount : total;

  const settings = readAdvancedSettings();
  const estUsd = UI.estimateBatchCostUsd(nextChargeCount, settings.model, settings.quality);
  const estHtml = nextChargeCount > 0
    ? `<span class="estimate-pill" title="按所选模型与画质估算">预计约 ${formatUsd(estUsd, 2)}（${nextChargeCount} 张）</span>`
    : "";

  document.getElementById("statsText").innerHTML =
    `<span>共 <strong>${total}</strong> 张</span>` +
    `<span>已完成 <strong style="color:var(--success)">${doneCount}</strong></span>` +
    (runningCount ? `<span>处理中 <strong style="color:var(--accent)">${runningCount}</strong></span>` : "") +
    (errorCount ? `<span>失败 <strong style="color:var(--danger)">${errorCount}</strong></span>` : "") +
    estHtml;

  const percent = total ? Math.round(((doneCount + errorCount) / total) * 100) : 0;
  const progressEl = document.getElementById("progressBar");
  progressEl.style.width = `${percent}%`;
  progressEl.classList.toggle("complete", total > 0 && doneCount === total);

  const generationDisabled = isGenerationDisabled();
  const toolbarState = UI.computeToolbarState({
    total,
    doneCount,
    pendingCount,
    runningCount,
    errorCount,
    isBatchRunning,
    stopRequested,
    generationDisabled,
    apiConfigured: !(balanceState && !balanceState.configured),
  });

  const zipBtn = document.getElementById("zipBtn");
  if (zipBtn.dataset.packing !== "true") {
    zipBtn.disabled = toolbarState.zipButton.disabled;
    zipBtn.className = BUTTON_VARIANT_CLASS[toolbarState.zipButton.variant] || "btn";
  }

  const retryFailedBtn = document.getElementById("retryFailedBtn");
  retryFailedBtn.style.display = toolbarState.retryFailedVisible ? "inline-flex" : "none";
  retryFailedBtn.disabled = generationDisabled;

  runBtn.className = BUTTON_VARIANT_CLASS[toolbarState.runButton.variant] || "btn";
  runBtn.disabled = toolbarState.runButton.disabled;
  runBtn.textContent = toolbarState.runButton.label;
  syncRunningTimer();
}

function renderQueue() {
  const grid = document.getElementById("cardGrid");
  grid.innerHTML = "";
  for (const item of queueItems) {
    grid.appendChild(createCardElement(item));
  }
  syncToolbarUI();
}

function removeItem(uid) {
  const index = queueItems.findIndex((item) => item.uid === uid);
  if (index === -1) return;
  const [removed] = queueItems.splice(index, 1);
  const card = document.querySelector(`.item-card[data-uid="${uid}"]`);
  if (card) card.remove();
  syncToolbarUI();

  const revokeTimer = setTimeout(() => {
    if (!queueItems.some((item) => item.uid === removed.uid) && removed.previewUrl) {
      URL.revokeObjectURL(removed.previewUrl);
    }
  }, 6000);

  showToast(`已移除“${removed.name}”`, {
    actionLabel: "撤销",
    onAction: () => {
      clearTimeout(revokeTimer);
      queueItems.splice(Math.min(index, queueItems.length), 0, removed);
      renderQueue();
      showToast("已恢复图片");
    },
  });
}

async function clearQueue() {
  if (isBatchRunning) {
    showToast("请先停止正在运行的任务");
    return;
  }
  if (UI.shouldConfirmClearQueue(queueItems)) {
    const confirmed = await openAppDialog({
      title: "清空当前队列？",
      message: "列表中包含已生成的白底图，清空后队列将被移除（已生成图片仍可在「历史生成」中查看与下载）。",
      confirmLabel: "确认清空",
      confirmVariant: "danger",
    });
    if (!confirmed) return;
  }
  for (const item of queueItems) {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
  }
  queueItems = [];
  renderQueue();
  showToast("已清空队列");
}

function buildFormData(file) {
  const formData = new FormData();
  formData.append("file", file, file.name || "image.png");
  formData.append("prompt", document.getElementById("promptInput").value.trim());
  formData.append("model", document.getElementById("modelSelect").value);
  formData.append("quality", document.getElementById("qualitySelect").value);
  formData.append("size", "1024x1024");
  formData.append("export_size", document.getElementById("exportSizeSelect").value);
  formData.append("export_format", document.getElementById("exportFormatSelect").value);
  formData.append("auto_crop_screenshot", document.getElementById("optAutoCrop").checked ? "true" : "false");
  formData.append("max_input_edge", document.getElementById("optMaxEdge").checked ? "1024" : "0");
  formData.append("enhance_small", document.getElementById("optEnhanceSmall").checked ? "true" : "false");
  return formData;
}

async function processOneItem(item) {
  item.status = "running";
  item.startedAt = Date.now();
  item.error = "";
  patchCardElement(item);
  syncToolbarUI();
  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      body: buildFormData(item.file),
    });
    let data = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    if (data && data.balance) {
      updateBalanceUI(data.balance);
      if (data.balance.disabled && isBatchRunning) {
        stopRequested = true;
      }
    }
    if (!response.ok) {
      if (response.status === 402 && isBatchRunning) {
        stopRequested = true;
      }
      throw new Error(UI.formatFriendlyError(data.detail || `请求失败 (${response.status})`, response.status));
    }
    item.status = "done";
    item.result = data;
  } catch (err) {
    item.status = "error";
    item.error = UI.formatFriendlyError(err.message || "未知错误");
  } finally {
    item.startedAt = null;
  }
  patchCardElement(item);
  syncToolbarUI();
}

async function runSingleItem(uid) {
  if (!guardGenerationAllowed()) return;
  const promptText = document.getElementById("promptInput").value.trim();
  if (!promptText) {
    showToast("生成提示词不能为空");
    return;
  }
  const item = queueItems.find((entry) => entry.uid === uid);
  if (!item || item.status === "running") return;
  await processOneItem(item);
}

async function startOrStopBatch() {
  if (isBatchRunning) {
    stopRequested = true;
    syncToolbarUI();
    showToast("将在当前请求完成后停止队列");
    return;
  }
  if (!guardGenerationAllowed()) return;
  const promptText = document.getElementById("promptInput").value.trim();
  if (!promptText) {
    showToast("请先输入生成提示词");
    return;
  }
  let targets = queueItems.filter((item) => item.status === "pending" || item.status === "error");
  if (targets.length === 0 && queueItems.length > 0) {
    const settings = readAdvancedSettings();
    const est = UI.estimateBatchCostUsd(queueItems.length, settings.model, settings.quality);
    const active = getActivePreset();
    const confirmed = await openAppDialog({
      title: `重新生成全部 ${queueItems.length} 张？`,
      message: "将按当前提示词与参数重新调用生图接口并产生费用。",
      detail: `预计费用：约 ${formatUsd(est, 2)} · 场景：${active ? active.name : "自定义"} · ${settings.quality} / ${settings.exportSize}`,
      confirmLabel: "开始重新生成",
    });
    if (!confirmed) return;
    for (const item of queueItems) {
      item.status = "pending";
      item.error = "";
      patchCardElement(item);
    }
    targets = [...queueItems];
  }
  if (targets.length === 0) return;

  const startedAt = Date.now();
  isBatchRunning = true;
  stopRequested = false;
  syncToolbarUI();

  const concurrency = parseInt(document.getElementById("concurrencySelect").value, 10) || 2;
  let cursor = 0;

  async function worker() {
    while (!stopRequested && !isGenerationDisabled()) {
      const currentIndex = cursor++;
      if (currentIndex >= targets.length) break;
      await processOneItem(targets[currentIndex]);
    }
  }

  const workers = Array.from({ length: Math.min(concurrency, targets.length) }, () => worker());
  await Promise.all(workers);

  await refreshBalance();
  const stoppedForBalance = isGenerationDisabled();
  const elapsedSec = ((Date.now() - startedAt) / 1000).toFixed(1);
  const doneInRun = targets.filter((t) => t.status === "done").length;
  const costInRun = targets.reduce((sum, t) => sum + (t.result && Number.isFinite(Number(t.result.cost_usd)) ? Number(t.result.cost_usd) : 0), 0);

  isBatchRunning = false;
  stopRequested = false;
  syncToolbarUI();
  showToast(
    stoppedForBalance
      ? "余额已触及禁用阈值，已停止剩余任务"
      : `批量完成：成功 ${doneInRun}/${targets.length} 张 · 耗时 ${elapsedSec}s · 约 ${formatUsd(costInRun, 3)}`,
    { duration: 4200 }
  );
}

function retryFailedItems() {
  if (isBatchRunning || isGenerationDisabled()) return;
  for (const item of queueItems) {
    if (item.status === "error") {
      item.status = "pending";
      patchCardElement(item);
    }
  }
  startOrStopBatch();
}

async function downloadZipByNames(filenames, triggerBtn) {
  if (!filenames.length) return;
  const origLabel = triggerBtn ? triggerBtn.textContent : "";
  if (triggerBtn) {
    triggerBtn.dataset.packing = "true";
    triggerBtn.disabled = true;
    triggerBtn.textContent = "打包中...";
  }
  try {
    const response = await fetch("/api/download-zip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filenames }),
    });
    if (!response.ok) throw new Error("ZIP 打包失败，请稍后重试");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `aliexpress_white_bg_${Date.now()}.zip`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast(`已打包下载 ${filenames.length} 张成品图`);
  } catch (err) {
    showToast(err.message || "下载 ZIP 失败");
  } finally {
    if (triggerBtn) {
      delete triggerBtn.dataset.packing;
      triggerBtn.textContent = origLabel;
      if (triggerBtn.id === "zipBtn") {
        syncToolbarUI();
      } else {
        triggerBtn.disabled = false;
      }
    }
  }
}

function downloadAllZip() {
  const filenames = queueItems.filter((item) => item.status === "done" && item.result).map((item) => item.result.filename);
  downloadZipByNames(filenames, document.getElementById("zipBtn"));
}

function getComparableQueueItems() {
  return queueItems.filter((entry) => entry.status === "done" && entry.result);
}

function renderCompareModalForQueue(item) {
  const list = getComparableQueueItems();
  const idx = list.findIndex((entry) => entry.uid === item.uid);
  activeCompareUid = item.uid;
  activeCompareMode = "queue";

  const stage = document.getElementById("sliderStage");
  stage.classList.remove("single-mode");
  document.getElementById("compareSlider").hidden = false;
  document.getElementById("modalTitle").textContent = `${item.name}（${idx + 1}/${list.length}）`;
  document.getElementById("modalOrigImg").src = item.previewUrl;
  document.getElementById("modalResultImg").src = `${item.result.url}?t=${item.result.created_at}`;
  document.getElementById("modalMetaText").textContent = UI.formatResultSummary(item.result);

  const tags = UI.formatPreprocessTags(item.result.preprocess);
  document.getElementById("modalCropNote").hidden = !tags.includes("已裁长截图");

  const dl = document.getElementById("modalDownloadLink");
  dl.href = item.result.url;
  dl.download = item.result.filename;

  const prevBtn = document.getElementById("modalPrevBtn");
  const nextBtn = document.getElementById("modalNextBtn");
  prevBtn.hidden = list.length <= 1;
  nextBtn.hidden = list.length <= 1;
  prevBtn.disabled = idx <= 0;
  nextBtn.disabled = idx >= list.length - 1;

  updateSlider(50);
}

function openCompareModal(uid) {
  const item = queueItems.find((entry) => entry.uid === uid);
  if (!item || !item.result) return;
  focusReturnEl = document.activeElement;
  renderCompareModalForQueue(item);
  document.getElementById("compareModal").classList.add("open");
  requestAnimationFrame(() => document.getElementById("closeModalBtn").focus());
}

function openHistoryPreviewModal(index) {
  const item = historyItems[index];
  if (!item) return;
  focusReturnEl = document.activeElement;
  activeCompareMode = "history";
  activeCompareUid = String(index);

  const stage = document.getElementById("sliderStage");
  stage.classList.add("single-mode");
  document.getElementById("compareSlider").hidden = true;
  document.getElementById("modalCropNote").hidden = true;
  document.getElementById("modalTitle").textContent = `${item.orig_name}（${index + 1}/${historyItems.length}）`;
  document.getElementById("modalOrigImg").src = BLANK_IMG;
  document.getElementById("modalResultImg").src = item.url;
  document.getElementById("sliderAfterWrap").style.clipPath = "inset(0 0 0 0%)";
  document.getElementById("modalMetaText").textContent = UI.formatResultSummary(item);

  const dl = document.getElementById("modalDownloadLink");
  dl.href = item.url;
  dl.download = item.filename;

  const prevBtn = document.getElementById("modalPrevBtn");
  const nextBtn = document.getElementById("modalNextBtn");
  prevBtn.hidden = historyItems.length <= 1;
  nextBtn.hidden = historyItems.length <= 1;
  prevBtn.disabled = index <= 0;
  nextBtn.disabled = index >= historyItems.length - 1;

  document.getElementById("compareModal").classList.add("open");
  requestAnimationFrame(() => document.getElementById("closeModalBtn").focus());
}

function stepCompareModal(delta) {
  if (activeCompareMode === "history") {
    const next = Number(activeCompareUid) + delta;
    if (next >= 0 && next < historyItems.length) openHistoryPreviewModal(next);
    return;
  }
  const list = getComparableQueueItems();
  const idx = list.findIndex((entry) => entry.uid === activeCompareUid);
  const nextIdx = idx + delta;
  if (nextIdx >= 0 && nextIdx < list.length) renderCompareModalForQueue(list[nextIdx]);
}

function updateSlider(val) {
  const pct = Math.max(0, Math.min(100, Number(val)));
  document.getElementById("compareSlider").value = pct;
  document.getElementById("sliderAfterWrap").style.clipPath = `inset(0 0 0 ${pct}%)`;
  document.getElementById("sliderDivider").style.left = `${pct}%`;
  document.getElementById("sliderHandle").style.left = `${pct}%`;
}

function closeModal() {
  const modal = document.getElementById("compareModal");
  if (!modal.classList.contains("open")) return;
  modal.classList.remove("open");
  activeCompareUid = null;
  if (focusReturnEl && typeof focusReturnEl.focus === "function") {
    focusReturnEl.focus();
    focusReturnEl = null;
  }
}

function switchTab(tab) {
  const isBatch = tab === "batch";
  const tabBatch = document.getElementById("tabBatch");
  const tabHistory = document.getElementById("tabHistory");
  tabBatch.classList.toggle("active", isBatch);
  tabHistory.classList.toggle("active", !isBatch);
  tabBatch.setAttribute("aria-selected", isBatch ? "true" : "false");
  tabHistory.setAttribute("aria-selected", !isBatch ? "true" : "false");
  document.getElementById("batchView").style.display = isBatch ? "flex" : "none";
  document.getElementById("historyView").style.display = !isBatch ? "flex" : "none";
  if (!isBatch) loadHistory();
}

async function loadHistory() {
  const grid = document.getElementById("historyGrid");
  const countPill = document.getElementById("historyCountPill");
  grid.innerHTML = `<div class="panel empty-history">加载历史记录中...</div>`;
  try {
    const response = await fetch("/api/history?limit=40");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    historyItems = data.items || [];
    countPill.textContent = `当前展示 ${historyItems.length} 条（最多 40 条）`;
    if (!historyItems.length) {
      grid.innerHTML = `<div class="panel empty-history">暂无历史生成记录</div>`;
      return;
    }
    grid.innerHTML = "";
    historyItems.forEach((item, index) => {
      const card = document.createElement("article");
      card.className = "item-card";
      card.innerHTML = `
        <div class="item-header">
          <span class="item-title" title="${escapeHtml(item.orig_name)}">${escapeHtml(item.orig_name)}</span>
          <span class="badge badge-done">${escapeHtml(item.output_size)}</span>
        </div>
        <div class="img-pane result-pane">
          <button type="button" class="img-pane-trigger" aria-label="查看大图 ${escapeHtml(item.orig_name)}" onclick="openHistoryPreviewModal(${index})">
            <img src="${item.url}" alt="${escapeHtml(item.orig_name)} 白底成品" />
            <span class="safe-frame-guide" aria-hidden="true"></span>
          </button>
        </div>
        <div class="item-meta">
          <div>${escapeHtml(UI.formatResultSummary(item))}</div>
        </div>
        <div class="item-footer">
          <span class="tabular" style="font-size:11px;color:var(--text-3);">${new Date(item.created_at * 1000).toLocaleString()}</span>
          <div class="item-footer-group">
            <button class="btn btn-sm" type="button" onclick="openHistoryPreviewModal(${index})">质检大图</button>
            <a class="btn btn-sm btn-primary" href="${item.url}" download="${escapeHtml(item.filename)}">下载</a>
          </div>
        </div>
      `;
      grid.appendChild(card);
    });
  } catch {
    grid.innerHTML = `
      <div class="panel empty-history">
        <span>加载历史记录失败，请检查服务连接后重试。</span>
        <button type="button" class="btn btn-sm" onclick="loadHistory()">重新加载</button>
      </div>
    `;
  }
}

function downloadHistoryZip() {
  downloadZipByNames(
    historyItems.map((item) => item.filename),
    document.getElementById("historyZipBtn")
  );
}

function bindStudioEvents() {
  const sliderStageEl = document.getElementById("sliderStage");
  let isDraggingSlider = false;

  function updateSliderFromPointer(clientX) {
    const rect = sliderStageEl.getBoundingClientRect();
    if (!rect.width) return;
    updateSlider(((clientX - rect.left) / rect.width) * 100);
  }

  sliderStageEl.addEventListener("pointerdown", (event) => {
    if (sliderStageEl.classList.contains("single-mode")) return;
    isDraggingSlider = true;
    sliderStageEl.setPointerCapture(event.pointerId);
    updateSliderFromPointer(event.clientX);
  });
  sliderStageEl.addEventListener("pointermove", (event) => {
    if (isDraggingSlider) updateSliderFromPointer(event.clientX);
  });
  sliderStageEl.addEventListener("pointerup", (event) => {
    if (!isDraggingSlider) return;
    isDraggingSlider = false;
    sliderStageEl.releasePointerCapture(event.pointerId);
  });
  sliderStageEl.addEventListener("pointercancel", () => { isDraggingSlider = false; });

  const dropzoneEl = document.getElementById("dropzone");
  const fileInputEl = document.getElementById("fileInput");
  dropzoneEl.addEventListener("click", () => fileInputEl.click());
  fileInputEl.addEventListener("change", (event) => {
    if (event.target.files.length) addFiles(event.target.files);
    event.target.value = "";
  });
  dropzoneEl.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzoneEl.classList.add("dragover");
  });
  dropzoneEl.addEventListener("dragleave", () => dropzoneEl.classList.remove("dragover"));
  dropzoneEl.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzoneEl.classList.remove("dragover");
    if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
  });

  window.addEventListener("paste", (event) => {
    const items = event.clipboardData && event.clipboardData.items;
    if (!items) return;
    const files = [];
    for (const entry of items) {
      if (entry.type.startsWith("image/")) {
        const blob = entry.getAsFile();
        if (blob) files.push(blob);
      }
    }
    if (files.length) addFiles(files);
  });

  document.getElementById("promptInput").addEventListener("input", syncPromptEditorState);
  for (const field of ADVANCED_FIELDS) {
    document.getElementById(field.id).addEventListener("change", () => {
      persistAdvancedSettings();
      syncAdvancedDirtyIndicator();
    });
  }

  document.addEventListener("click", (event) => {
    const pop = document.getElementById("balancePopover");
    const btn = document.getElementById("balanceStatus");
    if (!pop.hidden && !pop.contains(event.target) && !btn.contains(event.target)) {
      toggleBalancePopover(false);
    }
  });

  window.addEventListener("keydown", (event) => {
    const appDialog = document.getElementById("appDialog");
    const compareModal = document.getElementById("compareModal");
    const advancedBackdrop = document.getElementById("advancedDrawerBackdrop");

    if (appDialog.classList.contains("open")) {
      if (event.key === "Escape") return resolveAppDialog(null);
      if (event.key === "Enter" && activeDialogMode === "prompt") {
        event.preventDefault();
        return confirmAppDialog();
      }
      return trapDialogTab(event, appDialog);
    }
    if (compareModal.classList.contains("open")) {
      if (event.key === "Escape") return closeModal();
      if (event.key === "ArrowLeft" && document.activeElement !== document.getElementById("compareSlider")) {
        event.preventDefault();
        return stepCompareModal(-1);
      }
      if (event.key === "ArrowRight" && document.activeElement !== document.getElementById("compareSlider")) {
        event.preventDefault();
        return stepCompareModal(1);
      }
      return trapDialogTab(event, compareModal);
    }
    if (advancedBackdrop.classList.contains("open")) {
      if (event.key === "Escape") return closeAdvancedDrawer();
      return trapDialogTab(event, document.getElementById("advancedDrawer"));
    }
    if (event.key === "Escape") {
      toggleBalancePopover(false);
    } else if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      if (queueItems.length > 0 && !isBatchRunning) {
        event.preventDefault();
        startOrStopBatch();
      }
    }
  });

  window.addEventListener("resize", syncHeaderHeight);
}

window.ProductStudioApp = {
  boot() {
    bindStudioEvents();
    loadInspectPreferences();
    syncHeaderHeight();
    initApp();
  },
};
