(function (root, factory) {
  const exportsObj = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = exportsObj;
  }
  if (root) {
    root.ProductStudioUI = exportsObj;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
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
  }) {
    const runnable = pendingCount + errorCount;
    const retryFailedVisible = errorCount > 0 && !isBatchRunning;
    const zipDisabled = doneCount === 0;

    if (isBatchRunning) {
      return {
        runButton: {
          variant: "danger",
          disabled: false,
          label: stopRequested
            ? "正在停止..."
            : `停止剩余任务 (${doneCount}/${total})`,
        },
        zipButton: {
          variant: "secondary",
          disabled: zipDisabled,
        },
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
        zipButton: {
          variant: doneCount > 0 ? "primary" : "secondary",
          disabled: zipDisabled,
        },
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
        zipButton: {
          variant: "secondary",
          disabled: zipDisabled,
        },
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
        zipButton: {
          variant: "primary",
          disabled: false,
        },
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
      zipButton: {
        variant: "secondary",
        disabled: zipDisabled,
      },
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

  return {
    computeToolbarState,
    isPromptModified,
    hasCustomAdvancedSettings,
    shouldConfirmClearQueue,
    formatResultSummary,
    estimateUnitCostUsd,
    estimateBatchCostUsd,
    formatPreprocessTags,
    formatFriendlyError,
  };
});
