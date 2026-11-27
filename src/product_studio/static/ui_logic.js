(function (root, factory) {
  const exportsObj = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = exportsObj;
  }
  if (root) {
    root.ProductStudioUI = exportsObj;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function resolvePrimaryExportMode(doneCount, supportsFolderExport = false) {
    if (doneCount === 1) return "single";
    return supportsFolderExport ? "folder" : "zip";
  }

  function formatPrimaryExportLabel(exportMode, doneCount) {
    if (exportMode === "single") return "下载图片 (1 张)";
    const baseLabel = exportMode === "folder" ? "保存到文件夹" : "打包下载 ZIP";
    return doneCount >= 2 ? `${baseLabel} (${doneCount} 张)` : baseLabel;
  }

  function computeToolbarState({
    total,
    doneCount,
    pendingCount,
    runningCount = 0,
    errorCount,
    isBatchRunning,
    stopRequested,
    generationDisabled,
    apiConfigured,
    supportsFolderExport = false,
    isExporting = false,
  }) {
    const runnable = pendingCount + errorCount;
    const retryFailedVisible = errorCount > 0 && !isBatchRunning;
    const exportMode = resolvePrimaryExportMode(doneCount, supportsFolderExport);
    const exportLabel = formatPrimaryExportLabel(exportMode, doneCount);
    const exportDisabled = doneCount === 0 || isExporting;
    const exportSplitVisible = Boolean(supportsFolderExport && doneCount >= 2);
    const exportSplitDisabled = !exportSplitVisible || isExporting;

    function buildExportState(variant) {
      return {
        exportButton: {
          variant,
          disabled: exportDisabled,
          mode: exportMode,
          label: exportLabel,
        },
        exportSplitVisible,
        exportSplitDisabled,
      };
    }

    if (isBatchRunning) {
      return {
        runButton: {
          variant: "danger",
          disabled: false,
          label: stopRequested
            ? "正在停止..."
            : `停止剩余任务 (${doneCount}/${total})`,
        },
        ...buildExportState("secondary"),
        retryFailedVisible,
      };
    }

    if (generationDisabled) {
      return {
        runButton: {
          variant: "secondary",
          disabled: true,
          label: !apiConfigured ? "未检测到 API_KEY" : "余额不足，已禁用生图",
        },
        ...buildExportState(doneCount > 0 ? "primary" : "secondary"),
        retryFailedVisible,
      };
    }

    if (runningCount > 0 && runnable === 0) {
      return {
        runButton: {
          variant: "secondary",
          disabled: true,
          label: `生成中... (${runningCount} 张)`,
        },
        ...buildExportState("secondary"),
        retryFailedVisible,
      };
    }

    const allDone = total > 0 && runnable === 0 && runningCount === 0 && doneCount > 0;
    if (allDone) {
      return {
        runButton: {
          variant: "secondary",
          disabled: false,
          label: `重新生成全部 (${total} 张)`,
        },
        ...buildExportState("primary"),
        retryFailedVisible,
      };
    }

    return {
      runButton: {
        variant: "primary",
        disabled: total === 0,
        label:
          runnable > 0
            ? `开始批量生成 (${runnable} 张待处理)`
            : "请先上传图片",
      },
      ...buildExportState("secondary"),
      retryFailedVisible,
    };
  }

  function isPromptModified(currentText, presetPrompt) {
    const normalizedCurrent = String(currentText || "").trim();
    const normalizedPreset = String(presetPrompt || "").trim();
    return normalizedCurrent !== normalizedPreset;
  }

  function hasCustomAdvancedSettings(current, defaults) {
    if (!current || !defaults) return false;
    const keys = Object.keys(defaults);
    for (const key of keys) {
      if (current[key] !== defaults[key]) {
        return true;
      }
    }
    return false;
  }

  function shouldConfirmClearQueue(items) {
    if (!Array.isArray(items)) return false;
    return items.some((item) => item && item.status === "done");
  }

  function formatResultSummary(result) {
    if (!result) return "";
    const parts = [];
    if (result.output_size) parts.push(String(result.output_size));
    if (result.size_kb !== undefined && result.size_kb !== null) {
      parts.push(`${result.size_kb} KB`);
    }
    if (result.elapsed !== undefined && result.elapsed !== null) {
      parts.push(`耗时 ${result.elapsed}s`);
    }
    if (result.cost_usd !== undefined && result.cost_usd !== null) {
      const cost = Number(result.cost_usd);
      if (Number.isFinite(cost)) {
        parts.push(`约 $${cost.toFixed(3)}`);
      }
    }
    return parts.join(" · ");
  }

  const MODEL_UNIT_ESTIMATE_USD = {
    "gpt-image-2.5-sunburst": { low: 0.015, medium: 0.04, high: 0.12 },
    "gpt-image-2.5-flare": { low: 0.015, medium: 0.04, high: 0.12 },
    "gpt-image-2": { low: 0.015, medium: 0.04, high: 0.12 },
    "gpt-image-1.5": { low: 0.018, medium: 0.045, high: 0.13 },
    "gpt-image-1-mini": { low: 0.006, medium: 0.015, high: 0.045 },
  };

  function estimateUnitCostUsd(model, quality) {
    const modelTable =
      MODEL_UNIT_ESTIMATE_USD[model] ||
      MODEL_UNIT_ESTIMATE_USD["gpt-image-2.5-sunburst"];
    return modelTable[quality] || modelTable.medium || 0.04;
  }

  function estimateBatchCostUsd(count, model, quality) {
    const safeCount = Math.max(0, Number(count) || 0);
    return Number((safeCount * estimateUnitCostUsd(model, quality)).toFixed(3));
  }

  function formatPreprocessTags(preprocess) {
    if (!preprocess || !Array.isArray(preprocess.actions)) return [];
    const tags = [];
    for (const raw of preprocess.actions) {
      const text = String(raw || "");
      if (!text) continue;
      if (text.includes("长截图") || text.includes("裁")) {
        if (!tags.includes("已裁长截图")) tags.push("已裁长截图");
      } else if (text.includes("缩放") || text.includes("限")) {
        if (!tags.includes("已限边缩放")) tags.push("已限边缩放");
      } else if (text.includes("锐化") || text.includes("小图")) {
        if (!tags.includes("小图锐化")) tags.push("小图锐化");
      } else if (tags.length < 3) {
        tags.push(text.slice(0, 12));
      }
    }
    return tags;
  }

  function formatFriendlyError(rawMessage, statusCode) {
    const msg = String(rawMessage || "").trim();
    const code = Number(statusCode || 0);
    if (code === 401 || msg.includes("401")) {
      return "鉴权失败（401）：请检查访问密钥或重新登录后重试。";
    }
    if (code === 402 || msg.includes("402") || msg.includes("余额")) {
      return msg || "余额已触及禁用阈值，请调整预算后再试。";
    }
    if (code === 429 || msg.includes("429")) {
      return "请求过于频繁（429）：请降低并发数或稍等几秒后重试失败项。";
    }
    if (code === 504 || msg.includes("超时")) {
      return "单张生成超时（504）：服务繁忙，可点击“重试”重新生成。";
    }
    if (code === 502 || code === 503 || msg.includes("502") || msg.includes("503")) {
      return "上游服务暂时不可用，请稍后重试。";
    }
    if (!msg) return "生成失败，请点击重试。";
    return msg.length > 160 ? msg.slice(0, 160) + "…" : msg;
  }

  const INTERNAL_ID_PREFIX_RE = /^[0-9a-f]{12}_(.+)$/i;

  function basenameOf(rawName) {
    const text = String(rawName || "").trim();
    if (!text) return "";
    const parts = text.split(/[\\/]/);
    return parts[parts.length - 1] || "";
  }

  function deriveExportFilename(itemOrFilename) {
    if (itemOrFilename && typeof itemOrFilename === "object") {
      const explicit = basenameOf(itemOrFilename.export_filename);
      if (explicit) return explicit;
      return deriveExportFilename(itemOrFilename.filename);
    }
    const safeName = basenameOf(itemOrFilename);
    if (!safeName) return "product_white.png";
    const matched = INTERNAL_ID_PREFIX_RE.exec(safeName);
    return matched ? matched[1] : safeName;
  }

  function allocateUniqueExportFilename(desiredName, usedLowerNames) {
    const safeName = basenameOf(desiredName) || "product_white.png";
    const lower = safeName.toLowerCase();
    if (!usedLowerNames.has(lower)) {
      usedLowerNames.add(lower);
      return safeName;
    }
    const dotIndex = safeName.lastIndexOf(".");
    const stem = dotIndex > 0 ? safeName.slice(0, dotIndex) : safeName;
    const ext = dotIndex > 0 ? safeName.slice(dotIndex) : "";
    let counter = 2;
    while (true) {
      const candidate = `${stem}_${counter}${ext}`;
      const candidateLower = candidate.toLowerCase();
      if (!usedLowerNames.has(candidateLower)) {
        usedLowerNames.add(candidateLower);
        return candidate;
      }
      counter += 1;
    }
  }

  function planBatchExportNames(items, existingNames = []) {
    const usedLowerNames = new Set();
    for (const existing of existingNames || []) {
      const safe = basenameOf(existing);
      if (safe) usedLowerNames.add(safe.toLowerCase());
    }
    return (items || []).map((item) => {
      const source = item && item.result ? item.result : item;
      const desired = deriveExportFilename(source);
      const exportName = allocateUniqueExportFilename(desired, usedLowerNames);
      return { item, exportName };
    });
  }

  async function readExistingDirectoryNames(dirHandle) {
    const existing = [];
    if (dirHandle && typeof dirHandle.keys === "function") {
      for await (const name of dirHandle.keys()) {
        existing.push(name);
      }
      return existing;
    }
    if (dirHandle && typeof dirHandle.entries === "function") {
      for await (const [name] of dirHandle.entries()) {
        existing.push(name);
      }
    }
    return existing;
  }

  async function exportItemsToDirectory(items, { pickDirectory, fetchBlob, onProgress }) {
    const list = Array.isArray(items) ? items : [];
    if (list.length === 0) {
      return {
        cancelled: false,
        saved: 0,
        failed: 0,
        total: 0,
        folderName: "",
        savedNames: [],
        errors: [],
      };
    }

    let dirHandle;
    try {
      dirHandle = await pickDirectory();
    } catch (err) {
      if (err && err.name === "AbortError") {
        return {
          cancelled: true,
          saved: 0,
          failed: 0,
          total: list.length,
          folderName: "",
          savedNames: [],
          errors: [],
        };
      }
      throw err;
    }

    const existingNames = await readExistingDirectoryNames(dirHandle);
    const planned = planBatchExportNames(list, existingNames);
    const savedNames = [];
    const errors = [];
    let saved = 0;
    let failed = 0;

    for (let index = 0; index < planned.length; index += 1) {
      const { item, exportName } = planned[index];
      if (typeof onProgress === "function") {
        onProgress({ current: index + 1, total: planned.length, exportName });
      }
      let writable = null;
      let fileCreated = false;
      try {
        const blob = await fetchBlob(item);
        const fileHandle = await dirHandle.getFileHandle(exportName, { create: true });
        fileCreated = true;
        writable = await fileHandle.createWritable();
        await writable.write(blob);
        await writable.close();
        writable = null;
        saved += 1;
        savedNames.push(exportName);
      } catch (err) {
        if (writable && typeof writable.abort === "function") {
          try {
            await writable.abort();
          } catch {
            // ignore cleanup errors
          }
        }
        if (fileCreated && typeof dirHandle.removeEntry === "function") {
          try {
            await dirHandle.removeEntry(exportName);
          } catch {
            // ignore cleanup errors
          }
        }
        failed += 1;
        errors.push({ exportName, message: err && err.message ? err.message : "写入失败" });
      }
    }

    return {
      cancelled: false,
      saved,
      failed,
      total: planned.length,
      folderName: (dirHandle && dirHandle.name) || "",
      savedNames,
      errors,
    };
  }

  return {
    resolvePrimaryExportMode,
    computeToolbarState,
    isPromptModified,
    hasCustomAdvancedSettings,
    shouldConfirmClearQueue,
    formatResultSummary,
    estimateUnitCostUsd,
    estimateBatchCostUsd,
    formatPreprocessTags,
    formatFriendlyError,
    deriveExportFilename,
    planBatchExportNames,
    exportItemsToDirectory,
  };
});
