(function attachEdgeIQUi(global) {
  const DISPLAY_TIME_ZONE = "America/New_York";

  function friendlyStatus(value) {
    return String(value || "unknown")
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  }

  function sortProviderHealth(providers) {
    const rank = { missing_key: 0, not_configured: 1, error: 2, degraded: 3, connected: 4, available: 5 };
    return [...(providers || [])].sort((a, b) => {
      const difference = (rank[a.status] ?? 9) - (rank[b.status] ?? 9);
      return difference || String(a.name || "").localeCompare(String(b.name || ""));
    });
  }

  function sortNotifications(notifications) {
    const rank = { danger: 0, warning: 1, watch: 2, positive: 3, neutral: 4 };
    return [...(notifications || [])].sort((a, b) => {
      const difference = (rank[a.severity] ?? 9) - (rank[b.severity] ?? 9);
      return difference || String(a.type || "").localeCompare(String(b.type || ""));
    });
  }

  function money(value) {
    return `$${Number(value || 0).toFixed(2)}`;
  }

  function pct(value) {
    return `${Number(value || 0).toFixed(1)}%`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function parseEdgeIQTime(value) {
    if (!value) return null;
    const text = String(value).trim();
    if (!text || text === "Time unavailable") return null;
    const isoWithoutZone = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(text);
    return new Date(isoWithoutZone ? `${text}Z` : text);
  }

  function formatDateTime(value) {
    if (!value) return "";
    const date = parseEdgeIQTime(value);
    if (!date || Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      timeZone: DISPLAY_TIME_ZONE,
      month: "long",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZoneName: "short",
    }).format(date);
  }

  function formatGameTime(value) {
    if (!value || value === "Time unavailable") return "Time unavailable";
    const date = parseEdgeIQTime(value);
    if (!date || Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat(undefined, {
      timeZone: DISPLAY_TIME_ZONE,
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
      timeZoneName: "short",
    }).format(date);
  }

  function directionBadge(direction) {
    const normalized = direction === "Under" ? "Under" : "Over";
    const arrow = normalized === "Under" ? "▼" : "▲";
    return `<span class="direction-badge direction-${normalized.toLowerCase()}"><span class="direction-arrow">${arrow}</span>${normalized}</span>`;
  }

  function gradeClass(grade) {
    const normalized = String(grade || "").trim().toLowerCase().charAt(0);
    return ["a", "b", "c", "d", "f"].includes(normalized) ? `grade-${normalized}` : "grade-unknown";
  }

  function dataStrengthBadges(props = []) {
    const rows = props || [];
    if (!rows.length) return "";
    const labels = [];
    rows.forEach((prop) => {
      (prop.data_strength || []).forEach((item) => labels.push({
        label: item.label,
        tone: item.status === "good" ? "positive" : item.status === "warning" ? "warning" : "verified",
      }));
    });
    if (rows.some((prop) => prop.provider_backed || prop.projection_type === "provider-backed" || (!prop.auto_projected && prop.projection_source && prop.projection_source !== "line_model"))) {
      labels.push({ label: "Provider-backed", tone: "positive" });
    }
    if (rows.some((prop) => prop.auto_projected || prop.projection_type === "auto-projected")) {
      labels.push({ label: "Auto-projected", tone: "warning" });
    }
    if (rows.some((prop) => Number(prop.espn?.sample_size || prop.espn_sample_size || prop.hit_rate?.sample_size || 0) > 0 || prop.final_source || prop.actual !== undefined)) {
      labels.push({ label: "Final stats verified", tone: "verified" });
    }
    if (rows.some((prop) => {
      const quality = prop.data_quality || {};
      return Number(quality.score || 100) < 60
        || /thin|low/i.test(String(quality.label || ""))
        || Number(prop.espn?.sample_size || prop.espn_sample_size || prop.hit_rate?.sample_size || 0) === 0;
    })) {
      labels.push({ label: "Thin history", tone: "thin" });
    }
    const unique = [...new Map(labels.map((row) => [row.label, row])).values()];
    if (!unique.length) return "";
    const warningCount = unique.filter((row) => row.tone === "warning" || row.tone === "thin").length;
    const verifiedCount = unique.length - warningCount;
    const tone = warningCount === 0 ? "verified" : verifiedCount > warningCount ? "mixed" : "warning";
    const label = warningCount === 0 ? "Strong evidence" : verifiedCount ? "Mixed evidence" : "Thin evidence";
    const detail = unique.map((row) => row.label).join(" · ");
    return `<div class="data-strength-row"><span class="trust-indicator trust-${tone}" title="${escapeHtml(detail)}"><span class="trust-indicator-dot" aria-hidden="true"></span>${escapeHtml(label)}<small>${unique.length} checks</small></span></div>`;
  }

  global.EdgeIQUi = {
    dataStrengthBadges,
    directionBadge,
    escapeHtml,
    formatDateTime,
    formatGameTime,
    friendlyStatus,
    gradeClass,
    money,
    pct,
    sortNotifications,
    sortProviderHealth,
  };
}(window));
