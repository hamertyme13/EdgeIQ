(function initializeEdgeIQApi(global) {
  const API_BASE = global.location.protocol === "file:" ? "http://127.0.0.1:8007" : "";
  const inflightGetRequests = new Map();
  const $ = (id) => document.getElementById(id);
  const deferWork = global.requestIdleCallback
    ? (task, timeout = 1500) => global.requestIdleCallback(task, { timeout })
    : (task, timeout = 1500) => global.setTimeout(task, Math.min(timeout, 800));

  function humanizeErrorText(value, status = 0) {
    const text = String(value || "").trim();
    if (!text) {
      return status >= 500
        ? "EdgeIQ hit a server issue. Please refresh and try again."
        : "EdgeIQ could not complete that action.";
    }
    const lowered = text.toLowerCase();
    if (lowered.includes("failed to fetch") || lowered.includes("networkerror")) {
      return "EdgeIQ could not reach the app server. Make sure the app is running, then try again.";
    }
    if (lowered.includes("openai_http_401") || lowered.includes("invalid api key")) {
      return "The AI key was not accepted. Check the OpenAI API key in settings.";
    }
    if (lowered.includes("openai_http_429") || lowered.includes("rate limit")) {
      return "The AI service is busy or rate-limited. Try again in a moment.";
    }
    if (lowered.includes("openai_request_error") || lowered.includes("timeout")) {
      return "The AI service did not respond in time. EdgeIQ can still use the local review.";
    }
    if (lowered.includes("traceback") || lowered.includes("exception") || lowered.includes('{"detail"')) {
      return status >= 500
        ? "EdgeIQ hit a server issue. Please refresh and try again."
        : "EdgeIQ could not complete that action. Please check the inputs and try again.";
    }
    return text
      .replace(/^Risk guardrail blocked placement:\s*/i, "Placement blocked: ")
      .replace(/_/g, " ");
  }

  function humanizeApiError(detail, status) {
    const fallback = status >= 500
      ? "Something went wrong on the EdgeIQ server. Please try again after refreshing."
      : "EdgeIQ could not complete that action. Please check the fields and try again.";
    if (!detail) return fallback;
    try {
      const parsed = JSON.parse(detail);
      const apiDetail = parsed.detail ?? parsed.message ?? parsed.error;
      if (Array.isArray(apiDetail)) {
        const fields = apiDetail
          .map((item) => Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(" ") : "")
          .filter(Boolean)
          .slice(0, 3);
        return fields.length
          ? `Please check ${fields.join(", ")} and try again.`
          : "Please check the form values and try again.";
      }
      if (typeof apiDetail === "string") return humanizeErrorText(apiDetail, status);
    } catch (error) {
      return humanizeErrorText(detail, status);
    }
    return fallback;
  }

  async function api(path, options = {}) {
    const method = String(options.method || "GET").toUpperCase();
    const requestKey = method === "GET" ? `${API_BASE}${path}` : "";
    if (requestKey && inflightGetRequests.has(requestKey)) return inflightGetRequests.get(requestKey);
    const request = (async () => {
      const { timeoutMs = method === "GET" ? 20000 : 60000, signal, ...fetchOptions } = options;
      const controller = new AbortController();
      const abortFromCaller = () => controller.abort();
      if (signal) signal.addEventListener("abort", abortFromCaller, { once: true });
      const timeout = window.setTimeout(() => controller.abort(), Math.max(1000, Number(timeoutMs) || 20000));
      try {
        const response = await fetch(`${API_BASE}${path}`, {
          headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
          cache: "no-store",
          ...fetchOptions,
          signal: controller.signal,
        });
        if (!response.ok) {
          const detail = await response.text();
          throw new Error(humanizeApiError(detail, response.status));
        }
        return response.json();
      } catch (error) {
        if (error?.name === "AbortError") {
          throw new Error("This is taking longer than expected. Check provider status, then try again.");
        }
        throw error;
      } finally {
        window.clearTimeout(timeout);
        if (signal) signal.removeEventListener("abort", abortFromCaller);
      }
    })();
    if (requestKey) inflightGetRequests.set(requestKey, request);
    try {
      return await request;
    } finally {
      if (requestKey) inflightGetRequests.delete(requestKey);
    }
  }

  async function withButtonBusy(buttonOrId, busyLabel, task) {
    const button = typeof buttonOrId === "string" ? $(buttonOrId) : buttonOrId;
    if (!button) return task();
    const originalLabel = button.textContent;
    button.disabled = true;
    button.classList.add("is-busy");
    button.textContent = busyLabel;
    try {
      return await task();
    } finally {
      button.disabled = false;
      button.classList.remove("is-busy");
      button.textContent = originalLabel;
    }
  }

  function showRuntimeNotice(message) {
    const notice = $("runtime-notice");
    if (!notice) return;
    notice.textContent = message;
    notice.hidden = false;
  }

  function hideRuntimeNotice() {
    const notice = $("runtime-notice");
    if (notice) notice.hidden = true;
  }

  async function copyText(value) {
    if (!navigator.clipboard?.writeText) return false;
    await navigator.clipboard.writeText(value);
    return true;
  }

  global.EdgeIQApi = {
    $,
    api,
    copyText,
    deferWork,
    hideRuntimeNotice,
    humanizeApiError,
    humanizeErrorText,
    showRuntimeNotice,
    withButtonBusy,
  };
})(window);
