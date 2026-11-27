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
    return parts.join(" · ");
  }

  return {
    computeToolbarState,
    isPromptModified,
    hasCustomAdvancedSettings,
    shouldConfirmClearQueue,
    formatResultSummary,
  };
});
