const state = window.EdgeIQState;
window.EdgeIQLoaded = true;

const {
  $,
  api,
  copyText,
  deferWork,
  hideRuntimeNotice,
  humanizeErrorText,
  showRuntimeNotice,
  withButtonBusy,
} = window.EdgeIQApi;
const {
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
} = window.EdgeIQUi;
function registerPwa() {
  if ("serviceWorker" in navigator && window.location.protocol !== "file:") {
    let refreshingForNewShell = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (refreshingForNewShell) return;
      refreshingForNewShell = true;
      window.location.reload();
    });
    navigator.serviceWorker.register("/static/sw.js", { updateViaCache: "none" })
      .then((registration) => registration.update())
      .catch((error) => {
        console.warn("EdgeIQ service worker registration failed", error);
      });
  }
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    state.deferredInstallPrompt = event;
    if ($("install-app")) $("install-app").hidden = false;
    if ($("install-hint") && !window.localStorage.getItem("edgeiq-install-dismissed")) {
      $("install-hint").hidden = false;
    }
  });
  window.addEventListener("appinstalled", () => {
    state.deferredInstallPrompt = null;
    if ($("install-app")) $("install-app").hidden = true;
    if ($("install-hint")) $("install-hint").hidden = true;
  });
}

async function installPwa() {
  if (!state.deferredInstallPrompt) {
    $("install-hint").hidden = false;
    $("install-hint").querySelector("span").textContent = "On iPhone, tap Share, then Add to Home Screen.";
    return;
  }
  state.deferredInstallPrompt.prompt();
  await state.deferredInstallPrompt.userChoice;
  state.deferredInstallPrompt = null;
  if ($("install-app")) $("install-app").hidden = true;
}

function applyViewFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view");
  if (view && document.getElementById(view)) setView(view);
}

function playCircuitSound(kind, options = {}) {
  return window.EdgeIQAudio?.play(kind, options) || false;
}

function buttonSoundKind(button) {
  if (!button || button.disabled || button.matches(".circuit-action, #preview-sound")) return "";
  if (button.dataset.sound) return button.dataset.sound;
  if (
    button.matches(".danger, [data-remove-prop]")
    || button.id === "clear-entry"
    || String(button.dataset.settle || "").endsWith(":Loss")
  ) return "delete";
  if (button.dataset.settle) return "select";
  if (
    button.matches(
      ".nav-item, .workspace-tab, .tab-button, [data-view], [data-view-shortcut], "
      + "[data-workspace-jump], [data-briefing-tab], [data-close-drawer]"
    )
  ) return "navigate";

  const signature = [
    button.id,
    button.textContent,
    ...Object.keys(button.dataset),
  ].join(" ").toLowerCase();
  if (/(why|explain|review|detail|research)/.test(signature)) return "inspect";
  if (/(refresh|scan|analy|generate|optimizer|optimize|sync|check|recheck|classify|auto|run|calculat|estimat|project|test)/.test(signature)) {
    return "scan";
  }
  if (/(add|save|load|copy|share|open|import|export|backup|upload|install|enable|prepare|settle|submit|create)/.test(signature)) {
    return "select";
  }
  return "tap";
}

function setupButtonSounds() {
  if (state.buttonSoundsBound) return;
  state.buttonSoundsBound = true;
  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("button") : null;
    const kind = buttonSoundKind(button);
    if (kind) playCircuitSound(kind);
  }, true);
}

function finishCircuitFeedback(button, outcome) {
  if (!button) return;
  button.classList.remove("circuit-shimmer", "circuit-success", "circuit-warning");
  void button.offsetWidth;
  button.classList.add(outcome === "success" ? "circuit-success" : "circuit-warning");
  window.setTimeout(() => {
    button.classList.remove("circuit-success", "circuit-warning");
  }, outcome === "success" ? 950 : 680);
}

function syncEntryActionLabels() {
  const isPaper = ($("entry-mode")?.value || "real") === "paper";
  if ($("place-entry")) $("place-entry").textContent = isPaper ? "Save Paper Entry" : "Place Paid Entry";
  if ($("mobile-place-entry")) $("mobile-place-entry").textContent = isPaper ? "Save Paper Entry" : "Place Paid Entry";
}

async function placeEntryFromButton(button) {
  if (state.placementInFlight || !state.lastEntryPayload) return false;
  state.placementInFlight = true;
  const controls = [$("place-entry"), $("mobile-place-entry")].filter(Boolean);
  const labels = new Map(controls.map((control) => [control, control.textContent]));
  controls.forEach((control) => {
    control.disabled = true;
    control.classList.add("is-busy");
    control.textContent = "Checking...";
  });
  button?.classList.add("circuit-shimmer");
  playCircuitSound("engage");
  let placed = false;
  try {
    placed = await placeEntry(button);
    return placed;
  } finally {
    state.placementInFlight = false;
    controls.forEach((control) => {
      control.classList.remove("is-busy");
      control.textContent = labels.get(control);
    });
    syncEntryActionLabels();
    $("place-entry").disabled = !state.lastEntryPayload;
    $("mobile-place-entry").disabled = state.entryProps.length < 2 || !state.lastEntryPayload;
    if (!placed) window.setTimeout(() => button?.classList.remove("circuit-shimmer"), 160);
  }
}

function handleLoadError(error) {
  const fileHint = window.location.protocol === "file:"
    ? " The page is open from a file, so start the EdgeIQ server and use http://127.0.0.1:8007 for live data."
    : "";
  showRuntimeNotice(`${humanizeErrorText(error?.message || error)}${fileHint}`);
  $("props-status").textContent = "Waiting for app server...";
  console.error(error);
}

function propPickText(prop) {
  const direction = prop.direction || "Over";
  return `<span class="prop-pick-text">${directionBadge(direction)} <span>${escapeHtml(prop.player)} ${escapeHtml(prop.stat)} ${escapeHtml(prop.line)}</span></span>`;
}

function propPickList(props) {
  return (props || []).map(propPickText).join(", ");
}

function shortPropPickText(prop) {
  return `<span class="prop-pick-text">${directionBadge(prop.direction || "Over")} <span>${escapeHtml(prop.player)} ${escapeHtml(prop.stat)}</span></span>`;
}


function modelTrustBadge(suggestion = {}, props = []) {
  if (suggestion.trust?.score !== undefined) {
    return `<span class="model-trust-badge" title="Backend release trust">Model Trust ${Number(suggestion.trust.score || 0).toFixed(0)} · ${escapeHtml(suggestion.trust.label || "No Data")}</span>`;
  }
  const qualityScores = (props || [])
    .map((prop) => Number(prop.data_quality?.score || 0))
    .filter((score) => score > 0);
  const avgQuality = qualityScores.length ? qualityScores.reduce((sum, score) => sum + score, 0) / qualityScores.length : 50;
  const confidence = Number(suggestion.entry?.average_confidence || 0);
  const score = Math.max(0, Math.min(100, Number(suggestion.score || 0) * 0.45 + confidence * 0.35 + avgQuality * 0.2));
  const label = score >= 72 ? "High Trust" : score >= 58 ? "Medium Trust" : "Low Trust";
  return `<span class="model-trust-badge" title="Blend of score, confidence, and data quality">Model Trust ${score.toFixed(0)} · ${label}</span>`;
}

function releaseStatusBlock(release) {
  if (!release || (!release.blocks?.length && !release.warnings?.length)) return "";
  const blocks = release.blocks || [];
  const warnings = release.warnings || [];
  const tone = blocks.length ? "warning" : "subtle";
  return `<p class="${tone}">Release check: ${[...blocks, ...warnings].slice(0, 3).map(escapeHtml).join(" · ")}</p>`;
}

function platformValueBlock(platformValue) {
  if (!platformValue) return "";
  const delta = Number(platformValue.value_delta || 0);
  const recommended = platformValue.recommended_platform || platformValue.selected_platform || "Best app";
  const complete = platformValue.complete_on_recommended_platform ? "Full 3-leg match" : "Partial match";
  const tone = delta > 0 ? "data-positive" : platformValue.complete_on_recommended_platform ? "data-verified" : "data-warning";
  const bestEconomics = (platformValue.platforms || []).find((row) => row.platform === recommended)?.payout_analysis || {};
  return `
    <div class="recommendation-meta-row">
      <span class="data-strength-badge ${tone}">Best App: ${escapeHtml(recommended)}</span>
      <span class="data-strength-badge ${tone}">${complete}</span>
      <span class="data-strength-badge ${tone}">Value ${delta >= 0 ? "+" : ""}${delta.toFixed(2)}</span>
      <span class="data-strength-badge ${Number(bestEconomics.expected_value || 0) > 0 ? "data-positive" : "data-warning"}">EV ${Number(bestEconomics.expected_value || 0) >= 0 ? "+" : ""}${Number(bestEconomics.expected_value || 0).toFixed(1)}%</span>
    </div>
    <p class="${delta > 0 ? "subtle" : "warning"}">${escapeHtml(platformValue.recommendation || "Compare lines manually before placing.")}</p>
  `;
}

function optimizerSummaryBlock(data) {
  const best = data.best_value_pick;
  const obstacles = data.obstacles || [];
  const paidReady = Number(data.paid_ready_count || 0);
  const total = (data.suggestions || []).length;
  const portfolioReady = Number(data.portfolio_ready_count || 0);
  return `
    <div class="suggestion compact-suggestion ${paidReady ? "grade-b" : "grade-f"}">
      <div class="suggestion-top">
        <span class="pill">Best 3-Leg Path</span>
        <strong>${paidReady ? `${paidReady}/${total} paid-ready` : "No paid-ready slip yet"}</strong>
        ${best ? `<span class="subtle">Value score ${Number(best.value_adjusted_score || best.score || 0).toFixed(1)}</span>` : ""}
      </div>
      <p class="subtle">${portfolioReady}/${total} stay within pending player, game, and market limits.</p>
      ${best?.platform_value ? platformValueBlock(best.platform_value) : ""}
      ${obstacles.length ? `<p class="warning">${obstacles.map(escapeHtml).join(" · ")}</p>` : `<p class="subtle">At least one optimized slip cleared the paid-entry release checks.</p>`}
    </div>
  `;
}

function portfolioSuggestionBlock(suggestion) {
  const portfolio = suggestion.portfolio || {};
  const conflicts = portfolio.conflicts || [];
  const replacements = portfolio.replacements || [];
  const tone = portfolio.risk === "High" ? "danger-text" : portfolio.risk === "Medium" ? "warning" : "subtle";
  return `
    <div class="portfolio-card-review risk-${String(portfolio.risk || "Low").toLowerCase()}">
      <div class="suggestion-top">
        <strong>Portfolio ${escapeHtml(portfolio.risk || "Low")} Risk</strong>
        <span class="status-pill ${conflicts.length ? "status-warning" : "status-positive"}">Adjusted ${Number(portfolio.adjusted_score ?? suggestion.value_adjusted_score ?? suggestion.score ?? 0).toFixed(1)}</span>
      </div>
      <p class="${tone}">${escapeHtml(portfolio.summary || "No portfolio assessment available.")}</p>
      ${conflicts.slice(0, 3).map((conflict) => `<p class="subtle">${escapeHtml(conflict.message)}</p>`).join("")}
      ${replacements.map((replacement) => `<p class="portfolio-replacement">${escapeHtml(replacement.message)}</p>`).join("")}
    </div>
  `;
}

function samePortfolioProp(left, right) {
  return String(left?.player || "").toLocaleLowerCase() === String(right?.player || "").toLocaleLowerCase()
    && String(left?.stat || "").toLocaleLowerCase() === String(right?.stat || "").toLocaleLowerCase()
    && String(left?.direction || "Over").toLocaleLowerCase() === String(right?.direction || "Over").toLocaleLowerCase()
    && Number(left?.line || 0) === Number(right?.line || 0);
}

function portfolioAdjustedProps(suggestion) {
  const props = [...(suggestion.entry?.props || [])];
  (suggestion.portfolio?.replacements || []).forEach((replacement) => {
    const index = props.findIndex((prop) => samePortfolioProp(prop, replacement.remove_prop));
    if (index >= 0 && replacement.add) props[index] = replacement.add;
  });
  return props;
}

function confidenceMovementText(prop) {
  const calibration = prop?.forecast_snapshot?.calibration;
  if (!calibration || Number(calibration.sample_size || 0) === 0) return "";
  const adjustment = Number(calibration.probability || 0) - Number(calibration.raw_probability || 0);
  if (Math.abs(adjustment) < 0.1) return "";
  const direction = adjustment > 0 ? "up" : "down";
  return `Why this moved: confidence moved ${direction} ${Math.abs(adjustment).toFixed(1)} pts using ${escapeHtml(calibration.tier || "segment")} calibration from ${Number(calibration.sample_size || 0)} independent results.`;
}

function suggestionMetaRow(suggestion) {
  const props = suggestion?.entry?.props || [];
  return `
    <div class="recommendation-meta-row">
      ${modelTrustBadge(suggestion, props)}
      ${dataStrengthBadges(props)}
    </div>
  `;
}

function confidenceMoveNotes(props = []) {
  return (props || [])
    .map(confidenceMovementText)
    .filter(Boolean)
    .slice(0, 2)
    .map((note) => `<p class="confidence-move-note">${escapeHtml(note)}</p>`)
    .join("");
}

function skeletonCards(count = 3, compact = false) {
  return Array.from({ length: count }, () => `
    <div class="skeleton-card ${compact ? "compact-skeleton" : ""}">
      <span></span>
      <strong></strong>
      <p></p>
    </div>
  `).join("");
}

function showInitialSkeletons() {
  if ($("daily-briefing-summary")) $("daily-briefing-summary").innerHTML = skeletonCards(1);
  ["daily-bet-list", "daily-paper-list", "daily-watch-list", "daily-avoid-list"].forEach((id) => {
    if ($(id)) $(id).innerHTML = skeletonCards(1, true);
  });
  ["performance-summary", "backtest-summary", "calibration-list", "backtest-works", "backtest-fails", "settlement-audit-list"].forEach((id) => {
    if ($(id)) $(id).innerHTML = skeletonCards(id === "performance-summary" ? 4 : 2, true);
  });
}

function syncDefaultInputs() {
  const defaults = JSON.parse(localStorage.getItem("edgeiq.onboarding") || "{}");
  if (defaults.platform && $("props-platform")) $("props-platform").value = defaults.platform;
  if (defaults.platform && $("entry-platform")) $("entry-platform").value = defaults.platform;
  if (defaults.sport && $("props-sport")) $("props-sport").value = defaults.sport;
  if (defaults.defaultWager && $("entry-wager")) $("entry-wager").value = defaults.defaultWager;
  if ((defaults.risk === "conservative" || defaults.risk === "paper_first") && $("entry-multiplier")) $("entry-multiplier").value = "2";
  if (defaults.risk === "aggressive" && $("entry-multiplier")) $("entry-multiplier").value = "5";
  if (defaults.risk === "paper_first" && $("entry-mode")) $("entry-mode").value = "paper";
}

function activateWorkspace(root, paneName, options = {}) {
  if (!root || !paneName) return;
  const tabs = [...root.querySelectorAll("[data-workspace-tab]")].filter(
    (tab) => tab.closest("[data-workspace]") === root
  );
  const panes = [...root.querySelectorAll("[data-workspace-pane]")].filter(
    (pane) => pane.closest("[data-workspace]") === root
  );
  tabs.forEach((tab) => {
    const active = tab.dataset.workspaceTab === paneName;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  panes.forEach((pane) => {
    const active = pane.dataset.workspacePane === paneName;
    pane.hidden = !active;
    if (active && pane.tagName === "DETAILS") pane.open = true;
  });
  if (root.dataset.workspace) {
    window.sessionStorage.setItem(`edgeiq.workspace.${root.dataset.workspace}`, paneName);
  }
  if (options.focus) {
    root.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  if (options.load !== false) loadWorkspacePaneData(root, paneName);
}

function loadWorkspacePaneData(root, paneName) {
  const workspaceId = root?.dataset.workspace;
  if (!workspaceId) return;
  const key = `${workspaceId}:${paneName}`;
  if (state.loadedWorkspacePanes.has(key)) return;
  const loaders = {
    "decision-desk:value": [loadSportsbookSync, loadTrendingProps],
    "decision-desk:alerts": [loadTimingAlerts, loadNotifications],
    "decision-desk:builder": [() => loadEntryProgress({ autoCheck: false, refreshProviders: false, marketDetail: false }), loadTrendingGames],
    "decision-desk:board": [() => loadProps({ cascade: false })],
    "results-workspace:performance": [loadPerformance],
    "results-workspace:model": [loadBacktest, loadAccuracyLab],
    "results-workspace:settlement": [loadSettlementAudit],
  }[key] || [];
  if (!loaders.length) return;
  state.loadedWorkspacePanes.add(key);
  Promise.allSettled(loaders.map((loader) => loader())).then((results) => {
    const failure = results.find((result) => result.status === "rejected");
    if (failure) {
      state.loadedWorkspacePanes.delete(key);
      console.warn(`${key} refresh failed`, failure.reason);
    }
  });
}

function setupWorkspaces() {
  document.querySelectorAll("[data-workspace]").forEach((root) => {
    const tabs = [...root.querySelectorAll("[data-workspace-tab]")].filter(
      (tab) => tab.closest("[data-workspace]") === root
    );
    if (!tabs.length) return;
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => activateWorkspace(root, tab.dataset.workspaceTab));
    });
    const stored = window.sessionStorage.getItem(`edgeiq.workspace.${root.dataset.workspace}`);
    const initial = tabs.some((tab) => tab.dataset.workspaceTab === stored)
      ? stored
      : tabs.find((tab) => tab.classList.contains("active"))?.dataset.workspaceTab || tabs[0].dataset.workspaceTab;
    activateWorkspace(root, initial, { load: false });
  });
}

function jumpToWorkspace(button) {
  const [workspaceId, paneName] = String(button?.dataset.workspaceJump || "").split(":");
  const root = document.querySelector(`[data-workspace="${workspaceId}"]`);
  const view = root?.closest(".view");
  if (view) setView(view.id);
  activateWorkspace(root, paneName, { focus: true });
}

function setResearchToolValue(id, value) {
  const field = $(id);
  if (!field || value === "") return;
  if (field.tagName === "SELECT") {
    const available = [...field.options].some((option) => option.value === value);
    if (!available) return;
  }
  field.value = value;
}

function runFullResearch(event) {
  event.preventDefault();
  const player = $("research-context-player").value.trim();
  const stat = $("research-context-stat").value.trim();
  const sport = $("research-context-sport").value;
  const platform = $("research-context-platform").value;
  const line = $("research-context-line").value;
  if (!player || !stat) {
    $("research-context-status").textContent = "Enter both a player and stat to run research.";
    return;
  }
  ["assist-player", "hit-player", "research-player", "shop-player", "consensus-player", "movement-player"].forEach((id) => setResearchToolValue(id, player));
  ["assist-stat", "hit-stat", "research-stat", "shop-stat", "consensus-stat", "movement-stat"].forEach((id) => setResearchToolValue(id, stat));
  ["assist-sport", "research-sport", "shop-sport", "consensus-sport"].forEach((id) => setResearchToolValue(id, sport));
  ["research-platform", "shop-platform", "consensus-platform", "movement-platform"].forEach((id) => setResearchToolValue(id, platform));
  ["assist-line", "hit-line", "research-line"].forEach((id) => setResearchToolValue(id, line));
  $("research-context-status").textContent = line
    ? "Running projection, hit-rate, and player-context analysis..."
    : "Running player context. Add a line to include projection and hit-rate analysis.";
  $("player-research-form").requestSubmit();
  if (line) {
    $("projection-assist-form").requestSubmit();
    $("hit-rate-form").requestSubmit();
  }
}

function setView(viewId) {
  if (viewId === "props") {
    viewId = "dashboard";
    const advancedSignals = document.querySelector(".dashboard-support-drawer:nth-of-type(2)");
    if (advancedSignals) advancedSignals.open = true;
  }
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.remove("active"));
  $(viewId).classList.add("active");
  document.querySelectorAll(`[data-view="${viewId}"]`).forEach((button) => button.classList.add("active"));
  const navButton = document.querySelector(`[data-view="${viewId}"]`);
  const titles = { dashboard: "Today", entries: "Entries", performance: "Results", analysis: "Research", bets: "Results · Ledger" };
  $("view-title").textContent = titles[viewId] || navButton?.textContent || viewId;
  loadViewData(viewId);
  const workspace = $(viewId).matches("[data-workspace]") ? $(viewId) : $(viewId).querySelector("[data-workspace]");
  const activeWorkspaceTab = workspace?.querySelector("[data-workspace-tab].active");
  if (workspace && activeWorkspaceTab) {
    loadWorkspacePaneData(workspace, activeWorkspaceTab.dataset.workspaceTab);
  }
}

function loadViewData(viewId) {
  if (state.loadedViews.has(viewId)) return;
  state.loadedViews.add(viewId);
  const tasks = {
    performance: [
      loadPerformance,
    ],
    bets: [loadBets, loadGradingReport, loadLossReview, loadBankrollTransactions],
    entries: [loadLossProtection, loadPending, loadPreferences, loadDnpSetting, loadPortfolioIntelligence],
    analysis: [loadDataHealth, loadNotifications, loadDeployReadiness, loadRefreshSchedule, loadAlertDeliverySettings],
  }[viewId] || [];
  if (!tasks.length) return;
  Promise.allSettled(tasks.map((task) => task())).then((results) => {
    const failure = results.find((result) => result.status === "rejected");
    if (failure) console.warn(`${viewId} view refresh failed`, failure.reason);
  });
}

function renderStats(stats) {
  const accuracy = stats.recommendation_accuracy || {};
  const paper = stats.paper || {};
  const items = [
    { label: "Record", value: stats.record, icon: "▥", tone: "neutral" },
    { label: "Win %", value: stats.wins + stats.losses ? pct((stats.wins / (stats.wins + stats.losses)) * 100) : "0.0%", icon: "◎", tone: "positive" },
    { label: "Net Profit", value: money(stats.profit), icon: "$", tone: Number(stats.profit || 0) >= 0 ? "positive" : "negative" },
    { label: "ROI", value: pct(stats.roi), icon: "↗", tone: Number(stats.roi || 0) >= 0 ? "positive" : "negative" },
    { label: "Bankroll", value: money(stats.bankroll), icon: "◈", tone: "blue" },
    { label: "Deposits", value: money(stats.bankroll_transactions?.deposits), icon: "+", tone: "positive" },
    { label: "Withdrawals", value: money(stats.bankroll_transactions?.withdrawals), icon: "-", tone: "warning" },
    { label: "Wagered", value: money(stats.wagered), icon: "◆", tone: "purple" },
    { label: "Pending Entry Exposure", value: money(stats.pending_entry_exposure), icon: "⌁", tone: "warning" },
    { label: "Paper Calibration", value: `${paper.decisions || 0} decisions`, icon: "◇", tone: "purple" },
    { label: "Current Streak", value: stats.current_streak > 0 ? `W${stats.current_streak}` : stats.current_streak < 0 ? `L${Math.abs(stats.current_streak)}` : "-", icon: "↕", tone: stats.current_streak >= 0 ? "positive" : "negative" },
    { label: "Max Drawdown", value: money(stats.max_drawdown), icon: "↓", tone: Number(stats.max_drawdown || 0) > 0 ? "negative" : "neutral" },
  ];
  $("dashboard-stats").innerHTML = items.map((item) => `
    <div class="stat-card stat-${item.tone}">
      <span class="stat-icon">${item.icon}</span>
      <div>
        <div class="stat-label">${item.label}</div>
        <div class="stat-value">${item.value}</div>
      </div>
    </div>
  `).join("");
  $("recommendation-accuracy").innerHTML = `
    <div class="recommendation-accuracy-header">
      <div>
        <h2>EdgeIQ Recommendation Accuracy</h2>
        <p>Entries placed from EdgeIQ recommendations</p>
      </div>
      <div class="grade">${pct(accuracy.accuracy || 0)}</div>
    </div>
    <div class="accuracy-grid">
      <div><strong>${accuracy.wins || 0}-${accuracy.losses || 0}</strong><span>Win/Loss</span></div>
      <div><strong>${accuracy.pending || 0}</strong><span>Pending</span></div>
      <div><strong>${accuracy.pushes || 0}</strong><span>Pushes</span></div>
      <div><strong>${accuracy.tracked || 0}</strong><span>Tracked</span></div>
      <div><strong>${pct(paper.accuracy || 0)}</strong><span>Paper Accuracy</span></div>
    </div>
  `;
}

async function loadDashboard() {
  const stats = await api("/api/dashboard");
  renderStats(stats);
}

async function loadDailyBriefing(options = {}) {
  const refresh = Boolean(options.refresh);
  $("daily-briefing-status").textContent = refresh
    ? "Rebuilding confirmed props, calibration gaps, timing, and bankroll..."
    : "Loading cached morning card...";
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const params = new URLSearchParams({ platform, sport });
  if (refresh) params.set("refresh", "true");
  if (!refresh) params.set("cached_only", "true");
  const data = await api(`/api/daily-briefing?${params.toString()}`);
  state.dailyBriefing = data;
  renderDailyBriefing(data);
  maybeAutoStartDailyScan(data);
}

async function startDailyBriefingScan() {
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const params = new URLSearchParams({ platform, sport });
  const scan = await api(`/api/daily-briefing/scan?${params.toString()}`, { method: "POST" });
  renderDailyScanStatus({ current: scan, runs: [] });
  pollDailyScanStatus(true);
}

function maybeAutoStartDailyScan(briefing) {
  const cache = briefing?.cache || {};
  const needsScan = Boolean(cache.cached_only || cache.requires_refresh || cache.stale);
  const scanKey = `${$("props-platform")?.value || "PrizePicks"}:${$("props-sport")?.value || "All Sports"}`;
  if (!needsScan || state.dailyScanAutoStartedFor === scanKey) return;
  const status = document.querySelector("[data-daily-scan-status]")?.dataset.dailyScanStatus;
  if (["scanning_props", "analyzing_games", "building_entries"].includes(status)) return;
  state.dailyScanAutoStartedFor = scanKey;
  startDailyBriefingScan().catch((error) => {
    state.dailyScanAutoStartedFor = "";
    console.warn("Daily briefing auto scan failed", error);
  });
}

async function loadDailyScanStatus() {
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const params = new URLSearchParams({ platform, sport });
  const data = await api(`/api/daily-briefing/scan-status?${params.toString()}`);
  renderDailyScanStatus(data);
  const status = data.current?.status;
  if (["scanning_props", "analyzing_games", "building_entries"].includes(status)) {
    pollDailyScanStatus();
  }
}

function pollDailyScanStatus(immediate = false) {
  if (state.dailyScanPoll) window.clearTimeout(state.dailyScanPoll);
  const tick = async () => {
    await loadDailyScanStatus();
    const status = document.querySelector("[data-daily-scan-status]")?.dataset.dailyScanStatus;
    if (["scanning_props", "analyzing_games", "building_entries"].includes(status)) {
      state.dailyScanPoll = window.setTimeout(tick, 2500);
    } else if (status === "ready") {
      await loadDailyBriefing();
    }
  };
  state.dailyScanPoll = window.setTimeout(tick, immediate ? 400 : 2500);
}

function renderDailyScanStatus(data) {
  const current = data.current || {};
  const runs = data.runs || [];
  const status = current.status || "not_run_today";
  const summary = current.summary || {};
  const steps = current.steps || [];
  $("daily-scan-status").classList.remove("muted-card");
  $("daily-scan-status").innerHTML = `
    <div class="scan-status-card" data-daily-scan-status="${escapeHtml(status)}">
      <div class="scan-status-head">
        <div>
          <span class="status-pill status-${status === "ready" ? "connected" : status === "failed" ? "error" : "degraded"}">${escapeHtml(current.status_label || friendlyStatus(status))}</span>
          <strong>${escapeHtml(current.message || "No Daily Briefing scan has run yet today.")}</strong>
        </div>
        <small>${current.updated_at ? `Updated ${formatDateTime(current.updated_at)}` : "Waiting for first scan"}</small>
      </div>
      <div class="scan-progress"><span style="width:${Math.max(0, Math.min(100, Number(current.progress || 0)))}%"></span></div>
      <div class="scan-step-row">
        ${steps.map((step) => `<span class="scan-step scan-step-${escapeHtml(step.state || "pending")}">${escapeHtml(step.label)}</span>`).join("")}
      </div>
      <div class="scan-summary-row">
        <span>${Number(summary.analyzed_props || 0).toLocaleString()} props</span>
        <span>${Number(summary.games || 0).toLocaleString()} games</span>
        <span>${Number(summary.bet_cards || 0).toLocaleString()} bet cards</span>
        <span>${Number(summary.paper_cards || 0).toLocaleString()} paper cards</span>
      </div>
      ${runs.length ? `
        <details class="scan-run-log">
          <summary>Recent Scan Log</summary>
          <div>
            ${runs.slice(0, 5).map((run) => `
              <div class="scan-run-row">
                <span>${escapeHtml(run.status_label || friendlyStatus(run.status))}</span>
                <strong>${escapeHtml(run.summary?.headline || run.message || "Daily Briefing scan")}</strong>
                <small>${formatDateTime(run.completed_at || run.updated_at || run.started_at)}</small>
              </div>
            `).join("")}
          </div>
        </details>
      ` : ""}
    </div>
  `;
}

function friendlyModeLabel(mode) {
  const labels = {
    lockdown: "Protect",
    watch: "Protect",
    normal: "Ready",
    attack: "Ready",
    selective: "Selective",
  };
  return labels[String(mode || "").toLowerCase()] || "Ready";
}

function commandCenterSummary(data, protection) {
  if (protection?.active) {
    return "EdgeIQ is protecting your bankroll today. Paid entries stay paused unless a card clears recovery rules.";
  }
  const paid = (data.sections?.bet || []).length;
  if (paid) return `EdgeIQ found ${paid} paid card${paid === 1 ? "" : "s"} worth reviewing, with paper and watch ideas kept separate.`;
  if ((data.sections?.watch || []).length) return "No paid card cleared yet. The board has watch candidates that need one more confirmation.";
  return "No forced bets today. EdgeIQ will keep the board useful with games, paper calibration, and avoid signals.";
}

function renderNextActionCard(label, detail, view, targetId) {
  return `
    <button class="next-action-card" type="button" data-next-action-view="${escapeHtml(view)}" data-next-action-target="${escapeHtml(targetId || "")}">
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(detail)}</span>
    </button>
  `;
}

function renderRecoveryProgress(protection) {
  const metrics = protection?.metrics || {};
  const trackedClv = Number(metrics.tracked_clv_legs || 0);
  const clvStep = trackedClv
    ? { label: "CLV Improving", value: Math.max(0, Math.min(100, 50 + Number(metrics.average_clv || 0) * 20)), detail: `${Number(metrics.average_clv || 0).toFixed(2)} avg · ${trackedClv} verified` }
    : { label: "CLV Building", value: 8, detail: `${Number(metrics.quarantined_clv_legs || 0)} legacy legs excluded` };
  const steps = [
    { label: "Final Stats Verified", value: Math.min(100, Number(metrics.verified_legs || 0) * 12), detail: `${Number(metrics.verified_legs || 0)} verified` },
    clvStep,
    { label: "Monthly ROI", value: Math.max(0, Math.min(100, 50 + Number(metrics.roi || 0) * 2)), detail: pct(metrics.roi || 0) },
  ];
  return `
    <div class="recovery-progress ${protection?.active ? "recovery-active" : "recovery-clear"}">
      <div class="suggestion-top">
        <div>
          <span class="pill">${protection?.active ? "Bankroll protection" : "Model ready"}</span>
          <strong>${escapeHtml(protection?.label || "Paid Entries Enabled")}</strong>
        </div>
        <span class="subtle">${Number(protection?.score || 100).toFixed(0)}/100</span>
      </div>
      <div class="recovery-step-grid">
        ${steps.map((step) => `
          <div class="recovery-step">
            <div><strong>${escapeHtml(step.label)}</strong><span>${escapeHtml(step.detail)}</span></div>
            <div class="progress-track"><span style="width:${Math.max(8, step.value)}%"></span></div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderDailyBriefing(data) {
  const cacheLabel = data.cache?.stale
    ? `expired cache ${formatDateTime(data.cache.created_at)} · refresh recommended`
    : data.cache?.hit
      ? `cached ${formatDateTime(data.cache.created_at)}`
      : "fresh scan";
  $("daily-briefing-status").textContent = `${data.headline} · ${data.sport} · ${cacheLabel}`;
  const health = data.summary?.model_health || {};
  const slate = data.summary?.slate || [];
  const riskOrder = { conservative: 0, balanced: 1, aggressive: 2 };
  const opportunities = [...(data.top_opportunities || [])].sort((a, b) =>
    (riskOrder[a.risk_profile?.key] ?? 2) - (riskOrder[b.risk_profile?.key] ?? 2)
    || Number(b.score || 0) - Number(a.score || 0));
  const suggestedEntries = data.suggested_entries || [];
  const gamesToday = data.games_today || [];
  const providerBadges = data.provider_badges || [];
  const protection = data.loss_protection || {};
  const ev = Number(data.summary?.expected_value || 0);
  const mode = protection.active ? protection.mode || "watch" : (data.sections?.bet || []).length ? "attack" : "selective";
  const betCount = (data.sections?.bet || []).length;
  const watchCount = (data.sections?.watch || []).length;
  const paperCount = (data.sections?.paper || []).length;
  const avoidCount = (data.sections?.avoid || []).length;
  if ($("daily-greeting")) $("daily-greeting").textContent = data.user?.greeting || "Good Morning Joshua.";
  $("daily-briefing-summary").classList.remove("muted-card");
  $("daily-briefing-summary").innerHTML = `
    <div class="command-welcome">
      <div>
        <p class="eyebrow">Today Command Center</p>
        <h2>Today's Decision Plan</h2>
        <p>${escapeHtml(commandCenterSummary(data, protection))}</p>
      </div>
      <div class="command-mode ${protection.active ? "mode-protect" : "mode-ready"}">
        <span>${escapeHtml(friendlyModeLabel(mode))}</span>
        <strong>${protection.active ? Number(protection.score || 0).toFixed(0) : Number(health.trust_score || 0).toFixed(0)}/100</strong>
      </div>
    </div>
    <div class="command-next-grid">
      ${renderNextActionCard("Review Today's Best Card", betCount ? `${betCount} paid candidate${betCount === 1 ? "" : "s"} cleared` : "No paid card cleared. That can be the right call.", "dashboard", "daily-bet-list")}
      ${renderNextActionCard("Recheck Final Stats", "Clear unknowns before trusting calibration.", "performance", "entry-history-list")}
      ${renderNextActionCard("Create Paper Calibration", `${paperCount} paper idea${paperCount === 1 ? "" : "s"} available`, "dashboard", "daily-paper-list")}
      ${renderNextActionCard("View Loss Review", "See what EdgeIQ will avoid next.", "performance", "loss-review-list")}
    </div>
    ${renderRecoveryProgress(protection)}
    <div class="briefing-terminal">
      <div class="briefing-terminal-main">
        <div class="briefing-terminal-kicker">AI analyzed</div>
        <div class="briefing-terminal-number">${Number(data.summary?.analyzed_props || 0).toLocaleString()}</div>
        <div class="briefing-terminal-label">player props</div>
        <p>${escapeHtml(data.headline)}</p>
      </div>
      <div class="briefing-terminal-side">
        <span class="health-orb">${Math.round(health.trust_score || 0)}</span>
        <small>${escapeHtml(health.status || "Model")}</small>
      </div>
    </div>
    <div class="provider-badge-row">
      ${providerBadges.map((badge) => `
        <span class="provider-badge provider-${escapeHtml(badge.status || "available")}">
          <strong>${escapeHtml(badge.name)}</strong>
          <small>${escapeHtml(badge.role)} · ${escapeHtml(badge.freshness)}</small>
        </span>
      `).join("")}
    </div>
    ${protection.active ? `
      <div class="loss-protection-banner">
        <div>
          <strong>${escapeHtml(protection.label || "Loss Protection Active")}</strong>
          <span>${escapeHtml((protection.reasons || [])[0] || "Paid entries are paused until recovery rules clear.")}</span>
        </div>
        <span>${escapeHtml(protection.mode || "watch")} · ${Number(protection.score || 0).toFixed(0)}/100</span>
      </div>
    ` : ""}
    <div class="briefing-market-grid">
      <div class="briefing-market-section">
        <div class="briefing-section-title">Today's Slate</div>
        <div class="slate-ticker">
          ${slate.length ? slate.slice(0, 4).map((row) => `
            <div class="slate-tile">
              <strong>${Number(row.games || 0).toLocaleString()}</strong>
              <span>${escapeHtml(row.sport || "Sport")} Games</span>
              <small>${Number(row.props || 0).toLocaleString()} props</small>
            </div>
          `).join("") : `
            <div class="slate-tile">
              <strong>${Number(data.summary?.confirmed_props || 0).toLocaleString()}</strong>
              <span>Confirmed Props</span>
              <small>${Number(data.summary?.excluded_props || 0).toLocaleString()} filtered</small>
            </div>
          `}
        </div>
      </div>
      <div class="briefing-market-section">
        <div class="briefing-section-title">Risk Level</div>
        <div class="risk-ev-grid">
          <div>
            <strong>${escapeHtml(data.summary?.risk_level || "No Card")}</strong>
            <span>Risk Level</span>
          </div>
          <div>
            <strong>${ev > 0 ? "+" : ""}${pct(ev)}</strong>
            <span>Expected Value</span>
          </div>
        </div>
        <div class="briefing-section-title compact-title">Suggested Entries</div>
        <div class="suggested-entry-row">
          ${suggestedEntries.map((entry) => `
            <button class="secondary suggested-entry-button" data-ai-prompt="${escapeHtml(entry.prompt)}">${escapeHtml(entry.label)}</button>
          `).join("")}
        </div>
      </div>
    </div>
    <section id="opportunity-board" class="opportunity-board" aria-labelledby="opportunity-board-title">
      <div class="opportunity-board-header">
        <div>
          <p class="eyebrow">Single Recommendation Source</p>
          <h3 id="opportunity-board-title">Opportunity Board</h3>
          <p>Conservative emphasizes verified evidence, Balanced accepts measured uncertainty, and Aggressive is best treated as paper-first.</p>
        </div>
        <div class="button-row compact-button-row">
          <span class="status-pill status-connected">${opportunities.length} ranked</span>
          <button id="send-selected-opportunities" class="secondary" type="button" disabled>Send selected (0)</button>
        </div>
      </div>
      <div class="opportunity-list opportunity-board-list">
        ${opportunities.slice(0, 5).map((prop, index) => {
          const receipt = prop.decision_receipt || {};
          const movement = receipt.movement || {};
          const exposure = receipt.portfolio_exposure || {};
          const marketProbability = receipt.market_probability;
          const previousProfile = index ? opportunities[index - 1]?.risk_profile?.key : "";
          const currentProfile = prop.risk_profile?.key || "aggressive";
          const expired = prop.recommendation_freshness?.status === "expired";
          const actionable = prop.actionable ?? Boolean(
            prop.market_supported !== false
            && Number(prop.trust?.score || 0) >= 50
            && Number(prop.confidence || 0) >= 52
          );
          const profileHeader = currentProfile !== previousProfile ? `
            <div class="opportunity-risk-header risk-${escapeHtml(currentProfile)}">
              <strong>${escapeHtml(prop.risk_profile?.label || "Aggressive")}</strong>
              <span>${escapeHtml(prop.risk_profile?.description || "Higher uncertainty. Prefer paper tracking.")}</span>
            </div>` : "";
          return `
          ${profileHeader}
          <div class="opportunity-row ${expired ? "opportunity-expired" : ""}">
            <label aria-label="Select ${escapeHtml(prop.player || `opportunity ${index + 1}`)}">
              <input class="opportunity-select" type="checkbox" data-select-opportunity="${index}" ${expired || !actionable ? "disabled" : ""} />
            </label>
            <span class="stars">${escapeHtml(prop.stars || "★★★☆☆")}</span>
            <strong>
              <span class="risk-profile-label risk-${escapeHtml(prop.risk_profile?.key || "aggressive")}">${escapeHtml(prop.risk_profile?.label || "Aggressive")}</span>
              ${escapeHtml(prop.player)} ${escapeHtml(prop.direction || "Over")} ${escapeHtml(prop.line ?? "")} ${escapeHtml(prop.stat || "")}
              <small>
                ${escapeHtml(prop.platform || data.platform || "Provider")} · ${escapeHtml(prop.sport || data.sport || "All Sports")}
                ${prop.adjusted_line ? ` · ${prop.is_discounted_line ? "Discounted line" : (String(prop.line_offer_type || "").toLowerCase() === "demon" ? "Demon · Over only" : "Adjusted payout")}` : " · Standard line"}
              </small>
            </strong>
            <div class="opportunity-proof">
              <span>Model ${Number(receipt.probability || prop.confidence || 0).toFixed(0)}%</span>
              <span>${marketProbability == null ? "Market unavailable" : `Market ${Number(marketProbability).toFixed(0)}% · ${Number(receipt.market_book_count || 0)} book${Number(receipt.market_book_count || 0) === 1 ? "" : "s"}`}</span>
              <span>Move ${Number(movement.change || 0) > 0 ? "+" : ""}${Number(movement.change || 0).toFixed(1)}</span>
              <span>${escapeHtml(exposure.label || "No pending exposure")}</span>
              <span class="${expired || !actionable ? "danger-text" : ""}">${expired ? "Expired · refresh required" : !actionable ? "Research only · cannot add" : "Fresh recommendation"}</span>
            </div>
            <div class="opportunity-actions">
              <button class="icon-text-button secondary" type="button" data-inspect-opportunity="${index}">Proof</button>
            </div>
          </div>
        `;
        }).join("") || `<div class="suggestion compact-suggestion">No props cleared the current recommendation and data-quality filters.</div>`}
      </div>
    </section>
    <div class="briefing-metric-row">
      <span>Bankroll ${money(data.summary?.bankroll)}</span>
      <span>Month ${money(data.summary?.monthly_profit)} · ${pct(data.summary?.monthly_roi)}</span>
      <span>${betCount} paid · ${watchCount} watch · ${avoidCount} no-bet</span>
      <span>${Number(data.summary?.confirmed_props || 0).toLocaleString()} confirmed</span>
      <span>${Number(data.summary?.excluded_props || 0).toLocaleString()} filtered</span>
    </div>
    <div class="games-today-panel">
      <div class="briefing-section-title">Games Today</div>
      <div class="games-today-list">
        ${gamesToday.map((game, index) => renderDailyGame(game, index)).join("") || `<div class="suggestion compact-suggestion">No game-level slate is available for this filter yet.</div>`}
      </div>
    </div>
  `;
  renderBriefingSection("daily-bet-list", data.sections?.bet || [], data.empty_states?.bet || "No real-money slip cleared this filter yet.");
  renderBriefingSection("daily-paper-list", data.sections?.paper || [], data.empty_states?.paper || "No paper calibration card is needed right now.");
  renderBriefingSection("daily-watch-list", data.sections?.watch || [], data.empty_states?.watch || "No watchlist alerts right now.");
  renderBriefingSection("daily-avoid-list", data.sections?.avoid || [], data.empty_states?.avoid || "No avoid flags on the visible board.");
  bindDailyBriefingActions();
  bindDailyBriefingSummaryActions();
  bindBriefingTabs();
}

function renderDailyGame(game, index) {
  const best = game.best_prop || {};
  const matchup = game.matchup_label || game.game || "Matchup TBD";
  const generatorAvailable = Boolean(game.generated_entry?.available && (game.generated_entry?.props || []).length >= 2);
  return `
    <details class="daily-game-card">
      <summary>
        <div>
          <span class="pill">${escapeHtml(game.sport || "Game")}</span>
          <strong>${escapeHtml(matchup)}</strong>
          <small>${Number(game.prop_count || 0)} props · AI ${Number(game.ai_score || 0).toFixed(0)} · ${pct(game.probability || 0)}</small>
        </div>
        <button class="secondary" type="button" data-generate-game-entry="${index}" ${generatorAvailable ? "" : "disabled"}>${escapeHtml(game.generated_entry?.label || "Generate Entry")}</button>
      </summary>
      <div class="daily-game-grid">
        ${renderGameMetric("Projected Winner", game.projected_winner)}
        ${renderGameMetric("Team Pace", game.team_pace)}
        ${renderGameMetric("Injuries", game.injuries)}
        ${renderGameMetric("Best Prop", propLabel(game.best_prop))}
        ${renderGameMetric("Best Value Prop", propLabel(game.best_value_prop))}
        ${renderGameMetric("Highest Confidence", propLabel(game.highest_confidence))}
        ${renderGameMetric("Fade Candidate", propLabel(game.fade_candidate))}
        ${renderGameMetric(game.vegas_line_source ? `Vegas Line · ${game.sportsbook_count || 0} books` : "Vegas Line", game.vegas_line)}
        ${renderGameMetric("AI Score", Number(game.ai_score || 0).toFixed(1))}
        ${renderGameMetric("Probability", pct(game.probability || 0))}
        ${renderGameMetric("Line Movement", game.line_movement)}
        ${renderGameMetric("Public Betting", game.public_betting)}
        ${renderGameMetric("Weather", game.weather)}
      </div>
      ${best.player ? `<p class="subtle">Best visible angle: ${escapeHtml(propLabel(best))}</p>` : ""}
    </details>
  `;
}

function renderGameMetric(label, value) {
  return `
    <div class="game-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value || "Unavailable")}</strong>
    </div>
  `;
}

function propLabel(prop) {
  if (!prop || !prop.player) return "Unavailable";
  return `${prop.player} ${prop.direction || "Over"} ${prop.line ?? ""} ${prop.stat || ""}`.trim();
}

function renderBriefingSection(elementId, cards, emptyMessage) {
  $(elementId).innerHTML = cards.map((card, index) => {
    const props = card.props || [];
    const stake = card.stake || {};
    const trust = card.trust || {};
    const timing = card.timing || {};
    const isHero = elementId === "daily-bet-list";
    return `
      <div class="briefing-card ${isHero ? "daily-best-card" : ""} ${card.grade ? gradeClass(card.grade) : ""}" data-briefing-card="${elementId}:${index}">
        <div class="suggestion-top">
          <span class="pill">${escapeHtml(isHero ? "Daily Best Card" : card.title || "Card")}</span>
          <strong>${escapeHtml(card.grade || card.type || "")}${card.score ? ` · ${Number(card.score || 0).toFixed(1)}` : ""}</strong>
        </div>
        <div class="recommendation-meta-row">
          ${trust.label ? `<span class="model-trust-badge">Model Trust ${Number(trust.score || 0).toFixed(0)} · ${escapeHtml(trust.label)}</span>` : ""}
          ${dataStrengthBadges(props)}
        </div>
        <h3>${escapeHtml(friendlyCardAction(card))}</h3>
        <p>${escapeHtml(card.reason || card.summary || "")}</p>
        ${releaseStatusBlock(card.release_status)}
        ${props.length ? `
          <div class="command-leg-list">
            ${props.slice(0, 4).map((prop) => `<span>${shortPropPickText(prop)} <b>${escapeHtml(prop.line ?? "")}</b></span>`).join("")}
          </div>
        ` : ""}
        ${confidenceMoveNotes(props)}
        <div class="briefing-card-meta">
          ${trust.label ? `<span>Trust ${Number(trust.score || 0).toFixed(0)} · ${escapeHtml(trust.label)}</span>` : ""}
          ${timing.label ? `<span>${escapeHtml(timing.label)}</span>` : ""}
          ${stake.unit_label ? `<span>${money(stake.amount || 0)}</span>` : ""}
          ${card.explanation?.freshness ? `<span>${escapeHtml(card.explanation.freshness.label)}</span>` : ""}
        </div>
        ${card.warnings && card.warnings.length ? `<p class="warning">${card.warnings.map(escapeHtml).join(" · ")}</p>` : ""}
        <div class="button-row">
          <button class="secondary" data-daily-action="${elementId}:${index}">${escapeHtml(card.button_label || "Review")}</button>
          ${card.explanation ? `<button class="secondary" data-daily-explain="${elementId}:${index}">Why?</button>` : ""}
          ${props.length ? `<button class="secondary" data-daily-compare="${elementId}:${index}">Compare Apps</button>` : ""}
        </div>
      </div>
    `;
  }).join("") || friendlyEmptyState(elementId, emptyMessage);
}

function friendlyCardAction(card) {
  const text = String(card.action || card.summary || "Review");
  if (/pass/i.test(text)) return text.replace(/pass/ig, "No Bet");
  if (/avoid/i.test(text)) return text.replace(/avoid/ig, "No Bet");
  return text;
}

function friendlyEmptyState(elementId, emptyMessage) {
  const map = {
    "daily-bet-list": {
      title: "No paid card cleared",
      body: "That is a good outcome when the board is weak. EdgeIQ will protect bankroll and keep useful watch/paper ideas separate.",
    },
    "daily-paper-list": {
      title: "No paper calibration needed",
      body: "When a weak sport, stat, or confidence segment appears, EdgeIQ will create paper-only reps here.",
    },
    "daily-watch-list": {
      title: "No watch items right now",
      body: "Line movement, injury, and timing checks are quiet for this filter.",
    },
    "daily-avoid-list": {
      title: "No no-bet flags visible",
      body: "If a prop fails validation or calibration, EdgeIQ will explain the no-bet here.",
    },
  };
  const item = map[elementId] || { title: "Nothing to show yet", body: emptyMessage };
  return `
    <div class="empty-state-card">
      <strong>${escapeHtml(item.title)}</strong>
      <p>${escapeHtml(item.body || emptyMessage)}</p>
    </div>
  `;
}

function dailyCardFromKey(key) {
  const [elementId, indexText] = String(key || "").split(":");
  const sectionMap = {
    "daily-bet-list": "bet",
    "daily-paper-list": "paper",
    "daily-watch-list": "watch",
    "daily-avoid-list": "avoid",
  };
  const section = sectionMap[elementId];
  if (!section || !state.dailyBriefing) return null;
  return (state.dailyBriefing.sections?.[section] || [])[Number(indexText)];
}

function bindDailyBriefingActions() {
  document.querySelectorAll("[data-daily-action]").forEach((button) => {
    button.addEventListener("click", () => handleDailyBriefingAction(dailyCardFromKey(button.dataset.dailyAction)));
  });
  document.querySelectorAll("[data-daily-explain]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = dailyCardFromKey(button.dataset.dailyExplain);
      if (card?.explanation) openExplanationDrawer(card.explanation);
    });
  });
  document.querySelectorAll("[data-daily-compare]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = dailyCardFromKey(button.dataset.dailyCompare);
      if (!card) return;
      handleDailyBriefingAction(card);
      $("entry-status").textContent = "Loaded card for app comparison. Analyze first, then use the handoff panel to compare apps.";
    });
  });
}

function bindDailyBriefingSummaryActions() {
  state.opportunitySelections.clear();
  const selectionButton = $("send-selected-opportunities");
  const updateOpportunitySelection = () => {
    if (!selectionButton) return;
    selectionButton.disabled = state.opportunitySelections.size === 0;
    selectionButton.textContent = `Send selected (${state.opportunitySelections.size})`;
  };
  document.querySelectorAll("[data-select-opportunity]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const index = Number(checkbox.dataset.selectOpportunity);
      const opportunity = state.dailyBriefing?.top_opportunities?.[index];
      if (!opportunity) return;
      const selectedPlatforms = [...state.opportunitySelections].map(
        (selectedIndex) => state.dailyBriefing?.top_opportunities?.[selectedIndex]?.platform
      ).filter(Boolean);
      if (checkbox.checked && selectedPlatforms.length && !selectedPlatforms.includes(opportunity.platform)) {
        checkbox.checked = false;
        $("daily-briefing-status").textContent = "A single entry must use one app. Send the current selection, then build a separate card for the other app.";
        return;
      }
      if (checkbox.checked) state.opportunitySelections.add(index);
      else state.opportunitySelections.delete(index);
      updateOpportunitySelection();
    });
  });
  selectionButton?.addEventListener("click", () => {
    const selected = [...state.opportunitySelections]
      .sort((left, right) => left - right)
      .map((index) => state.dailyBriefing?.top_opportunities?.[index])
      .filter(Boolean);
    if (!selected.length) return;
    renderEntryPropsFromAnalyzed(selected.map(entryPropFromFeed));
    if ($("entry-platform") && selected[0]?.platform) $("entry-platform").value = selected[0].platform;
    state.recommendationOrigin = true;
    setView("entries");
    $("entry-status").textContent = `${selected.length} selected ${selected.length === 1 ? "prop" : "props"} loaded as one entry. Review the legs, then analyze.`;
  });
  document.querySelectorAll("[data-next-action-view]").forEach((button) => {
    button.addEventListener("click", () => {
      setView(button.dataset.nextActionView || "dashboard");
      const target = $(button.dataset.nextActionTarget || "");
      if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
  document.querySelectorAll("[data-inspect-opportunity]").forEach((button) => {
    button.addEventListener("click", () => {
      const opportunity = state.dailyBriefing?.top_opportunities?.[Number(button.dataset.inspectOpportunity)];
      if (opportunity) openExplanationDrawer(opportunityExplanation(opportunity));
    });
  });
  document.querySelectorAll(".suggested-entry-button[data-ai-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      $("ai-parlay-input").value = button.dataset.aiPrompt;
      askAiParlay();
    });
  });
  document.querySelectorAll("[data-generate-game-entry]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      const game = state.dailyBriefing?.games_today?.[Number(button.dataset.generateGameEntry)];
      const props = game?.generated_entry?.props || [];
      if (!props.length) return;
      renderEntryPropsFromAnalyzed(props);
      state.recommendationOrigin = true;
      setView("entries");
      $("entry-status").textContent = `Generated entry from ${game.matchup_label || game.game}. Analyze before placing.`;
    });
  });
}

function opportunityExplanation(opportunity) {
  const receipt = opportunity.decision_receipt || {};
  const movement = receipt.movement || {};
  const exposure = receipt.portfolio_exposure || {};
  const market = receipt.market_consensus || {};
  const marketAvailable = receipt.market_probability != null;
  const dfsOfferSummary = (market.dfs_offers || []).map((offer) => {
    const selection = String(opportunity.direction || "Over").toLowerCase() === "under"
      ? offer.under
      : offer.over;
    const multiplier = selection?.multiplier;
    return `${offer.platform || offer.bookmaker}${multiplier == null ? "" : ` x${Number(multiplier).toFixed(2)}`}`;
  }).join(" · ");
  return {
    title: `${opportunity.player} · ${opportunity.stat}`,
    grade: receipt.status || "Research",
    summary: `${opportunity.direction || "Over"} ${opportunity.line} on ${opportunity.platform}. Inspect the evidence before adding it to a paid card.`,
    score: opportunity.score || 0,
    average_confidence: receipt.probability || opportunity.confidence || 0,
    average_edge: receipt.edge || opportunity.edge || 0,
    source_count: (opportunity.data_strength || []).length,
    trust: opportunity.trust || { score: 0, label: "Not scored" },
    why: `${receipt.probability_source || "EdgeIQ model"} estimates this leg at ${Number(receipt.probability || 0).toFixed(1)}%.`,
    evidence: [
      `Projection ${receipt.projection ?? "unavailable"} versus line ${opportunity.line}.`,
      marketAvailable
        ? `Multi-book no-vig probability ${Number(receipt.market_probability).toFixed(1)}% from ${Number(receipt.market_book_count || 0)} exact-line sportsbook${Number(receipt.market_book_count || 0) === 1 ? "" : "s"}; model-market edge ${Number(receipt.model_market_edge || 0) >= 0 ? "+" : ""}${Number(receipt.model_market_edge || 0).toFixed(1)} pts.`
        : receipt.market_probability_note || "Exact-line sportsbook consensus is unavailable.",
      `Line movement ${Number(movement.change || 0) > 0 ? "+" : ""}${Number(movement.change || 0).toFixed(1)} across ${Number(movement.snapshots || 0)} stored snapshots.`,
      receipt.freshness?.label || "Refresh before paid use.",
      exposure.label || "No matching pending exposure.",
      `Current matching real-money exposure ${money(exposure.real_money_exposure || 0)}.`,
      market.dfs_offers?.length
        ? `Live DFS evidence: ${dfsOfferSummary}. Multipliers are selection-level and indicative.`
        : receipt.provider_payout_note || "No live DFS payout evidence matched this exact line.",
    ],
    freshness: receipt.freshness,
    breakers: [
      ...(!marketAvailable ? [receipt.market_probability_note || "Market-derived probability is unavailable."] : []),
      ...(marketAvailable && Number(receipt.market_book_count || 0) < 2
        ? ["Only one paired sportsbook supports this exact line; market confirmation is too thin for app-generated paid use."]
        : []),
      ...(market.stale ? ["The market snapshot is stale; refresh it before paid use."] : []),
      receipt.provider_payout_note || "Confirm the complete card payout in the provider app.",
      ...(receipt.invalidation_rules || []),
    ],
    no_bet_rule: "A ranked prop is research, not a cleared paid card. Paid use requires a complete entry with positive provider-specific EV.",
    legs: [{
      player: opportunity.player,
      platform: opportunity.platform,
      sport: opportunity.sport,
      pick: `${opportunity.direction || "Over"} ${opportunity.stat} ${opportunity.line}`,
      projection: opportunity.projection,
      confidence: opportunity.confidence,
      edge: opportunity.edge,
    }],
    warnings: exposure.same_market_entries
      ? ["A matching market is already pending. EdgeIQ will block duplicate paid exposure."]
      : [],
  };
}

function focusOpportunityBoard() {
  setView("dashboard");
  requestAnimationFrame(() => {
    const target = $("opportunity-board") || $("daily-briefing-summary");
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

function bindBriefingTabs() {
  document.querySelectorAll("[data-briefing-tab]").forEach((button) => {
    button.onclick = () => {
      const target = button.dataset.briefingTab;
      document.querySelectorAll("[data-briefing-tab]").forEach((tab) => tab.classList.toggle("active", tab === button));
      document.querySelectorAll("[data-briefing-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.briefingPanel === target));
    };
  });
}

function handleDailyBriefingAction(card) {
  if (!card) return;
  state.recommendationSnapshotId = card.recommendation_snapshot_id || state.dailyBriefing?.recommendation_snapshot_id || "";
  if (card.suggestion?.entry?.props?.length) {
    renderEntryPropsFromAnalyzed(card.suggestion.entry.props);
    state.recommendationOrigin = true;
    if ($("entry-mode")) $("entry-mode").value = card.entry_mode === "paper" || card.type === "paper" ? "paper" : "real";
    setView("entries");
    $("entry-status").textContent = card.type === "paper"
      ? "Loaded paper calibration slip. Analyze, then save as paper."
      : "Loaded Today's Card slip. Analyze/place when ready.";
    return;
  }
  if ((card.props || []).length) {
    renderEntryPropsFromAnalyzed(card.props);
    state.recommendationOrigin = true;
    if ($("entry-mode")) $("entry-mode").value = card.type === "paper" ? "paper" : "real";
    setView("entries");
    $("entry-status").textContent = card.type === "paper"
      ? "Loaded paper calibration prop. Add another prop before saving as paper."
      : "Loaded Today's Card prop. Add another prop before analyzing.";
    return;
  }
  if (card.type === "paper_status") {
    setView("performance");
    return;
  }
  setView("dashboard");
}

async function loadCommandCenter() {
  $("command-center-status").textContent = "Scanning props, slips, calibration, and bankroll...";
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const data = await api(`/api/dashboard/command-center?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}`);
  state.commandCards = data.cards || [];
  renderCommandCenter(data);
  renderModelHealth(data.model_health);
}

function renderCommandCenter(data) {
  const readyCount = (data.cards || []).filter((card) => card.release_status?.ok).length;
  $("command-center-status").textContent = `${readyCount} release-ready · ${data.cards.length} reviewed · ${data.sport}`;
  $("command-center-list").innerHTML = data.cards.map((card, index) => `
    <div class="command-card ${gradeClass(card.grade)}">
      <div class="suggestion-top">
        <span class="pill">${card.title}</span>
        <strong>${card.grade} · ${card.score}</strong>
      </div>
      <div class="recommendation-meta-row">
        <span class="model-trust-badge">Model Trust ${Number(card.trust?.score || 0).toFixed(0)} · ${escapeHtml(card.trust?.label || "No Data")}</span>
        ${dataStrengthBadges(card.props || [])}
      </div>
      <h3>${card.action}</h3>
      <p>${card.summary}</p>
      <div class="timing-metrics">
        <span>Trust ${Number(card.trust?.score || 0).toFixed(0)} · ${card.trust?.label || "No Data"}</span>
        <span>${card.timing?.label || "Monitor"} ${Number(card.timing?.score || 0).toFixed(0)}</span>
        <span>Stake ${money(card.stake?.amount || 0)}</span>
      </div>
      <div class="command-leg-list">
        ${card.props.slice(0, 5).map((prop) => `<span>${shortPropPickText(prop)} <b>${prop.line}</b></span>`).join("")}
      </div>
      ${confidenceMoveNotes(card.props || [])}
      ${releaseStatusBlock(card.release_status)}
      ${card.warnings && card.warnings.length ? `<p class="warning">${card.warnings.join(" · ")}</p>` : ""}
      <div class="button-row">
        ${card.suggestion ? `<button class="secondary" data-load-command="${index}">Load Slip</button>` : `<button class="secondary" data-load-command-single="${index}">Load Single</button>`}
        <button class="secondary" data-explain-command="${index}">Why?</button>
      </div>
    </div>
  `).join("") || `<div class="suggestion">No command-center recommendations are available for this filter.</div>`;
  $("command-center-avoid").innerHTML = data.avoid && data.avoid.length
    ? `<strong>Watchlist:</strong> ${data.avoid.map(propPickText).join(" · ")}`
    : `<strong>Watchlist:</strong> No obvious avoid flags on the visible board.`;
  document.querySelectorAll("[data-load-command]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = state.commandCards[Number(button.dataset.loadCommand)];
      renderEntryPropsFromAnalyzed(card.suggestion.entry.props);
      state.recommendationOrigin = true;
      setView("entries");
      $("entry-status").textContent = `Loaded ${card.title}. Analyze/place when ready.`;
    });
  });
  document.querySelectorAll("[data-load-command-single]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = state.commandCards[Number(button.dataset.loadCommandSingle)];
      renderEntryPropsFromAnalyzed(card.props);
      state.recommendationOrigin = true;
      setView("entries");
      $("entry-status").textContent = `Loaded ${card.title}. Add another prop to place an entry.`;
    });
  });
  document.querySelectorAll("[data-explain-command]").forEach((button) => {
    button.addEventListener("click", () => openExplanationDrawer(state.commandCards[Number(button.dataset.explainCommand)].explanation));
  });
}

function renderModelHealth(health) {
  if (!health) return;
  $("model-health-score").textContent = Math.round(health.trust_score || 0);
  $("model-health-detail").classList.remove("muted-card");
  $("model-health-detail").innerHTML = `
    <div class="suggestion-top">
      <strong>${health.status}</strong>
      <span class="subtle">${health.settled_entries} settled entries · ${health.calibrated_picks} calibrated picks · ${health.paid_entry_mode === "enabled" ? "Paid enabled" : "Paper first"}</span>
    </div>
    <div class="health-bars">
      ${Object.entries(health.components || {}).map(([name, value]) => `
        <div>
          <span>${name.replaceAll("_", " ")}</span>
          <div class="health-bar"><i style="width:${Math.max(0, Math.min(100, Number(value || 0)))}%"></i></div>
        </div>
      `).join("")}
    </div>
    <p>${health.next_steps && health.next_steps.length ? health.next_steps[0] : "Model inputs look healthy."}</p>
  `;
}

async function loadModelHealth() {
  const data = await api("/api/analytics/model-health");
  renderModelHealth(data);
}

async function loadRuntimeStatus() {
  if (!$("runtime-status-list")) return;
  const data = await api("/api/runtime/status");
  $("runtime-status-list").innerHTML = (data.items || []).map((item) => `
    <div class="runtime-status-item runtime-${escapeHtml(item.status || "attention")}" title="${escapeHtml(humanizeCopilotText(item.detail || ""))}">
      <span class="runtime-status-dot" aria-hidden="true"></span>
      <div><strong>${escapeHtml(item.label || "System")}</strong><small>${escapeHtml(humanizeCopilotText(item.value || "Unknown"))}</small></div>
    </div>
  `).join("") || `<div class="runtime-status-loading">Runtime status is not available yet.</div>`;
}

async function loadDataHealth() {
  const data = await api("/api/data-health");
  const providers = sortProviderHealth(data.providers);
  const usage = data.api_usage || {};
  const totals = usage.totals || {};
  const endpointPerformance = data.endpoint_performance || {};
  const endpointRoutes = endpointPerformance.routes || [];
  const operations = data.operations || {};
  const scheduler = operations.scheduler || {};
  const shadow = operations.shadow_evaluation || {};
  const shadowSettlement = operations.shadow_settlement || {};
  const researchMemory = operations.research_memory || {};
  $("data-health-list").innerHTML = `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${data.summary.connected}/${data.summary.total} sources available</strong>
        <span class="status-pill ${data.summary.warnings ? "status-warning" : "status-connected"}">${data.summary.warnings} warnings</span>
      </div>
      <p>${data.summary.last_daily_refresh ? `Last scheduled provider refresh ${formatDateTime(data.summary.last_daily_refresh)}` : "No scheduled provider refresh recorded yet."}</p>
      <p>${Number(usage.requests_avoided || 0)} provider calls avoided · ${Number(totals.network_requests || 0)} network requests · ${Number(usage.avoidance_pct || 0).toFixed(1)}% cache efficiency · ${Number(totals.stale_fallbacks || 0)} stale fallbacks</p>
    </div>
    <div class="suggestion compact-suggestion health-${operations.status === "degraded" ? "degraded" : "fresh"}">
      <div class="suggestion-top">
        <strong>Evidence collection</strong>
        <span class="status-pill ${operations.status === "degraded" ? "status-warning" : "status-connected"}">${operations.status === "degraded" ? "Needs attention" : "Operational"}</span>
      </div>
      <p>${Number(shadow.settled || 0)}/${Number(shadow.queued || 0)} shadow predictions settled across ${Number(shadow.cohorts || 0)} daily cohorts.</p>
      <p>${Number(researchMemory.active || 0)} active research facts · ${Number(researchMemory.outcome_linked || 0)} linked to settled outcomes · ${Number(researchMemory.expired || 0)} expired facts retained for audit.</p>
      <p class="subtle">Last scheduler run ${scheduler.ran_at ? formatDateTime(scheduler.ran_at) : "not recorded"} · Jobs ${escapeHtml((scheduler.jobs_run || []).join(", ") || "none")} · Last settlement attempt ${shadowSettlement.ran_at ? formatDateTime(shadowSettlement.ran_at) : "not recorded"}</p>
      ${(operations.warnings || []).map((warning) => `<p class="human-error">${escapeHtml(warning)}</p>`).join("")}
      ${(scheduler.failures || []).map((failure) => `<p class="human-error">${escapeHtml(failure.job || "Scheduled job")}: ${escapeHtml(failure.message || "The job did not complete.")}</p>`).join("")}
    </div>
    ${providers.map((provider) => `
      <div class="suggestion compact-suggestion health-${provider.status}">
        <div class="suggestion-top">
          <strong>${provider.name}</strong>
          <span class="status-pill status-${provider.status}">${friendlyStatus(provider.status)}</span>
        </div>
        <p>${provider.purpose} · ${provider.message}</p>
        <p class="subtle">
          ${escapeHtml(provider.data_role || "Unclassified")} ·
          ${escapeHtml(provider.settlement_suitability || "Not for settlement")} ·
          ${provider.officially_documented ? "Officially documented" : "Undocumented endpoint"} ·
          Contract ${escapeHtml(provider.contract_version || "unversioned")}
        </p>
        <p class="subtle">${provider.api_usage?.used_this_session
          ? `${Number(provider.api_usage.requests_avoided || 0)} calls avoided · ${Number(provider.api_usage.network_requests || 0)} network requests this session`
          : "Not requested in this session yet"}</p>
      </div>
    `).join("")}
    <div class="suggestion compact-suggestion endpoint-performance-card">
      <div class="suggestion-top">
        <strong>App response times</strong>
        <span class="status-pill ${Number(endpointPerformance.slow_requests || 0) ? "status-warning" : "status-connected"}">${Number(endpointPerformance.slow_requests || 0)} slow calls</span>
      </div>
      <p>${Number(endpointPerformance.requests || 0)} recent API calls measured · slow threshold ${Number(endpointPerformance.slow_threshold_ms || 1000)} ms</p>
      <div class="endpoint-timing-list">
        ${endpointRoutes.slice(0, 8).map((route) => `
          <div class="endpoint-timing-row ${route.slow ? "endpoint-slow" : ""}">
            <code>${escapeHtml(route.route)}</code>
            <span>${Number(route.average_ms || 0).toFixed(0)} ms avg</span>
            <span>${Number(route.p95_ms || 0).toFixed(0)} ms p95</span>
            <span>${Number(route.requests || 0)} calls</span>
          </div>
        `).join("") || `<p class="subtle">Response timing appears after the first app requests complete.</p>`}
      </div>
    </div>
  `;
}

async function loadNotifications() {
  const data = await api("/api/notifications");
  const notifications = sortNotifications(data.notifications);
  $("notification-list").innerHTML = notifications.map((note) => `
    <div class="suggestion compact-suggestion notification-${note.severity || "neutral"}">
      <div class="suggestion-top">
        <strong>${escapeHtml(note.title)}</strong>
        <span class="status-pill status-${note.severity || "neutral"}">${friendlyStatus(note.type)}</span>
      </div>
      <p>${escapeHtml(note.message)}</p>
    </div>
  `).join("") || `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>All clear</strong>
        <span class="status-pill status-connected">No alerts</span>
      </div>
      <p>No smart notifications right now.</p>
    </div>
  `;
}

async function loadDeployReadiness() {
  if (!$("deploy-readiness-list")) return;
  const data = await api("/api/deploy/readiness");
  $("deploy-readiness-list").innerHTML = `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${escapeHtml(friendlyStatus(data.status))}</strong>
        <span class="subtle">${Number(data.score || 0).toFixed(1)}/100</span>
      </div>
      <div class="checklist-grid">
        ${(data.checks || []).map((check) => `
          <div class="checklist-item status-${check.ok ? "checked" : check.required ? "warning" : "optional"}">
            <strong>${escapeHtml(check.label)}</strong>
            <span>${escapeHtml(check.status)}</span>
            <p>${escapeHtml(check.action)}</p>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

async function loadRefreshSchedule() {
  const data = await api("/api/automation/refresh-schedule");
  $("refresh-schedule-list").innerHTML = data.jobs.map((job) => `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${job.name}</strong>
        <span class="pill">${job.time}</span>
      </div>
      <p>${job.action}</p>
    </div>
  `).join("");
}

async function runDailyRefresh() {
  $("refresh-schedule-list").innerHTML = `<div class="suggestion">Running refresh jobs...</div>`;
  await api("/api/automation/run-daily-refresh", { method: "POST" });
  await Promise.all([loadRefreshSchedule(), loadDataHealth(), loadNotifications(), loadDashboard(), loadEntryProgress({ autoCheck: true, refreshProviders: true })]);
}

async function loadAdvantageCenter() {
  $("advantage-center-status").textContent = "Checking competitive edge signals...";
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const data = await api(`/api/dashboard/advantage-center?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}`);
  const top = data.top_recommendation;
  const freshness = data.data_freshness || {};
  const providerRows = freshness.providers || [];
  const providerReady = providerRows.length > 0 && providerRows.every((row) => ["fresh", "available", "connected"].includes(row.status));
  $("advantage-center-status").textContent = top
    ? `${data.competitive_features.length} competitive features active · ${data.sport} · Updated ${formatDateTime(freshness.as_of || data.as_of)}`
    : "Advantage Center is active, but no top recommendation is available for this board.";
  $("advantage-journey").innerHTML = [
    ["Live Props", providerReady, providerRows.map((row) => `${row.name}: ${friendlyStatus(row.status)}`).join(" · ") || "Provider check"],
    ["Freshness", providerReady, providerReady ? "Ready" : "Review"],
    ["Ranked", Boolean((data.opportunity_feed || []).length), `${(data.opportunity_feed || []).length} opportunities`],
    ["Evidence", Boolean(top), top ? `Trust ${Number(data.trust_score?.score || 0).toFixed(0)}` : "Waiting"],
    ["Paper", Boolean(top), top ? "Ready to add" : "Waiting"],
    ["Settle", false, "Automatic"],
    ["Calibrate", false, "Results"],
  ].map(([label, ready, detail]) => `
    <div class="journey-step ${ready ? "journey-ready" : ""}">
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(String(detail))}</span>
    </div>
  `).join("");
  $("advantage-center-list").innerHTML = `
    ${top ? `
      <div class="suggestion advantage-hero">
        <div class="suggestion-top">
          <span class="pill">Top Ranked</span>
          <strong>${escapeHtml(top.title || "Best Opportunity")}</strong>
          <span class="score-pill">${escapeHtml(top.grade || "-")} · ${Number(top.score || 0).toFixed(1)}</span>
        </div>
        <div class="advantage-hero-props">
          ${(top.props || []).map((prop) => `
            <div>
              <strong>${escapeHtml(prop.player || "")}</strong>
              <span>${directionBadge(prop.direction || "Over")} ${escapeHtml(prop.stat || "")} ${prop.line ?? ""}</span>
              <small>${pct(prop.confidence || 0)} confidence · Edge ${Number(prop.edge || 0).toFixed(2)}</small>
            </div>
          `).join("")}
        </div>
        <p>${escapeHtml(top.explanation?.summary || top.summary || "")}</p>
        ${dataStrengthBadges(top.props || [])}
        <div class="button-row">
          <button id="advantage-add-paper" type="button">Add as Paper Entry</button>
          <button class="secondary" data-view-shortcut="performance" type="button">View Calibration</button>
        </div>
      </div>
    ` : ""}
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>Recommendation Trust</strong>
        <span class="pill">${data.trust_score?.label || "No Data"}</span>
      </div>
      <h2>${Number(data.trust_score?.score || 0).toFixed(1)}</h2>
      <p>${(data.trust_score?.flags || ["No flags."]).join(" · ")}</p>
    </div>
    <div class="suggestion compact-suggestion">
      <strong>Best Line Finder</strong>
      <p>${data.best_line_finder?.message || "No line-shop data yet."}</p>
      <p class="subtle">${data.best_line_finder?.positive_edges || 0}/${data.best_line_finder?.checked || 0} legs with better numbers.</p>
    </div>
    <div class="suggestion compact-suggestion">
      <strong>Closing Line Value</strong>
      <p>${data.closing_line_value?.tracked_legs
        ? `${Number(data.closing_line_value?.positive_clv_rate || 0).toFixed(1)}% positive CLV · Avg ${Number(data.closing_line_value?.average_clv || 0).toFixed(2)}`
        : "Collecting verified closing lines"}</p>
      <p class="subtle">${data.closing_line_value?.tracked_legs || 0} verified · ${data.closing_line_value?.quarantined_legs || 0} legacy legs excluded</p>
    </div>
    <div class="suggestion compact-suggestion">
      <strong>Personal Profile</strong>
      <p>${(data.personal_profile?.strengths || []).slice(0, 2).join(" ")}</p>
      <p class="subtle">${(data.personal_profile?.weaknesses || []).slice(0, 1).join(" ")}</p>
    </div>
    <div class="suggestion compact-suggestion">
      <strong>Market Timing</strong>
      <p>${(data.timing_alerts || []).slice(0, 2).map((alert) => `${alert.type}: ${alert.player}`).join(" · ") || "No urgent timing alerts."}</p>
    </div>
    <div class="suggestion compact-suggestion">
      <strong>Bankroll Mode</strong>
      <p>${data.bankroll_strategy?.mode || "balanced"} · Unit ${money(data.bankroll_strategy?.unit_size || 0)} · Max ${Number(data.bankroll_strategy?.max_wager_pct || 0).toFixed(1)}%</p>
    </div>
  `;
  if ($("advantage-add-paper")) {
    $("advantage-add-paper").addEventListener("click", () => loadPaperProps(top.props || []));
  }
  document.querySelectorAll("#advantage-center-list [data-view-shortcut]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.viewShortcut));
  });
  $("watchlist-list").innerHTML = (data.watchlist_alerts || []).map((alert) => `
    <div class="suggestion compact-suggestion">
      <strong>${alert.player} · ${alert.direction} ${alert.stat}</strong>
      <p>${alert.platform} ${alert.line} · ${alert.reason}</p>
    </div>
  `).join("") || `<div class="suggestion compact-suggestion">No watchlist alerts yet.</div>`;
  renderSportsbookSync(data.sportsbook_integrations);
  loadBankrollStrategyFields(data.bankroll_strategy || {});
}

async function loadSportsbookSync() {
  const data = await api("/api/integrations/sportsbooks");
  renderSportsbookSync(data);
}

async function loadTrendingProps() {
  if (!$("trending-props-list")) return;
  const platform = $("trending-props-platform").value;
  const sport = $("trending-props-sport").value;
  state.trendingSelections.clear();
  updateTrendingSelectionActions();
  $("trending-props-status").textContent = `Loading ${sport} market activity...`;
  $("trending-props-list").innerHTML = Array.from({ length: 5 }, () => `<div class="skeleton-row"></div>`).join("");
  const data = await api(`/api/props/trending?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}&limit=15`);
  state.trendingProps = data.props || [];
  $("trending-props-count").textContent = `Top ${data.count || 0}`;
  $("trending-props-status").textContent = data.note || `${data.count || 0} end-to-end trackable props ranked by model and data strength.`;
  $("trending-props-list").innerHTML = state.trendingProps.map((prop, index) => `
    <div class="trending-prop-row">
      <input class="opportunity-select" type="checkbox" data-select-trending-prop="${index}" aria-label="Select ${escapeHtml(prop.player || "prop")}" />
      <span class="trending-rank">#${Number(prop.rank || index + 1)}</span>
      <span class="grade-chip" title="Grade combines model confidence and data quality">${escapeHtml(prop.grade || "-")}</span>
      <strong>${escapeHtml(prop.player || "Player")}<small>${escapeHtml(prop.platform || platform)} · ${escapeHtml(prop.game || "Matchup")}</small></strong>
      <span class="trending-stat">${escapeHtml(prop.stat || "Stat")} ${prop.line ?? "-"}</span>
      <span>${directionBadge(prop.direction || "Over")}</span>
      <span class="trending-count">Score ${Number(prop.grade_score || 0).toFixed(1)}</span>
      <button class="secondary" type="button" data-add-trending-prop="${index}">Add</button>
    </div>
  `).join("") || `<div class="suggestion compact-suggestion">No end-to-end trackable ${escapeHtml(sport)} props are trending right now.</div>`;
  document.querySelectorAll("[data-select-trending-prop]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => toggleTrendingPropSelection(checkbox));
  });
  document.querySelectorAll("[data-add-trending-prop]").forEach((button) => {
    button.addEventListener("click", () => addFeedProp(state.trendingProps[Number(button.dataset.addTrendingProp)]));
  });
}

function updateTrendingSelectionActions() {
  const count = state.trendingSelections.size;
  const sendButton = $("send-selected-trending");
  const clearButton = $("clear-selected-trending");
  if (sendButton) {
    sendButton.disabled = count === 0;
    sendButton.textContent = `Send selected (${count})`;
  }
  if (clearButton) clearButton.disabled = count === 0;
}

function toggleTrendingPropSelection(checkbox) {
  const index = Number(checkbox.dataset.selectTrendingProp);
  const prop = state.trendingProps[index];
  if (!prop) return;
  if (!checkbox.checked) {
    state.trendingSelections.delete(index);
    updateTrendingSelectionActions();
    return;
  }
  const selected = [...state.trendingSelections]
    .map((selectedIndex) => state.trendingProps[selectedIndex])
    .filter(Boolean);
  const selectedPlatform = selected[0]?.platform;
  if (selectedPlatform && prop.platform !== selectedPlatform) {
    checkbox.checked = false;
    $("trending-props-status").textContent = `A single entry cannot mix ${selectedPlatform} and ${prop.platform}. Send one sportsbook at a time.`;
    return;
  }
  const maximumLegs = providerMaximumLegs(prop.platform);
  if (state.trendingSelections.size >= maximumLegs) {
    checkbox.checked = false;
    $("trending-props-status").textContent = `${prop.platform} supports up to ${maximumLegs} legs in one entry.`;
    return;
  }
  state.trendingSelections.add(index);
  updateTrendingSelectionActions();
}

function clearTrendingPropSelection() {
  state.trendingSelections.clear();
  document.querySelectorAll("[data-select-trending-prop]").forEach((checkbox) => { checkbox.checked = false; });
  updateTrendingSelectionActions();
}

function sendSelectedTrendingProps() {
  const selected = [...state.trendingSelections]
    .sort((left, right) => left - right)
    .map((index) => state.trendingProps[index])
    .filter(Boolean);
  if (!selected.length) return;
  renderEntryPropsFromAnalyzed(selected.map(entryPropFromFeed));
  state.recommendationOrigin = true;
  setView("entries");
  $("entry-status").textContent = `${selected.length} top-ranked ${selected[0].platform} ${selected.length === 1 ? "prop" : "props"} loaded as one entry. Review and analyze before placing.`;
}

function renderSportsbookSync(data) {
  if (!$("sportsbook-sync-list") || !data) return;
  const liveMarketData = Boolean(data.market_data_connected);
  $("sportsbook-sync-list").innerHTML = `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${escapeHtml(data.headline || "Sportsbook sync")}</strong>
        <span class="status-pill ${liveMarketData ? "status-connected" : "status-degraded"}">${liveMarketData ? "Market connected" : data.import_ready ? "Import ready" : "Manual"}</span>
      </div>
      <p>${escapeHtml(data.next_step || "")}</p>
      <p class="subtle">${escapeHtml(data.privacy_note || "")}</p>
    </div>
    ${(data.connectors || []).map((connector) => `
      <div class="suggestion compact-suggestion">
        <div class="suggestion-top">
          <strong>${escapeHtml(connector.name)}</strong>
          <span class="status-pill status-${connector.status === "configured" ? "connected" : "degraded"}">${friendlyStatus(connector.status)}</span>
        </div>
        <p>${(connector.capabilities || []).map(escapeHtml).join(" · ") || "No capabilities configured."}</p>
        ${(connector.missing || []).length ? `<p class="subtle">Missing: ${(connector.missing || []).map(escapeHtml).join(" · ")}</p>` : ""}
      </div>
    `).join("")}
  `;
}

function loadBankrollStrategyFields(strategy) {
  if (!strategy || !$("strategy-mode")) return;
  $("strategy-mode").value = strategy.mode || "balanced";
  $("strategy-unit").value = strategy.unit_size ?? 10;
  $("strategy-max-pct").value = strategy.max_wager_pct ?? 5;
  $("strategy-open-exposure-pct").value = strategy.max_open_exposure_pct ?? 15;
  $("strategy-stop-loss-pct").value = strategy.stop_loss_pct ?? 12;
  $("strategy-max-player-entries").value = strategy.max_player_entries ?? 2;
  $("strategy-max-game-entries").value = strategy.max_game_entries ?? 3;
  $("strategy-max-market-entries").value = strategy.max_market_entries ?? 1;
  $("strategy-max-player-exposure").value = strategy.max_player_exposure_pct ?? 7.5;
  $("strategy-paper-first").checked = Boolean(strategy.paper_first);
  $("bankroll-strategy-status").textContent = `${strategy.mode || "balanced"} sizing · single ${Number(strategy.max_wager_pct || 0).toFixed(1)}% · exposure ${Number(strategy.max_open_exposure_pct || 0).toFixed(1)}% · player/game/market limits ${Number(strategy.max_player_entries || 2)}/${Number(strategy.max_game_entries || 3)}/${Number(strategy.max_market_entries || 1)}.`;
}

async function saveBankrollStrategy(event) {
  event.preventDefault();
  const payload = {
    mode: $("strategy-mode").value,
    unit_size: Number($("strategy-unit").value || 10),
    max_wager_pct: Number($("strategy-max-pct").value || 5),
    max_open_exposure_pct: Number($("strategy-open-exposure-pct").value || 15),
    stop_loss_pct: Number($("strategy-stop-loss-pct").value || 12),
    max_player_entries: Number($("strategy-max-player-entries").value || 2),
    max_game_entries: Number($("strategy-max-game-entries").value || 3),
    max_market_entries: Number($("strategy-max-market-entries").value || 1),
    max_player_exposure_pct: Number($("strategy-max-player-exposure").value || 7.5),
    paper_first: $("strategy-paper-first").checked,
  };
  const data = await api("/api/settings/bankroll-strategy", { method: "POST", body: JSON.stringify(payload) });
  loadBankrollStrategyFields(data.strategy);
  await loadPortfolioIntelligence();
  await loadAdvantageCenter();
}

async function loadPortfolioIntelligence(payload = null) {
  const target = $("portfolio-intelligence-summary");
  if (!target) return;
  const data = payload || await api("/api/portfolio/intelligence");
  const concentrations = data.concentrations || [];
  const sharedRisk = data.shared_leg_failure_risk || {};
  const exposureRows = (data.top_players || []).slice(0, 4).map((row) => `
    <span><strong>${escapeHtml(row.label)}</strong><small>${Number(row.entries)} entries · ${money(row.wager)}</small></span>
  `).join("");
  target.classList.remove("muted-card");
  target.innerHTML = `
    <div class="suggestion-top">
      <div><p class="eyebrow">Pending Portfolio</p><h3>${escapeHtml(data.status || "Balanced")}</h3></div>
      <span class="status-pill ${concentrations.length ? "status-warning" : "status-positive"}">${Number(data.score || 0)}/100</span>
    </div>
    <div class="metric-strip portfolio-metrics">
      <span><strong>${Number(data.pending_real_entries || 0)}</strong><small>Paid Entries</small></span>
      <span><strong>${money(data.open_wager || 0)}</strong><small>Open Wager</small></span>
      <span><strong>${Number(data.bankroll_exposure_pct || 0).toFixed(1)}%</strong><small>Bankroll Exposure</small></span>
      <span><strong>${Number(concentrations.length)}</strong><small>Limit Breaches</small></span>
      <span><strong>${Number(data.correlation_score || 0)}</strong><small>Correlation Risk</small></span>
    </div>
    ${exposureRows ? `<div class="metric-strip portfolio-exposure-strip">${exposureRows}</div>` : `<p class="subtle">No paid entries are currently pending.</p>`}
    <p class="subtle">${escapeHtml(sharedRisk.message || "No shared-leg risk detected.")}</p>
    ${(data.top_teams || []).slice(0, 3).length ? `<p class="subtle">Team exposure: ${(data.top_teams || []).slice(0, 3).map((row) => `${escapeHtml(row.label)} ${Number(row.entries)}`).join(" · ")}</p>` : ""}
    ${(data.top_stats || []).length ? `<p class="subtle">Stat exposure: ${(data.top_stats || []).slice(0, 3).map((row) => `${escapeHtml(row.label)} ${Number(row.entries)}`).join(" · ")} · Direction ${(data.directions || []).map((row) => `${escapeHtml(row.label)} ${Number(row.entries)}`).join(" / ")}</p>` : ""}
    ${concentrations.slice(0, 4).map((row) => `<p class="${row.severity === "danger" ? "danger-text" : "warning"}">${escapeHtml(row.message)}</p>`).join("")}
  `;
  renderActivePortfolioMonitor(data.monitor || {});
}

async function refreshPortfolioLines() {
  const status = $("portfolio-monitor-refresh-status");
  if (status) status.textContent = "Refreshing current lines for pending paid entries...";
  const data = await api("/api/portfolio/refresh-market-data", { method: "POST" });
  await loadPortfolioIntelligence(data.intelligence);
  if (status) {
    const providers = (data.providers || []).map((row) => `${row.platform}: ${friendlyStatus(row.status)}`).join(" · ");
    status.textContent = `${data.message}${providers ? ` ${providers}` : ""}`;
  }
}

function renderActivePortfolioMonitor(monitor) {
  const target = $("portfolio-monitor-list");
  const count = $("portfolio-monitor-count");
  if (!target || !count) return;
  const entries = monitor.entries || [];
  count.textContent = `${entries.length} pending`;
  count.className = `status-pill ${Number(monitor.action_count || 0) ? "status-warning" : "status-positive"}`;
  if (!entries.length) {
    target.innerHTML = `<div class="empty-state compact-empty"><strong>Nothing needs monitoring</strong><p>${escapeHtml(monitor.headline || "No paid entries are currently pending.")}</p></div>`;
    return;
  }
  target.innerHTML = `
    <p class="portfolio-monitor-headline">${escapeHtml(monitor.headline || "Pending entry monitoring is current.")}</p>
    ${entries.map((entry) => activePortfolioEntryCard(entry)).join("")}
  `;
}

function activePortfolioEntryCard(entry) {
  const status = String(entry.status || "Needs Refresh");
  const alerting = ["Review", "Watch", "Needs Refresh"].includes(status);
  const legs = entry.legs || [];
  return `
    <article class="suggestion compact-suggestion portfolio-monitor-card monitor-${status.toLowerCase().replaceAll(" ", "-")}">
      <div class="suggestion-top">
        <div>
          <strong>${escapeHtml(entry.platform || "Paid entry")} #${Number(entry.id || 0)}</strong>
          <span class="subtle">${money(entry.wager || 0)} · ${formatDateTime(entry.placed_at)}</span>
        </div>
        <span class="status-pill ${alerting ? "status-warning" : "status-positive"}">${escapeHtml(status)}</span>
      </div>
      <div class="portfolio-monitor-legs">
        ${legs.map((leg) => activePortfolioLegRow(leg)).join("")}
      </div>
      <p class="${status === "Review" ? "danger-text" : alerting ? "warning" : "subtle"}">${escapeHtml(entry.action || "Continue normal monitoring.")}</p>
    </article>
  `;
}

function activePortfolioLegRow(leg) {
  const value = leg.line_value;
  const valueLabel = value === null || value === undefined
    ? "Refresh needed"
    : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(1)} line value`;
  const current = leg.current_line === null || leg.current_line === undefined
    ? "Latest line unavailable"
    : `Latest ${Number(leg.current_line).toFixed(1)}`;
  const tone = leg.movement_status === "Adverse"
    ? "movement-adverse"
    : leg.movement_status === "Favorable"
      ? "movement-favorable"
      : "movement-neutral";
  return `
    <div class="portfolio-monitor-leg ${tone}">
      <div>
        <strong>${escapeHtml(leg.player || "Player")}</strong>
        <span>${escapeHtml(leg.direction || "Over")} ${escapeHtml(leg.stat || "Prop")} ${Number(leg.placed_line || 0).toFixed(1)}</span>
      </div>
      <div class="portfolio-leg-state">
        <strong>${escapeHtml(valueLabel)}</strong>
        <span>${escapeHtml(current)} · ${escapeHtml(leg.game_state || "Pregame")}</span>
      </div>
    </div>
  `;
}

async function saveWatchlistItem(event) {
  event.preventDefault();
  const payload = {
    player: $("watch-player").value.trim(),
    stat: $("watch-stat").value.trim(),
    sport: $("watch-sport").value,
    platform: $("watch-platform").value,
    direction: $("watch-direction").value,
    alert_when: $("watch-alert-when").value,
    target_line: $("watch-target-line").value === "" ? null : Number($("watch-target-line").value),
  };
  if (!payload.player) return;
  await api("/api/watchlist", { method: "POST", body: JSON.stringify(payload) });
  $("watchlist-form").reset();
  await loadAdvantageCenter();
}

async function analyzeBoost(event) {
  event.preventDefault();
  const payload = {
    player: $("boost-player").value.trim(),
    stat: $("boost-stat").value.trim(),
    sport: $("boost-sport").value,
    platform: $("boost-platform").value,
    direction: $("boost-direction").value,
    original_line: Number($("boost-original-line").value),
    boosted_line: Number($("boost-boosted-line").value),
  };
  if (!payload.player || !payload.stat) return;
  const data = await api("/api/market/boost-analysis", { method: "POST", body: JSON.stringify(payload) });
  $("boost-result").classList.remove("muted-card");
  $("boost-result").innerHTML = `
    <div class="suggestion-top">
      <strong>${data.recommendation}</strong>
      <span class="pill">${data.ev_delta > 0 ? "+" : ""}${pct(data.ev_delta)}</span>
    </div>
    <p>${data.player} ${data.direction} ${data.stat} · Projection ${data.projection}</p>
    <p>Original EV ${pct(data.original.ev)} · Boosted EV ${pct(data.boosted.ev)}</p>
    <p class="subtle">${data.reason}</p>
  `;
}

async function loadTimingAlerts() {
  $("timing-alert-status").textContent = "Checking EV, line movement, and confidence...";
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const params = new URLSearchParams({
    platform,
    sport,
    min_confidence: $("timing-min-confidence")?.value || "60",
    min_ev: $("timing-min-ev")?.value || "0",
    alert_type: $("timing-alert-type")?.value || "All",
    hide_outliers: $("timing-hide-outliers")?.checked ? "true" : "false",
  });
  const data = await api(`/api/market/timing-alerts?${params.toString()}`);
  $("timing-alert-status").textContent = data.count
    ? `${data.count} timing alerts · ${data.sport}`
    : "No market timing alerts for this filter.";
  $("timing-alert-list").innerHTML = data.alerts.map((alert, index) => `
    <div class="timing-alert timing-${alert.severity}">
      <div class="suggestion-top">
        <span class="pill">${alert.type}</span>
        <strong>${alert.action}</strong>
        <span class="subtle">Score ${alert.priority_score}</span>
      </div>
      <p><strong>${alert.player}</strong> · ${alert.direction} ${alert.stat} ${alert.line} · ${alert.platform} ${alert.sport}</p>
      <p>${alert.reason}</p>
      <div class="timing-metrics">
        <span>EV ${alert.expected_value > 0 ? "+" : ""}${pct(alert.expected_value)}</span>
        <span>Conf ${pct(alert.confidence)}</span>
        <span>Edge ${Number(alert.edge || 0).toFixed(2)}</span>
        <span>Move ${formatMovement(alert.movement)}</span>
      </div>
      <button class="secondary" data-load-timing-alert="${index}">Load Prop</button>
    </div>
  `).join("") || `<div class="suggestion">No timing alerts yet. Refresh props over time to build line history.</div>`;
  document.querySelectorAll("[data-load-timing-alert]").forEach((button) => {
    button.addEventListener("click", () => {
      const alert = data.alerts[Number(button.dataset.loadTimingAlert)];
      addFeedProp({
        player: alert.player,
        team: alert.player,
        league: alert.sport,
        stat: alert.stat,
        line: alert.line,
        projection: alert.projection,
        direction: alert.direction,
        platform: alert.platform,
        game: alert.game,
        game_time: alert.game_time || "",
        trending_count: 0,
      });
      $("entry-status").textContent = `Loaded market timing alert: ${alert.player} ${alert.direction} ${alert.stat}.`;
    });
  });
}

function openExplanationDrawer(explanation) {
  if (!explanation) return;
  $("drawer-title").textContent = explanation.title || "Why this pick?";
  $("drawer-content").innerHTML = `
    <div class="grade">${explanation.grade || "-"}</div>
    <p>${explanation.summary || ""}</p>
    <div class="stats-grid" style="margin-top:14px">
      <div class="stat-card"><div class="stat-value">${Number(explanation.score || 0).toFixed(1)}</div><div class="stat-label">Score</div></div>
      <div class="stat-card"><div class="stat-value">${pct(explanation.average_confidence)}</div><div class="stat-label">Avg Confidence</div></div>
      <div class="stat-card"><div class="stat-value">${Number(explanation.average_edge || 0).toFixed(2)}</div><div class="stat-label">Avg Edge</div></div>
      <div class="stat-card"><div class="stat-value">${explanation.source_count || 0}</div><div class="stat-label">Data Sources</div></div>
    </div>
    <div class="analysis-card" style="margin-top:14px">
      <h3>Why EdgeIQ Likes It</h3>
      <p>${explanation.why || "The card blends confidence, edge, source agreement, and timing."}</p>
      <p><strong>Trust:</strong> ${Number(explanation.trust?.score || 0).toFixed(1)} · ${explanation.trust?.label || "No Data"} · <strong>Timing:</strong> ${explanation.timing?.label || "Monitor"}</p>
      ${(explanation.evidence || []).length ? `
        <div class="evidence-list">
          ${explanation.evidence.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
        </div>
      ` : ""}
      ${explanation.freshness ? `<p><strong>Freshness:</strong> ${escapeHtml(explanation.freshness.label || "Unknown")}</p>` : ""}
    </div>
    <div class="analysis-card" style="margin-top:14px">
      <h3>What Could Break It</h3>
      ${(explanation.breakers || []).map((item) => `<p>${item}</p>`).join("")}
      <p class="warning">${explanation.no_bet_rule || ""}</p>
    </div>
    <h3>Leg Breakdown</h3>
    <div class="suggestion-list">
      ${(explanation.legs || []).map((leg) => `
        <div class="suggestion compact-suggestion">
          <div class="suggestion-top">
            <strong>${leg.player}</strong>
            <span class="subtle">${leg.platform} · ${leg.sport}</span>
          </div>
          <p>${leg.pick} · Projection ${leg.projection ?? "-"} · Confidence ${pct(leg.confidence)} · Edge ${Number(leg.edge || 0).toFixed(2)}</p>
        </div>
      `).join("")}
    </div>
    ${(explanation.signals || []).length ? `
      <h3>Source Signals</h3>
      <div class="suggestion-list">
        ${explanation.signals.map((signal) => `
          <div class="suggestion compact-suggestion">
            <strong>${signal.source} · ${signal.player}</strong>
            <p>${signal.message}</p>
          </div>
        `).join("")}
      </div>
    ` : ""}
    ${(explanation.warnings || []).length ? `<p class="warning">${explanation.warnings.join(" · ")}</p>` : ""}
  `;
  $("recommendation-drawer").hidden = false;
}

function closeExplanationDrawer() {
  $("recommendation-drawer").hidden = true;
}

function suggestionExplanation(suggestion, title = "Suggested Entry") {
  const props = suggestion.entry?.props || [];
  const avgConfidence = props.length ? props.reduce((sum, prop) => sum + Number(prop.confidence || 0), 0) / props.length : 0;
  const avgEdge = props.length ? props.reduce((sum, prop) => sum + Number(prop.edge || 0), 0) / props.length : 0;
  return {
    title,
    summary: `${suggestion.leg_count || props.length}-leg ${suggestion.risk_tier || "Standard"} recommendation from EdgeIQ's optimizer.`,
    grade: suggestion.grade,
    score: suggestion.score,
    average_confidence: avgConfidence,
    average_edge: avgEdge,
    source_count: new Set(props.flatMap((prop) => (prop.source_signals || []).map((signal) => signal.source))).size,
    sources: [],
    signals: props.flatMap((prop) => (prop.source_signals || []).map((signal) => ({ ...signal, player: prop.player }))).slice(0, 5),
    warnings: suggestion.warnings || [],
    legs: props.map((prop) => ({
      player: prop.player,
      pick: `${prop.direction || "Over"} ${prop.stat} ${prop.line}`,
      projection: prop.projection,
      confidence: prop.confidence,
      edge: prop.edge,
      platform: prop.platform,
      sport: prop.sport,
    })),
  };
}

function syncMobileSlip() {
  const count = state.entryProps.length;
  $("mobile-slip-count").textContent = count;
  $("mobile-slip-summary").textContent = count ? `${count} leg${count === 1 ? "" : "s"} loaded` : "No props loaded";
  $("mobile-slip-legs").innerHTML = state.entryProps.map((prop, index) => `
    <div class="mobile-slip-leg">
      <span>${index + 1}</span>
      <strong>${shortPropPickText(prop)}</strong>
      <small>${prop.line} · ${prop.projection == null ? "Auto" : prop.projection}</small>
    </div>
  `).join("") || `<p class="subtle">Load a recommendation or add props from the board.</p>`;
  $("mobile-place-entry").disabled = count < 2 || state.placementInFlight || !state.lastEntryPayload;
  syncEntryActionLabels();
  if ($("entry-wager").value && !$("mobile-slip-wager").value) $("mobile-slip-wager").value = $("entry-wager").value;
  if ($("entry-multiplier").value && !$("mobile-slip-multiplier").value) $("mobile-slip-multiplier").value = $("entry-multiplier").value;
}

function clampProgress(value, min = 0, max = 100) {
  const number = Number(value || 0);
  if (Number.isNaN(number)) return min;
  return Math.max(min, Math.min(max, number));
}

function renderProgressLeg(leg) {
  const progress = clampProgress(leg.progress_percent);
  const bubblePosition = clampProgress(leg.stat_bubble_position || progress, 6, 94);
  const hasLiveStat = leg.actual !== null && leg.actual !== undefined;
  const bubbleEdgeClass = bubblePosition <= 10 ? " bubble-left" : bubblePosition >= 90 ? " bubble-right" : "";
  return `
    <div class="progress-leg progress-leg-${leg.timeline_status || "pending"}">
      <div class="progress-leg-player">
        <strong>${leg.player}</strong>
        <span>${leg.team || leg.game || "Team TBD"}</span>
      </div>
      <span class="leg-matchup">
        <span>${leg.game || leg.team || "Matchup TBD"}</span>
        <span class="leg-time-chip">${formatGameTime(leg.game_time_label)}</span>
      </span>
      <span class="leg-pick">
        <span class="timeline-chip timeline-${leg.timeline_status || "pending"}">${leg.timeline_label || leg.status}</span>
        <span>${directionBadge(leg.direction || "Over")} ${leg.stat}</span>
        <strong>${leg.line}</strong>
      </span>
      <span class="leg-progress-cell">
        <span class="leg-progress-copy">${leg.progress_text}</span>
        <span class="leg-meter ${hasLiveStat ? "has-live-stat" : ""}" aria-label="${leg.progress_label}">
          <span class="leg-meter-fill ${leg.status === "Win" ? "is-win" : leg.status === "Loss" ? "is-loss" : ""}" style="width:${progress}%"></span>
          <span class="leg-target-marker" aria-hidden="true"></span>
          <span class="leg-stat-bubble${bubbleEdgeClass}" style="left:${bubblePosition}%">${leg.stat_bubble || leg.progress_label}</span>
        </span>
      </span>
      <span class="leg-meta">
        <span class="leg-clv ${leg.clv && leg.clv.clv < 0 ? "danger-text" : ""}">CLV ${leg.clv && leg.clv.clv != null ? Number(leg.clv.clv).toFixed(1) : "-"}</span>
        <span class="leg-result ${leg.status === "Loss" ? "danger-text" : ""}">${leg.status}</span>
      </span>
      ${leg.settlement_note ? `<span class="leg-settlement-note">${escapeHtml(leg.settlement_note)}</span>` : ""}
    </div>
  `;
}

function renderProgressTimeGroups(entry) {
  const groups = entry.time_groups && entry.time_groups.length
    ? entry.time_groups
    : [{ game_time_label: entry.next_game_time_label, legs: entry.legs || [] }];
  return groups.map((group) => `
    <div class="progress-time-group">
      <div class="progress-time-heading">
        <span>${formatGameTime(group.game_time_label)}</span>
        <small>${group.legs.length} leg${group.legs.length === 1 ? "" : "s"}</small>
      </div>
      <div class="progress-legs">
        ${group.legs.map(renderProgressLeg).join("")}
      </div>
    </div>
  `).join("");
}

async function loadEntryProgress(options = {}) {
  const params = new URLSearchParams();
  if (options.autoCheck === true) params.set("auto_check", "true");
  if (options.refreshProviders === true) params.set("refresh_providers", "true");
  if (options.marketDetail === false) params.set("market_detail", "false");
  const query = params.toString();
  const data = await api(`/api/entries/progress${query ? `?${query}` : ""}`);
  const settled = data.auto_check && data.auto_check.settled ? ` · settled ${data.auto_check.settled}` : "";
  const liveSync = data.live_stats_sync || {};
  const settlementSync = data.settlement_refresh || {};
  const liveDetail = liveSync.skipped
    ? ""
    : ` · ESPN fetched ${liveSync.fetched_rows || 0}, saved ${liveSync.imported || 0}`;
  const automaticDetail = settlementSync.ran_at
    ? ` · automatic check ${formatDateTime(settlementSync.ran_at)}`
    : "";
  $("entry-progress-status").textContent = data.active
    ? `${data.active} active entries · ${data.with_live_stats} with live stat data${settled}${liveDetail}${automaticDetail}`
    : data.auto_check && data.auto_check.settled
      ? `No active placed entries · settled ${data.auto_check.settled}${liveDetail}`
      : "No active placed entries.";
  if (data.settlement_sla?.overdue_legs) {
    $("entry-progress-status").textContent += ` · ${data.settlement_sla.overdue_legs} final-stat SLA overdue`;
  }
  $("entry-progress-list").innerHTML = data.entries.map((entry) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <span class="pill">#${entry.id}</span>
        <strong class="${entry.live_result === "Loss" ? "danger-text" : ""}">${entry.tracker_status || entry.live_result}</strong>
        <span class="pill">${formatGameTime(entry.next_game_time_label)}</span>
        <span class="subtle">${entry.completed_legs}/${entry.total_legs} final · ${entry.source}</span>
      </div>
      <p>Confidence ${pct(entry.average_confidence)} · Edge ${Number(entry.average_edge).toFixed(2)} · Projected ${entry.projected_result} · ${formatDateTime(entry.placed_at)}</p>
      ${entry.settlement_sla?.overdue_legs ? `<p class="danger-text">${entry.settlement_sla.overdue_legs} leg${entry.settlement_sla.overdue_legs === 1 ? "" : "s"} exceeded the final-stat SLA. Use Recheck Final Stats.</p>` : ""}
      ${renderProgressTimeGroups(entry)}
    </div>
  `).join("") || `<div class="suggestion">No active placed entries.</div>`;
  if (data.auto_check && data.auto_check.settled) {
    Promise.allSettled([
      loadDashboard(),
      loadPending(),
      loadBets(),
      loadPerformance(),
      loadAccuracyLab(),
    ]).then((results) => {
      const failure = results.find((result) => result.status === "rejected");
      if (failure) console.warn("Post-settlement panel refresh failed", failure.reason);
    });
  }
}

async function loadProps(options = {}) {
  const cascade = options.cascade !== false;
  $("props-status").textContent = "Loading props...";
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const data = await api(`/api/props/top?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}`);
  $("props-status").textContent = sport === "All Sports"
    ? `Grouped by sport · showing up to ${data.per_sport_limit} unique-player props per sport`
    : `Showing top ${data.props.length} unique-player ${sport} props`;
  $("props-table").innerHTML = renderPropRows(data.props, platform, sport);
  document.querySelectorAll("[data-add-prop]").forEach((button) => {
    button.addEventListener("click", () => addFeedProp(data.props[Number(button.dataset.addProp)]));
  });
  document.querySelectorAll("[data-player-detail]").forEach((button) => {
    button.addEventListener("click", () => loadPlayerDetail(data.props[Number(button.dataset.playerDetail)]));
  });
  if (!cascade) return;
  Promise.allSettled([
    loadTrendingGames(platform, sport),
    loadDailyBriefing(),
    loadTimingAlerts(),
  ]);
}

function renderPropRows(props, platform, sport) {
  let previousSport = "";
  return (props || []).map((prop, index) => {
    const propSport = prop.league || prop.sport || sport || "";
    const showGroup = sport === "All Sports" && propSport !== previousSport;
    previousSport = propSport;
    const groupRow = showGroup ? `
      <tr class="sport-group-row">
        <td colspan="10">
          <span>${escapeHtml(propSport || "Other")}</span>
          <small>Top ${Number(prop.sport_rank || 1)}-${Math.min(5, Number(prop.sport_rank || 1) + ((props || []).slice(index + 1).filter((row) => (row.league || row.sport || "") === propSport).length))} shown for this sport</small>
        </td>
      </tr>
    ` : "";
    return `${groupRow}
    <tr>
      <td><span class="sport-rank-chip">${escapeHtml(propSport || "")} #${prop.sport_rank || index + 1}</span></td>
      <td>${prop.platform || platform}</td>
      <td>
        <button class="link-button" data-player-detail="${index}">${escapeHtml(prop.player)}</button>
        <button class="micro-button" data-add-prop="${index}">+</button>
      </td>
      <td>${directionBadge(prop.direction || "Over")}${String(prop.line_offer_type || "").toLowerCase() === "demon" ? `<small class="offer-rule-label">Demon · Over only</small>` : ""}</td>
      <td>${escapeHtml(prop.league || "")}</td>
      <td>${escapeHtml(prop.stat || "")}</td>
      <td>${prop.line ?? "-"}</td>
      <td>${escapeHtml(prop.game || "")}${prop.game_time ? ` · ${formatGameTime(prop.game_time)}` : ""}</td>
      <td>${Number(prop.trending_count || 0).toLocaleString()}</td>
      <td><button class="secondary" data-add-prop="${index}">Add</button></td>
    </tr>`;
  }).join("");
}

async function askAiParlay() {
  $("ai-parlay-status").textContent = "Finding today's best fit...";
  $("ai-parlay-response").classList.add("muted-card");
  $("ai-parlay-response").textContent = "Scoring candidates, checking risk, and looking for clean alternatives...";
  const data = await api("/api/ai/parlay-chat", {
    method: "POST",
    body: JSON.stringify({
      message: $("ai-parlay-input").value || "you need a parlay?",
      platform: $("props-platform").value,
      sport: $("props-sport").value,
    }),
  });
  state.lastAiRecommendation = data;
  $("ai-parlay-status").textContent = data.ai_enabled
    ? `${data.ai_provider || "AI"} assisted · ${data.model}`
    : `EdgeIQ Local · ${data.model} · ${data.request?.risk_profile || "balanced"} · ${data.request?.sport_label || "All Sports"} · ${data.request?.leg_count || 3} legs${data.ai_error ? ` · ${humanizeErrorText(data.ai_error)}` : ""}`;
  $("ai-parlay-response").classList.remove("muted-card");
  renderAiParlayResponse(data);
}

function renderAiParlayResponse(data) {
  const suggestion = data.suggestion;
  const props = suggestion?.entry?.props || [];
  const reasons = data.local_model?.reasons || [];
  const cautions = data.local_model?.cautions || [];
  const alternatives = data.alternatives || [];
  $("ai-parlay-response").innerHTML = `
    <div class="ai-answer-header">
      <span class="status-pill status-connected">${escapeHtml(data.request?.risk_profile || "balanced")}</span>
      <span class="status-pill ${data.request?.confirmed_only ? "status-connected" : "status-degraded"}">${data.request?.confirmed_only ? "confirmed board" : escapeHtml(data.search?.source || "provider board")}</span>
      <span class="status-pill status-available">${escapeHtml(data.request?.sport_label || "All Sports")}</span>
    </div>
    <p>${escapeHtml(data.message)}</p>
    ${suggestion ? `
      <div class="ai-slip-summary">
        <div>
          <strong>${escapeHtml(suggestion.grade || "-")} · ${escapeHtml(suggestion.action || "Recommendation")}</strong>
          <p>${escapeHtml(suggestion.leg_count || props.length)} legs · ${escapeHtml(suggestion.risk_tier || "Standard")} · score ${Number(data.local_model?.selected_score || suggestion.score || 0).toFixed(1)}</p>
          ${suggestionMetaRow(suggestion)}
          ${confidenceMoveNotes(props)}
        </div>
        <button class="secondary" data-load-ai-suggestion="0">Load</button>
        <button class="secondary" data-explain-ai-suggestion>Why?</button>
      </div>
      <div class="ai-leg-list">
        ${props.map((prop) => `
          <div class="ai-leg-row">
            <strong>${escapeHtml(prop.player)}</strong>
            <span>${directionBadge(prop.direction || "Over")} ${escapeHtml(prop.stat)} ${escapeHtml(prop.line ?? "")}</span>
            <small>${escapeHtml(prop.sport || "")}${prop.game ? ` · ${escapeHtml(prop.game)}` : ""}</small>
          </div>
        `).join("")}
      </div>
    ` : ""}
    <div class="ai-reason-grid">
      <div>
        <strong>Why this one</strong>
        ${(reasons.length ? reasons : ["Best available blend of confidence, edge, and data quality."]).map((reason) => `<p>${escapeHtml(reason)}</p>`).join("")}
      </div>
      <div>
        <strong>Watchouts</strong>
        ${(cautions.length ? cautions : ["Recheck injuries, game time, and line movement before placing."]).map((caution) => `<p>${escapeHtml(caution)}</p>`).join("")}
      </div>
    </div>
    ${alternatives.length ? `
      <div class="ai-alternatives">
        <strong>Alternatives</strong>
        ${alternatives.map((candidate, index) => `
          <button class="secondary ai-alt-button" data-load-ai-suggestion="${index + 1}">
            <span>${escapeHtml(candidate.grade || "-")} · ${escapeHtml(candidate.leg_count)} legs · ${escapeHtml((candidate.entry?.props || []).map((prop) => prop.player).join(", "))}</span>
            ${modelTrustBadge(candidate, candidate.entry?.props || [])}
          </button>
        `).join("")}
      </div>
    ` : ""}
  `;
  const loadable = [suggestion, ...alternatives].filter(Boolean);
  document.querySelectorAll("[data-load-ai-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      const selected = loadable[Number(button.dataset.loadAiSuggestion)];
      if (!selected) return;
      renderEntryPropsFromAnalyzed(selected.entry.props);
      state.recommendationOrigin = true;
      setView("entries");
      $("entry-status").textContent = "Loaded Ask EdgeIQ suggestion. Analyze/place when ready.";
    });
  });
  document.querySelector("[data-explain-ai-suggestion]")?.addEventListener("click", explainAiSuggestion);
}

async function explainAiSuggestion() {
  const current = state.lastAiRecommendation || {};
  if (!current.suggestion) return;
  $("copilot-response").classList.add("muted-card");
  $("copilot-response").textContent = "Checking the recommendation snapshot and alternatives...";
  const data = await api("/api/ai/explain-recommendation", {
    method: "POST",
    body: JSON.stringify({
      question: "Why is this card preferred, what could make it lose, and is there a stronger replacement leg?",
      suggestion: current.suggestion,
      alternatives: current.alternatives || [],
    }),
  });
  renderCopilotResponse(data);
}

async function askCopilot() {
  $("copilot-response").classList.add("muted-card");
  $("copilot-response").textContent = "Collecting verified EdgeIQ evidence...";
  const line = $("copilot-line").value;
  const data = await api("/api/ai/copilot", {
    method: "POST",
    body: JSON.stringify({
      question: $("copilot-question").value,
      player: $("copilot-player").value.trim(),
      stat: $("copilot-stat").value.trim(),
      line: line === "" ? null : Number(line),
      sport: $("props-sport").value,
      platform: $("props-platform").value,
    }),
  });
  renderCopilotResponse(data);
}

function renderCopilotResponse(data) {
  const response = data.response || {};
  const citationMap = new Map((data.citations || []).map((row) => [row.id, row]));
  $("copilot-response").classList.remove("muted-card");
  $("copilot-response").innerHTML = `
    <div class="ai-answer-header">
      <span class="status-pill status-connected">${escapeHtml(data.provider || "EdgeIQ Local")}</span>
      <span class="status-pill status-available">Grounded</span>
      <span class="subtle">${escapeHtml(data.model || "")}</span>
    </div>
    <section class="copilot-decision-brief">
      <div class="copilot-bottom-line"><span>Bottom line</span><h3>${escapeHtml(humanizeCopilotText(response.recommendation || "Evidence review"))}</h3><p>${escapeHtml(humanizeCopilotText(response.answer || "No answer was available."))}</p></div>
      <div class="copilot-brief-grid">
        <div><strong>Why</strong><ul>${(response.supporting_evidence || []).slice(0, 4).map((row) => `<li>${escapeHtml(humanizeCopilotText(row))}</li>`).join("") || "<li>No verified support was returned.</li>"}</ul></div>
        <div><strong>What could go wrong</strong><p>${escapeHtml(humanizeCopilotText(response.counterargument || "No counterargument was returned."))}</p></div>
        <div><strong>Suggested action</strong><p>${escapeHtml(humanizeCopilotText(response.suggested_correction || "No correction was suggested."))}</p></div>
        <div><strong>Still unknown</strong><ul>${(response.missing_information || []).slice(0, 4).map((row) => `<li>${escapeHtml(humanizeCopilotText(row))}</li>`).join("") || "<li>No important gaps were reported.</li>"}</ul></div>
      </div>
    </section>
    <div class="source-heading">Sources used</div>
    <div class="citation-row">
      ${(response.citations || []).map((id) => {
        const citation = citationMap.get(id);
        const label = escapeHtml(humanizeCopilotText(citation?.label || id));
        const timing = citation?.captured_at ? `Captured ${formatDateTime(citation.captured_at)}` : "Current EdgeIQ snapshot";
        return citation?.source_url
          ? `<a class="copilot-source" href="${escapeHtml(citation.source_url)}" target="_blank" rel="noopener" title="${label} · ${escapeHtml(timing)}">${label}</a>`
          : `<span class="copilot-source" title="${label} · ${escapeHtml(timing)}">${label}</span>`;
      }).join("")}
    </div>
    ${data.ai_error ? `<p class="subtle">${humanizeErrorText(data.ai_error)}</p>` : ""}
  `;
}

function humanizeCopilotText(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/[*`#]+/g, "")
    .replace(/[{}\[\]"]/g, "")
    .replace(/\s+/g, " ")
    .replace(/^[-*#\s]+/, "")
    .trim();
}

async function evaluateCopilotModel() {
  const data = await api("/api/ai/evaluate-model", {
    method: "POST",
    body: JSON.stringify({ model: $("copilot-model").value.trim() }),
  });
  const status = $("copilot-model-status");
  status.textContent = data.passed
    ? `${data.model} passed structured output and citation checks.`
    : `${data.model} is not qualified: ${humanizeErrorText(data.error || data.note)}`;
  status.className = data.passed ? "success-text" : "warning-text";
}

async function loadTrendingGames(platform = $("props-platform").value, sport = $("props-sport").value) {
  const data = await api(`/api/games/trending?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}`);
  $("trending-games-status").textContent = data.games.length
    ? `${data.games.length} popular games · ${data.ranked_player_count} ranked players in view`
    : "No trending games available.";
  $("trending-games-list").innerHTML = data.games.map((game) => {
    const players = game.ranked_players.length ? game.ranked_players : game.top_players;
    return `
      <div class="game-card">
        <div class="suggestion-top">
          <div>
            <span class="pill">${game.sport}</span>
            <strong>${game.game}</strong>
          </div>
          <span class="subtle">${Number(game.trending_count || 0).toLocaleString()} trending</span>
        </div>
        <p>${game.prop_count} props · ${game.ranked_player_count} ranked-player matches</p>
        <div class="player-chip-row">
          ${players.map((player) => `
            <span class="player-chip ${player.ranked ? "ranked" : ""}">
              ${player.player}${player.ranked ? " · ranked" : ""}
            </span>
          `).join("")}
        </div>
      </div>
    `;
  }).join("") || `<div class="suggestion">No trending games available.</div>`;
}

async function loadPlayerDetail(prop) {
  const detail = $("player-detail");
  detail.hidden = false;
  detail.classList.add("muted-card");
  detail.innerHTML = `Loading ${prop.player}...`;
  const data = await api(`/api/players/${encodeURIComponent(prop.player)}?platform=${encodeURIComponent(prop.platform || $("props-platform").value)}&sport=${encodeURIComponent(prop.league || $("props-sport").value)}`);
  detail.classList.remove("muted-card");
  detail.innerHTML = `
    <div class="suggestion-top">
      <div>
        <span class="pill">${data.sports.join(", ") || "Player"}</span>
        <strong>${data.player}</strong>
      </div>
      <button class="secondary" id="close-player-detail">Close</button>
    </div>
    <p>${data.teams.join(", ") || "Team unavailable"} · ${data.prop_count} active props · Avg confidence ${pct(data.average_confidence)} · Avg edge ${Number(data.average_edge).toFixed(2)}</p>
    ${playerResearchBars(data.props)}
    <div class="table-wrap compact">
      <table>
        <thead><tr><th>Platform</th><th>Stat</th><th>Line</th><th>Move</th><th>Hit Rate</th><th>Projection</th><th>Confidence</th><th></th></tr></thead>
        <tbody>
          ${data.props.map((playerProp, index) => `
            <tr>
              <td>${playerProp.platform}</td>
              <td>${directionBadge(playerProp.direction || "Over")} ${playerProp.stat}</td>
              <td>${playerProp.line}</td>
              <td>${formatMovement(playerProp.line_movement)}</td>
              <td>${pct(playerProp.hit_rate.estimated_hit_rate)}</td>
              <td>${playerProp.projection}</td>
              <td>${pct(playerProp.confidence)}</td>
              <td><button class="secondary" data-add-player-prop="${index}">Add</button></td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
  $("close-player-detail").addEventListener("click", () => {
    detail.hidden = true;
  });
  document.querySelectorAll("[data-add-player-prop]").forEach((button) => {
    button.addEventListener("click", () => addFeedProp({
      ...data.props[Number(button.dataset.addPlayerProp)],
      league: data.props[Number(button.dataset.addPlayerProp)].sport,
    }));
  });
}

function playerResearchBars(props = []) {
  const rows = [...props]
    .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))
    .slice(0, 6);
  if (!rows.length) return "";
  return `
    <div class="analysis-card player-research-bars">
      <h3>Prop Research Snapshot</h3>
      ${rows.map((prop) => {
        const confidence = Math.max(0, Math.min(100, Number(prop.confidence || 0)));
        const edge = Math.max(0, Math.min(100, Math.abs(Number(prop.edge || 0)) * 12));
        return `
          <div class="research-bar-row">
            <span>${escapeHtml(prop.stat)} ${prop.line ?? ""}</span>
            <div class="research-bar"><i style="width:${confidence}%"></i></div>
            <small>${pct(confidence)} conf · edge ${Number(prop.edge || 0).toFixed(2)}</small>
            <div class="research-bar edge-bar"><i style="width:${edge}%"></i></div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function formatMovement(movement) {
  if (!movement || movement.previous == null) return "flat";
  const prefix = movement.change > 0 ? "+" : "";
  return `${movement.direction} ${prefix}${Number(movement.change).toFixed(1)}`;
}

function entryPropFromFeed(prop) {
  const demonOnly = String(prop.platform || "").toLowerCase() === "prizepicks"
    && (String(prop.line_offer_type || "").toLowerCase() === "demon" || Boolean(prop.is_premium_line));
  return {
    player: prop.player,
    player_identity_id: prop.player_identity_id ?? null,
    player_provider: prop.player_provider || prop.platform || "",
    provider_player_id: prop.provider_player_id || prop.player_id || "",
    team: prop.team || "",
    position: prop.position || "",
    sport: prop.sport || prop.league || "WNBA",
    stat: prop.stat || "Points",
    line: Number(prop.line || 0),
    baseline_line: prop.baseline_line ?? null,
    standard_line: prop.standard_line ?? null,
    line_offer_type: prop.line_offer_type || "standard",
    adjusted_line: Boolean(prop.adjusted_line),
    is_discounted_line: Boolean(prop.is_discounted_line),
    is_premium_line: Boolean(prop.is_premium_line),
    line_discount: Number(prop.line_discount || 0),
    projection: prop.projection ?? null,
    direction: demonOnly ? "Over" : (prop.direction || "Over"),
    allowed_directions: demonOnly ? ["Over"] : (prop.allowed_directions || ["Over", "Under"]),
    platform: prop.platform || $("entry-platform").value,
    game: prop.game || "",
    game_time: prop.game_time || "",
    season_type: prop.season_type || prop.seasonType || "",
    trending_count: Number(prop.trending_count || 0),
    auto_projected: prop.auto_projected,
    provider_backed: prop.provider_backed,
    projection_source: prop.projection_source,
    model_version: prop.model_version || "",
    feature_as_of: prop.feature_as_of || "",
    forecast_snapshot: prop.forecast_snapshot || {},
    forecast_paid_eligible: Boolean(prop.forecast_paid_eligible),
    data_quality: prop.data_quality,
    data_strength: prop.data_strength,
    end_to_end_confirmed: Boolean(prop.end_to_end_confirmed),
    settlement_provider: prop.settlement_provider || "",
    recommendation_snapshot_id: prop.recommendation_snapshot_id || "",
  };
}

function entrySourcePlatforms(props = state.entryProps) {
  return [...new Set((props || []).map((prop) => String(prop.platform || "").trim()).filter(Boolean))];
}

function syncEntryPlatformFromProps(props = state.entryProps) {
  const platforms = entrySourcePlatforms(props);
  if (platforms.length === 1 && $("entry-platform")) {
    $("entry-platform").value = platforms[0];
  }
  return platforms;
}

function providerBaseMultiplier(platform, legCount) {
  const schedules = {
    PrizePicks: { 2: 3, 3: 6, 4: 10, 5: 20, 6: 37.5 },
    Underdog: { 2: 3.5, 3: 6.5, 4: 10, 5: 20, 6: 35, 7: 65, 8: 120 },
  };
  return schedules[platform]?.[Number(legCount)] || null;
}

function providerMaximumLegs(platform) {
  if (platform === "Underdog") return 8;
  if (platform === "PrizePicks" || platform === "DraftKings Pick6") return 6;
  return 5;
}

function addFeedProp(prop) {
  const nextProp = entryPropFromFeed(prop);
  const existingPlatforms = entrySourcePlatforms();
  if (existingPlatforms.length && nextProp.platform && !existingPlatforms.includes(nextProp.platform)) {
    $("entry-status").textContent = `This entry already contains ${existingPlatforms[0]} props. Build a separate ${nextProp.platform} entry.`;
    return;
  }
  state.entryProps.push(nextProp);
  state.recommendationSnapshotId = nextProp.recommendation_snapshot_id || state.recommendationSnapshotId;
  syncEntryPlatformFromProps();
  renderEntryProps();
  setView("entries");
  const demonNote = nextProp.allowed_directions?.length === 1
    ? " PrizePicks Demon lines are Over-only."
    : "";
  $("entry-status").textContent = `${prop.player} added. Projection will auto-fill unless you enter one.${demonNote}`;
}

function loadPaperProps(props) {
  state.entryProps = (props || []).map(entryPropFromFeed);
  if ($("entry-mode")) $("entry-mode").value = "paper";
  if ($("entry-platform") && props[0]?.platform) $("entry-platform").value = props[0].platform;
  renderEntryProps();
  setView("entries");
  $("entry-status").textContent = `${state.entryProps.length} paper ${state.entryProps.length === 1 ? "prop" : "props"} loaded for review.`;
}

async function manageDatabase(action) {
  const result = await api(`/api/data/${action}`, { method: "POST" });
  const artifact = result[action === "backup" ? "backup" : "export"];
  $("data-management-status").textContent = `${action === "backup" ? "Backup" : "Export"} created: ${artifact.path}`;
}

function renderEntryProps() {
  const corrections = new Map((state.lastAnalysis?.corrections?.legs || []).map((leg) => [Number(leg.index), leg]));
  $("entry-props").innerHTML = state.entryProps.map((prop, index) => {
    const projection = prop.projection == null ? "Auto" : Number(prop.projection).toFixed(1);
    const directionalEdge = String(prop.direction || "Over").toLowerCase() === "under"
      ? Number(prop.line) - Number(prop.projection)
      : Number(prop.projection) - Number(prop.line);
    const edge = prop.projection == null ? "Auto" : `${directionalEdge >= 0 ? "+" : ""}${directionalEdge.toFixed(1)}`;
    const correction = corrections.get(index);
    const differs = correction?.action === "flip";
    return `
      <tr data-entry-leg="${index}">
        <td>${prop.player}</td>
        <td>${directionBadge(prop.direction || "Over")}${differs ? `<small class="model-disagreement">EdgeIQ: ${escapeHtml(correction.suggested_direction)}</small>` : ""}</td>
        <td>${prop.stat}</td>
        <td>${prop.line}</td>
        <td>${projection}</td>
        <td>${edge}</td>
        <td><button class="secondary compact-button" data-edit-prop="${index}">Edit</button><button class="danger compact-button" data-remove-prop="${index}">Remove</button></td>
      </tr>
      <tr class="entry-leg-editor" data-entry-editor="${index}" hidden>
        <td colspan="7">
          <div class="entry-leg-edit-grid">
            <label>Player<input data-edit-field="player" value="${escapeHtml(prop.player)}"></label>
            <label>Stat<input data-edit-field="stat" value="${escapeHtml(prop.stat)}"></label>
            <label>Line<input data-edit-field="line" type="number" step="0.1" value="${Number(prop.line)}"></label>
            <label>Projection<input data-edit-field="projection" type="number" step="0.1" value="${prop.projection == null ? "" : Number(prop.projection)}"></label>
            <label>Pick<select data-edit-field="direction"><option${prop.direction === "Over" ? " selected" : ""}>Over</option><option${prop.direction === "Under" ? " selected" : ""}>Under</option></select></label>
            <button class="secondary compact-button" data-save-prop="${index}">Apply</button>
          </div>
        </td>
      </tr>
    `;
  }).join("");
  document.querySelectorAll("[data-edit-prop]").forEach((button) => {
    button.addEventListener("click", () => {
      const editor = document.querySelector(`[data-entry-editor="${button.dataset.editProp}"]`);
      if (editor) editor.hidden = !editor.hidden;
    });
  });
  document.querySelectorAll("[data-save-prop]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.saveProp);
      const editor = document.querySelector(`[data-entry-editor="${index}"]`);
      const value = (field) => editor?.querySelector(`[data-edit-field="${field}"]`)?.value ?? "";
      state.entryProps[index] = {
        ...state.entryProps[index],
        player: value("player").trim(),
        stat: value("stat").trim(),
        line: Number(value("line")),
        projection: value("projection") === "" ? null : Number(value("projection")),
        direction: value("direction"),
      };
      state.lastAnalysis = null;
      state.lastEntryPayload = null;
      $("ai-review-entry").disabled = true;
      $("prepare-handoff").disabled = true;
      $("place-entry").disabled = true;
      renderEntryProps();
      $("entry-status").textContent = "Leg updated. Analyze the entry again before saving.";
    });
  });
  document.querySelectorAll("[data-remove-prop]").forEach((button) => {
    button.addEventListener("click", () => {
      state.entryProps.splice(Number(button.dataset.removeProp), 1);
      state.lastEntryPayload = null;
      $("ai-review-entry").disabled = true;
      $("prepare-handoff").disabled = true;
      $("place-entry").disabled = true;
      renderEntryProps();
    });
  });
  syncMobileSlip();
}

function propFromForm() {
  const projectionValue = $("prop-projection").value;
  return {
    player: $("prop-player").value.trim(),
    team: $("prop-team").value.trim(),
    sport: $("prop-sport").value,
    stat: $("prop-stat").value,
    line: Number($("prop-line").value),
    projection: projectionValue === "" ? null : Number(projectionValue),
    direction: $("prop-direction").value,
    platform: $("entry-platform").value,
    game: "",
    game_time: "",
    season_type: "",
    trending_count: 0,
  };
}

function entryPayload() {
  const entryMode = $("entry-mode")?.value || "real";
  const sourcePlatforms = syncEntryPlatformFromProps();
  const platform = sourcePlatforms.length === 1 ? sourcePlatforms[0] : $("entry-platform").value;
  return {
    platform,
    wager: entryMode === "paper" ? 0 : Number($("entry-wager").value || 0),
    multiplier: Number($("entry-multiplier").value || 1),
    payout_type: $("entry-payout-type")?.value || "standard",
    payout_schedule: parsePayoutSchedule($("entry-payout-schedule")?.value || ""),
    entry_mode: entryMode,
    tracking_override: false,
    recommended_by_app: Boolean(state.recommendationOrigin),
    recommendation_snapshot_id: state.recommendationSnapshotId || state.entryProps.find((prop) => prop.recommendation_snapshot_id)?.recommendation_snapshot_id || "",
    props: state.entryProps.map((prop) => ({ ...prop, platform: prop.platform || platform })),
  };
}

function parsePayoutSchedule(value) {
  const schedule = {};
  String(value || "").split(",").forEach((part) => {
    const [winsText, multiplierText] = part.split(":").map((item) => item.trim());
    const wins = Number(winsText);
    const multiplier = Number(multiplierText);
    if (Number.isInteger(wins) && wins >= 0 && Number.isFinite(multiplier) && multiplier >= 0) {
      schedule[String(wins)] = multiplier;
    }
  });
  return schedule;
}

function renderAnalysis(data) {
  const rec = data.recommendation;
  const risk = data.risk;
  const components = rec.components || {};
  const warnings = data.warnings || [];
  const espn = data.espn_context || {};
  const fusion = data.source_fusion || {};
  const platformValue = data.platform_value || {};
  const guardrails = data.risk_guardrails || [];
  const checklist = data.confirmation_checklist || [];
  const payout = data.payout_analysis || {};
  const payoutVerified = Boolean(data.platform_value?.payout_verified);
  const release = data.release_verdict || {};
  const corrections = data.corrections || {};
  const correctionRows = (corrections.legs || []).map((leg) => {
    const action = String(leg.action || "keep");
    const actionLabel = action === "flip" ? `Use ${leg.suggested_direction}` : action === "remove" ? "Remove" : "Keep";
    return `
      <div class="entry-correction correction-${escapeHtml(action)}">
        <div class="entry-correction-copy">
          <div class="suggestion-top">
            <strong>${escapeHtml(leg.player)} · ${escapeHtml(leg.stat)} ${Number(leg.line).toFixed(1)}</strong>
            <span class="status-pill status-${action === "keep" ? "positive" : action === "flip" ? "warning" : "danger"}">${escapeHtml(actionLabel)}</span>
          </div>
          <p>${escapeHtml(leg.message || "")}</p>
          <p class="subtle">${escapeHtml(leg.reason || "")} · ${Number(leg.confidence || 0).toFixed(1)}% confidence</p>
        </div>
        ${action === "flip" || action === "remove"
          ? `<button class="secondary compact-action" data-correction-action="${escapeHtml(action)}" data-correction-index="${Number(leg.index)}">${escapeHtml(actionLabel)}</button>`
          : ""}
      </div>`;
  }).join("");
  const espnRows = (data.entry.props || [])
    .filter((prop) => prop.espn && prop.espn.sample_size)
    .map((prop) => `
      <div class="suggestion compact-suggestion">
        <strong>${propPickText(prop)}</strong>
        <p>${Number(prop.espn.hit_rate || 0).toFixed(1)}% hit · ${prop.espn.sample_size} ESPN games · Recent avg ${prop.espn.recent_average ?? "-"}</p>
        <p class="subtle">${prop.projection_source === "espn_recent_form" ? "Projection adjusted with ESPN recent form" : "Projection reviewed against ESPN history"} · Confidence ${prop.espn.confidence_adjustment >= 0 ? "+" : ""}${Number(prop.espn.confidence_adjustment || 0).toFixed(1)}</p>
        ${confidenceMovementText(prop) ? `<p class="confidence-move-note">${escapeHtml(confidenceMovementText(prop))}</p>` : ""}
      </div>
    `).join("");
  const signalRows = (data.entry.props || [])
    .flatMap((prop) => (prop.source_signals || []).map((signal) => ({ prop, signal })))
    .map(({ prop, signal }) => `
      <div class="suggestion compact-suggestion">
        <strong>${signal.source} · ${prop.player}</strong>
        <p>${signal.message}</p>
        <p class="subtle">Projection ${signal.projection_delta >= 0 ? "+" : ""}${Number(signal.projection_delta || 0).toFixed(2)} · Confidence ${signal.confidence_delta >= 0 ? "+" : ""}${Number(signal.confidence_delta || 0).toFixed(1)}</p>
        ${Number(signal.confidence_delta || 0) ? `<p class="confidence-move-note">Why this moved: ${escapeHtml(signal.source)} changed confidence ${signal.confidence_delta > 0 ? "up" : "down"} ${Math.abs(Number(signal.confidence_delta || 0)).toFixed(1)} pts.</p>` : ""}
      </div>
    `).join("");
  const qualityRows = (data.entry.props || []).map((prop) => `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${prop.player}</strong>
        <span class="subtle">${prop.data_quality?.label || "unscored"} · ${Number(prop.data_quality?.score || 0).toFixed(0)}/100</span>
      </div>
      ${dataStrengthBadges([prop])}
      <p>${(prop.data_quality?.flags || []).join(" · ") || "No major data-quality warnings."}</p>
    </div>
  `).join("");
  const platformValueRows = (platformValue.legs || []).map((leg) => `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${escapeHtml(leg.player)} · ${escapeHtml(leg.stat)}</strong>
        <span class="subtle">${escapeHtml(leg.best_platform || "-")} ${leg.best_line ?? "-"}</span>
      </div>
      <p>${escapeHtml(leg.direction || "Over")} · selected ${escapeHtml(platformValue.selected_platform || "-")} ${leg.selected_line ?? "-"} · value ${Number(leg.best_value || 0) >= 0 ? "+" : ""}${Number(leg.best_value || 0).toFixed(2)}</p>
      ${leg.market_consensus?.available
        ? `<p class="subtle">Market ${Number(leg.market_consensus.market_probability || 0).toFixed(1)}% no-vig · ${Number(leg.market_consensus.book_count || 0)} exact-line books</p>`
        : `<p class="subtle">${escapeHtml(leg.market_consensus?.reason || "Exact-line market consensus unavailable.")}</p>`}
    </div>
  `).join("");
  const platformEconomicsRows = (platformValue.platforms || []).map((row) => {
    const economics = row.payout_analysis || {};
    const payoutEvidence = row.payout_evidence || {};
    return `<div class="suggestion compact-suggestion">
      <div class="suggestion-top"><strong>${escapeHtml(row.platform || "Platform")}</strong><span class="status-pill ${payoutEvidence.verified ? "status-connected" : "status-warning"}">${payoutEvidence.verified ? "Payout verified" : "Payout confirmation needed"}</span></div>
      <p>${payoutEvidence.verified
        ? `Expected value ${Number(economics.expected_value || 0) >= 0 ? "+" : ""}${Number(economics.expected_value || 0).toFixed(1)}% · profit chance ${Number(economics.profit_probability || 0).toFixed(1)}% · break-even ${Number(economics.break_even_probability || 0).toFixed(1)}%`
        : "Enter the exact payout shown in the provider app before using expected value to make a paid decision."}</p>
      <p class="subtle">${escapeHtml(payoutEvidence.note || economics.message || "Confirm the complete card payout.")}</p>
    </div>`;
  }).join("");
  $("entry-analysis").classList.remove("muted-card");
  $("entry-analysis").innerHTML = `
    <div class="grade">${escapeHtml(release.verdict || rec.verdict || rec.action || "Review")}</div>
    <h2>${escapeHtml(release.verdict || rec.action || "Review")} Verdict</h2>
    <p>${escapeHtml(release.summary || rec.reason || "")}</p>
    <div class="stats-grid" style="margin-top:14px">
      <div class="stat-card"><div class="stat-value">${Number(rec.score ?? 0).toFixed(1)}</div><div class="stat-label">Entry Score</div></div>
      <div class="stat-card"><div class="stat-value">${pct(risk.average_confidence)}</div><div class="stat-label">Avg Confidence</div></div>
      <div class="stat-card"><div class="stat-value">${Number(risk.average_edge).toFixed(2)}</div><div class="stat-label">Avg Edge</div></div>
      <div class="stat-card"><div class="stat-value">${risk.level}</div><div class="stat-label">Risk</div></div>
    </div>
    <p class="subtle">Score blend: confidence ${pct(components.average_confidence)} · edge ${Number(components.average_edge || 0).toFixed(2)} · source support ${Number(components.average_source_score || 0).toFixed(1)}</p>
    <div class="analysis-card correction-plan" style="margin-top:14px">
      <div class="suggestion-top">
        <h3>Suggested Corrections</h3>
        <span class="status-pill ${Number(corrections.change_count || 0) ? "status-warning" : "status-positive"}">${Number(corrections.change_count || 0)} changes</span>
      </div>
      <p>${escapeHtml(corrections.summary || "EdgeIQ reviewed every leg against the current model.")}</p>
      <div class="correction-list">${correctionRows || `<p class="subtle">No leg-level corrections are available.</p>`}</div>
    </div>
    <div class="analysis-card" style="margin-top:14px">
      <div class="suggestion-top">
        <h3>${payoutVerified ? "Verified Payout Economics" : "Estimated Payout Economics"}</h3>
        <span class="status-pill ${payoutVerified ? "status-connected" : "status-warning"}">${payoutVerified ? "Verified" : "Payout confirmation needed"}</span>
      </div>
      ${payoutVerified ? "" : '<p class="subtle">Your sportsbook connection verifies available lines and market odds, but it does not expose the exact Pick’em card payout. Enter the payout shown in the provider app to verify EV.</p>'}
      <div class="metric-strip">
        <span><strong>${payoutVerified ? `${Number(payout.expected_value || 0) >= 0 ? "+" : ""}${pct(payout.expected_value || 0)}` : "Unverified"}</strong><small>Expected Value</small></span>
        <span><strong>${Number(payout.expected_return || 0).toFixed(2)}x</strong><small>Expected Return</small></span>
        <span><strong>${pct(payout.profit_probability || 0)}</strong><small>Profit Chance</small></span>
        <span><strong>${pct(payout.break_even_probability || 0)}</strong><small>Provider Break-Even</small></span>
      </div>
      <p class="subtle">${escapeHtml(release.authoritative_platform || payout.platform || "Provider")} is authoritative for this verdict.</p>
      <p class="subtle">${escapeHtml(payout.message || "Confirm the final displayed payout before placing.")}</p>
    </div>
    <div class="analysis-card" style="margin-top:14px">
      <h3>Best App Value</h3>
      <p>${escapeHtml(platformValue.recommendation || "No cross-platform value check was available.")}</p>
      ${platformValue.recommended_platform ? `<p class="subtle">Recommended platform: ${escapeHtml(platformValue.recommended_platform)} · value delta ${Number(platformValue.value_delta || 0) >= 0 ? "+" : ""}${Number(platformValue.value_delta || 0).toFixed(2)}</p>` : ""}
      ${platformEconomicsRows}
      ${platformValueRows || `<p class="subtle">No matching PrizePicks/Underdog legs were found for comparison.</p>`}
    </div>
    <div class="analysis-card" style="margin-top:14px">
      <h3>Placement Guardrails</h3>
      ${guardrails.map((guard) => `<p class="${guard.severity === "danger" ? "danger-text" : guard.severity === "warning" ? "warning" : "subtle"}">${guard.message}</p>`).join("")}
    </div>
    <div class="analysis-card" style="margin-top:14px">
      <h3>Final Checklist</h3>
      <div class="checklist-grid">
        ${checklist.map((item) => `
          <div class="checklist-item status-${String(item.status || "").replaceAll(" ", "-")}">
            <strong>${item.label}</strong>
            <span>${item.status}</span>
            <p>${item.detail}</p>
          </div>
        `).join("")}
      </div>
    </div>
    <div class="analysis-card" style="margin-top:14px">
      <h3>Data Quality</h3>
      ${qualityRows}
    </div>
    <div class="analysis-card ${espn.props_with_history ? "" : "muted-card"}" style="margin-top:14px">
      <h3>ESPN Form Assist</h3>
      <p>${espn.props_with_history || 0} props with ESPN history${espn.average_hit_rate ? ` · ${Number(espn.average_hit_rate).toFixed(1)}% avg hit rate` : ""}</p>
      ${espnRows || `<p class="subtle">No matching ESPN final-stat history yet. Auto-check completed entries to import more box scores.</p>`}
    </div>
    <div class="analysis-card ${fusion.signal_count ? "" : "muted-card"}" style="margin-top:14px">
      <h3>Source Fusion</h3>
      <p>${fusion.signal_count || 0} signals${fusion.sources && fusion.sources.length ? ` · ${fusion.sources.join(", ")}` : ""}</p>
      ${signalRows || `<p class="subtle">No extra source signals found for this entry yet.</p>`}
    </div>
    ${warnings.length ? `<p class="warning">${warnings.join(" · ")}</p>` : ""}
  `;
  document.querySelectorAll("[data-correction-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.correctionIndex);
      const action = button.dataset.correctionAction;
      const correction = (corrections.legs || []).find((leg) => Number(leg.index) === index);
      if (!correction || !state.entryProps[index]) return;
      if (action === "flip") {
        state.entryProps[index].direction = correction.suggested_direction;
        $("entry-status").textContent = `${correction.player} changed to ${correction.suggested_direction}. Analyze again to refresh the verdict.`;
      } else if (action === "remove") {
        state.entryProps.splice(index, 1);
        $("entry-status").textContent = `${correction.player} removed. Analyze again to refresh the verdict.`;
      }
      state.lastAnalysis = null;
      state.lastEntryPayload = null;
      $("ai-review-entry").disabled = true;
      $("prepare-handoff").disabled = true;
      $("place-entry").disabled = true;
      renderEntryProps();
      $("entry-analysis").classList.add("muted-card");
      $("entry-analysis").innerHTML = "Analyze the revised entry to see its updated score, payout economics, and release checks.";
    });
  });
}

async function analyzeEntry() {
  if (state.entryProps.length < 2) {
    $("entry-status").textContent = "Add at least two props.";
    return;
  }
  const sourcePlatforms = entrySourcePlatforms();
  if (sourcePlatforms.length > 1) {
    $("entry-status").textContent = `This entry mixes ${sourcePlatforms.join(" and ")}. Build one entry per sportsbook.`;
    return;
  }
  const payload = entryPayload();
  const data = await api("/api/entries/analyze", { method: "POST", body: JSON.stringify(payload) });
  state.lastAnalysis = data;
  renderAnalysis(data);
  renderEntryPropsFromAnalyzed(data.entry.props);
  state.lastEntryPayload = entryPayload();
  $("ai-review-entry").disabled = false;
  const isPaper = payload.entry_mode === "paper";
  $("prepare-handoff").disabled = !isPaper && !data.release_verdict?.paid_allowed;
  $("place-entry").disabled = false;
  $("entry-status").textContent = isPaper
    ? "Entry analyzed. Save it as a paper entry when ready."
    : data.release_verdict?.paid_allowed
      ? "Paid-entry checks passed. Review before placing."
      : `${data.release_verdict?.verdict || "Not recommended"}: ${data.release_verdict?.reasons?.[0] || "Release checks did not pass."} You can still press Place Paid Entry to track your decision after reviewing the warning.`;
  syncEntryActionLabels();
}

async function reviewEntryWithAi() {
  if (state.entryProps.length < 2) {
    $("entry-status").textContent = "Analyze an entry before asking AI to review it.";
    return;
  }
  $("entry-status").textContent = "AI is reviewing the entry...";
  const data = await api("/api/ai/entry-review", {
    method: "POST",
    body: JSON.stringify({
      ...entryPayload(),
      question: "Should I place this entry? Identify strongest leg, weakest leg, and risk flags.",
    }),
  });
  $("entry-analysis").classList.remove("muted-card");
  $("entry-analysis").innerHTML += `
    <div class="analysis-card" style="margin-top:14px">
      <h3>AI Entry Review</h3>
        <p class="subtle">${data.ai_enabled ? `${escapeHtml(data.ai_provider || "AI")} assisted · ${escapeHtml(data.model)}` : `EdgeIQ Local review${data.ai_error ? ` · ${humanizeErrorText(data.ai_error)}` : ""}`}</p>
      <p>${data.review}</p>
    </div>
  `;
  $("entry-status").textContent = data.ai_enabled ? `${data.ai_provider || "AI"} review complete.` : "EdgeIQ Local review complete.";
}

async function prepareEntryHandoff() {
  const payload = state.lastEntryPayload || entryPayload();
  if (!payload.props || payload.props.length < 2) {
    $("entry-status").textContent = "Add and analyze at least two props before preparing handoff.";
    return;
  }
  payload.platform = $("entry-platform").value || payload.platform || "PrizePicks";
  payload.entry_mode = $("entry-mode")?.value || payload.entry_mode || "real";
  payload.wager = payload.entry_mode === "paper" ? 0 : Number($("entry-wager").value || payload.wager || 0);
  payload.multiplier = Number($("entry-multiplier").value || payload.multiplier || 1);
  payload.props = state.entryProps;
  $("entry-handoff").classList.remove("muted-card");
  $("entry-handoff").textContent = "Preparing platform handoff...";
  const data = await api("/api/entries/handoff", { method: "POST", body: JSON.stringify(payload) });
  renderEntryHandoff(data);
  $("entry-status").textContent = data.ready_for_handoff
    ? `Handoff ready for ${data.recommended_platform}.`
    : `Handoff prepared, but ${data.blocks?.[0] || "release checks still need review."}`;
}

function renderEntryHandoff(data) {
  $("entry-handoff").classList.remove("muted-card");
  $("entry-handoff").innerHTML = `
    <div class="suggestion-top">
      <div>
        <span class="pill">${escapeHtml(data.recommended_platform || data.platform || "Platform")}</span>
        <strong>${data.ready_for_handoff ? "Handoff Ready" : "Review Before Handoff"}</strong>
      </div>
      <span class="subtle">${data.legs?.length || 0} legs</span>
    </div>
    <p>${escapeHtml(data.platform_value?.recommendation || "Verify the best platform manually.")}</p>
    ${(data.blocks || []).map((block) => `<p class="danger-text">${escapeHtml(block)}</p>`).join("")}
    ${(data.warnings || []).slice(0, 3).map((warning) => `<p class="warning">${escapeHtml(warning)}</p>`).join("")}
    <div class="suggestion-list">
      ${(data.legs || []).map((leg, index) => `
        <div class="suggestion compact-suggestion ${leg.offer_status === "current" ? "insight-positive" : "insight-warning"}">
          <div class="suggestion-top">
            <strong>${index + 1}. ${escapeHtml(leg.player)}</strong>
            <span class="subtle">${escapeHtml(leg.best_platform || data.recommended_platform || "")} ${leg.best_line ?? leg.line}</span>
          </div>
          <p>${escapeHtml(leg.direction || "Over")} ${escapeHtml(leg.stat)} ${leg.line ?? ""}${leg.game ? ` · ${escapeHtml(leg.game)}` : ""}</p>
          <p class="subtle">Live offer: ${escapeHtml(leg.offer_status || "not checked")} · requested ${leg.requested_line ?? leg.line}${leg.current_line == null ? "" : ` · current ${leg.current_line}`}</p>
          <p class="subtle">${escapeHtml(leg.blocking_reason || leg.value_note || "")}</p>
        </div>
      `).join("")}
    </div>
    <div class="handoff-copy">${escapeHtml(data.copy_text || "")}</div>
    <div class="button-row">
      <button class="secondary" id="copy-handoff">Copy Slip</button>
      <button class="secondary" id="share-handoff">Share Slip</button>
      ${data.open_url && data.ready_for_handoff ? `<button class="secondary" id="open-handoff">Open ${escapeHtml(data.recommended_platform || "App")}</button>` : ""}
    </div>
  `;
  $("copy-handoff").addEventListener("click", async () => {
    const copied = await copyText(data.copy_text || "");
    $("entry-status").textContent = copied ? "Slip copied for manual entry." : "Copy is unavailable in this browser; use the handoff text.";
  });
  $("share-handoff").addEventListener("click", shareCurrentSlip);
  if ($("open-handoff")) {
    $("open-handoff").addEventListener("click", () => window.open(data.open_url, "_blank", "noopener"));
  }
}

async function shareCurrentSlip() {
  const payload = state.lastEntryPayload || entryPayload();
  payload.platform = $("entry-platform").value || payload.platform || "PrizePicks";
  payload.entry_mode = $("entry-mode")?.value || payload.entry_mode || "real";
  payload.wager = payload.entry_mode === "paper" ? 0 : Number($("entry-wager").value || payload.wager || 0);
  payload.multiplier = Number($("entry-multiplier").value || payload.multiplier || 1);
  payload.props = state.entryProps;
  payload.note = "Generated by EdgeIQ. Verify current provider lines before placing.";
  const data = await api("/api/entries/share", { method: "POST", body: JSON.stringify(payload) });
  const url = new URL(data.share_url, window.location.origin).toString();
  const copied = await copyText(url);
  $("entry-status").textContent = copied ? "Share link copied." : `Share link: ${url}`;
  $("entry-handoff").innerHTML += `<p class="subtle">Share link: <a href="${url}" target="_blank" rel="noopener">${url}</a></p>`;
}

function renderPlacementAudit(data) {
  const audit = data.audit || {};
  const protection = data.loss_protection || audit.loss_protection || {};
  const status = audit.status || (data.ok ? "clear" : "blocked");
  const tone = status === "clear" ? "positive" : status === "review" ? "warning" : "danger-text";
  $("entry-handoff").classList.remove("muted-card");
  $("entry-handoff").innerHTML = `
    <div class="placement-audit-card placement-${escapeHtml(status)}">
      <div class="suggestion-top">
        <div>
          <span class="pill">Final Entry Audit</span>
          <strong class="${tone}">${escapeHtml(friendlyStatus(status))} · ${Number(audit.score || 0).toFixed(0)}/100</strong>
        </div>
        <span class="subtle">${escapeHtml(audit.recommended_platform || data.platform_value?.recommended_platform || "Platform")}</span>
      </div>
      <div class="stats-grid" style="margin-top:14px">
        <div class="stat-card"><div class="stat-value">${money(audit.wager || 0)}</div><div class="stat-label">Wager</div></div>
        <div class="stat-card"><div class="stat-value">${money(audit.projected_exposure || 0)}</div><div class="stat-label">Open Exposure</div></div>
        <div class="stat-card"><div class="stat-value">${money(audit.open_exposure_cap || 0)}</div><div class="stat-label">Exposure Cap</div></div>
        <div class="stat-card"><div class="stat-value">${money(audit.bankroll || 0)}</div><div class="stat-label">Bankroll</div></div>
      </div>
      ${protection.label ? `
        <div class="entry-protection-inline ${protection.active ? "protection-active" : "protection-clear"}">
          <strong>${escapeHtml(protection.label)}</strong>
          <span>${escapeHtml((protection.reasons || [])[0] || "Recovery checks are clear.")}</span>
        </div>
      ` : ""}
      <div class="checklist-grid placement-audit-grid">
        ${(audit.items || []).map((item) => `
          <div class="checklist-item status-${escapeHtml(item.status || "review")}">
            <strong>${escapeHtml(item.label)}</strong>
            <span>${escapeHtml(item.status || "review")}</span>
            <p>${escapeHtml(item.detail || "")}</p>
          </div>
        `).join("")}
      </div>
      ${(data.blocks || []).map((block) => `<p class="danger-text">${escapeHtml(block)}</p>`).join("")}
      ${(data.warnings || []).slice(0, 4).map((warning) => `<p class="warning">${escapeHtml(warning)}</p>`).join("")}
    </div>
  `;
}

function renderEntryPropsFromAnalyzed(props) {
  state.entryProps = uniqueUploadedProps(props).map(entryPropFromFeed);
  syncEntryPlatformFromProps();
  renderEntryProps();
}

function uniqueUploadedProps(props) {
  const selected = new Map();
  (props || []).forEach((prop) => {
    const player = String(prop.player || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
    const stat = uploadedStatKey(prop.stat);
    const direction = String(prop.direction || "").toLowerCase();
    const key = [player, stat, Number(prop.line || 0).toFixed(4), direction, String(prop.platform || "").toLowerCase()].join("|");
    if (!selected.has(key)) selected.set(key, prop);
  });
  return [...selected.values()];
}

function uploadedStatKey(value) {
  const key = String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const aliases = {
    pra: "pointsreboundsassists",
    ptsrebsasts: "pointsreboundsassists",
    pa: "pointsassists",
    ptsasts: "pointsassists",
    pr: "pointsrebounds",
    ptsrebs: "pointsrebounds",
    ra: "reboundsassists",
    rebsasts: "reboundsassists",
  };
  return aliases[key] || key;
}

function chooseEntrySaveMode(reasons, paidAllowed = true) {
  return new Promise((resolve) => {
    const modal = $("entry-mode-choice");
    const paperButton = $("entry-choice-paper");
    const paidButton = $("entry-choice-paid");
    const cancelButton = $("entry-choice-cancel");
    const reasonText = (reasons || []).slice(0, 4).join(" ");
    $("entry-choice-message").textContent = paidAllowed
      ? `EdgeIQ considers this a weak paid entry. ${reasonText} Do you want to continue with a paid entry or switch to paper?`
      : `This entry cannot be tracked safely as paid. ${reasonText} You can still save it as a paper entry.`;
    paidButton.disabled = !paidAllowed;
    modal.hidden = false;
    const finish = (choice) => {
      modal.hidden = true;
      paperButton.onclick = null;
      paidButton.onclick = null;
      cancelButton.onclick = null;
      resolve(choice);
    };
    paperButton.onclick = () => finish("paper");
    paidButton.onclick = () => finish("paid");
    cancelButton.onclick = () => finish("cancel");
    paperButton.focus();
  });
}

async function placeEntry(triggerButton = $("place-entry")) {
  if (!state.lastEntryPayload) return false;
  const sourcePlatforms = syncEntryPlatformFromProps();
  if (sourcePlatforms.length > 1) {
    $("entry-status").textContent = `This entry mixes ${sourcePlatforms.join(" and ")}. Build one entry per sportsbook.`;
    finishCircuitFeedback(triggerButton, "warning");
    return false;
  }
  state.lastEntryPayload.entry_mode = $("entry-mode")?.value || state.lastEntryPayload.entry_mode || "real";
  state.lastEntryPayload.wager = state.lastEntryPayload.entry_mode === "paper" ? 0 : Number($("entry-wager").value || state.lastEntryPayload.wager || 0);
  state.lastEntryPayload.multiplier = Number($("entry-multiplier").value || state.lastEntryPayload.multiplier || 1);
  state.lastEntryPayload.payout_type = $("entry-payout-type")?.value || state.lastEntryPayload.payout_type || "standard";
  state.lastEntryPayload.payout_schedule = parsePayoutSchedule($("entry-payout-schedule")?.value || "");
  state.lastEntryPayload.platform = sourcePlatforms[0] || $("entry-platform").value || state.lastEntryPayload.platform || "PrizePicks";
  state.lastEntryPayload.props = state.entryProps;
  state.lastEntryPayload.tracking_override = false;
  if (state.lastEntryPayload.entry_mode !== "paper" && state.lastEntryPayload.wager <= 0) {
    $("entry-status").textContent = "Enter the amount wagered before placing.";
    playCircuitSound("warning");
    finishCircuitFeedback(triggerButton, "warning");
    return false;
  }
  let isPaper = state.lastEntryPayload.entry_mode === "paper";
  let placementCheck = { ok: true, blocks: [], warnings: [] };
  let modeChoiceConfirmed = false;
  if (!isPaper) {
    try {
      placementCheck = await api("/api/entries/placement-check", { method: "POST", body: JSON.stringify(state.lastEntryPayload) });
    } catch (error) {
      $("entry-status").textContent = `Provider check needs review: ${humanizeErrorText(error.message)}`;
      playCircuitSound("warning");
      finishCircuitFeedback(triggerButton, "warning");
      return false;
    }
    renderPlacementAudit(placementCheck);
    if (!placementCheck.ok) {
      const blockMessage = placementCheck.blocks?.[0] || "Provider check blocked this entry.";
      const choiceReasons = placementCheck.tracking_override_allowed
        ? placementCheck.blocks || [blockMessage]
        : placementCheck.tracking_blocks || [blockMessage];
      const choice = await chooseEntrySaveMode(choiceReasons, Boolean(placementCheck.tracking_override_allowed));
      if (choice === "cancel") {
        $("entry-status").textContent = "Entry save canceled. No wager or paper result was recorded.";
        playCircuitSound("warning");
        finishCircuitFeedback(triggerButton, "warning");
        return false;
      }
      if (choice === "paper") {
        state.lastEntryPayload.entry_mode = "paper";
        state.lastEntryPayload.wager = 0;
        state.lastEntryPayload.tracking_override = false;
        $("entry-mode").value = "paper";
        isPaper = true;
        syncEntryActionLabels();
      } else {
        state.lastEntryPayload.tracking_override = true;
      }
      modeChoiceConfirmed = true;
    }
  }
  const checkWarnings = [...(placementCheck.blocks || []), ...(placementCheck.warnings || [])];
  const valueText = placementCheck.platform_value?.recommendation
    ? `\n\nBest app value:\n- ${placementCheck.platform_value.recommendation}`
    : "";
  const checkText = isPaper
    ? "\n\nPaper entries do not affect bankroll. EdgeIQ will retain the verified game and stat context for settlement."
    : checkWarnings.length
    ? `\n\nProvider check:\n${checkWarnings.slice(0, 6).map((warning) => `- ${warning}`).join("\n")}${checkWarnings.length > 6 ? "\n- More warnings hidden." : ""}`
    : "\n\nProvider check passed: current lines and available game times were reviewed.";
  const paidPrompt = placementCheck.loss_protection?.active
    ? "Loss Protection is active and EdgeIQ recommends that you do not place this entry. Did you place it and want EdgeIQ to track it?"
    : "Will you place this entry?";
  const confirmed = modeChoiceConfirmed || window.confirm(
    (state.lastEntryPayload.entry_mode === "paper" ? "Save this as a paper entry for calibration?" : paidPrompt)
    + checkText
    + valueText
  );
  if (!confirmed) return false;
  triggerButton.textContent = "Saving...";
  let data;
  try {
    data = await api("/api/entries/place", { method: "POST", body: JSON.stringify(state.lastEntryPayload) });
  } catch (error) {
    $("entry-status").textContent = humanizeErrorText(error.message);
    playCircuitSound("warning");
    finishCircuitFeedback(triggerButton, "warning");
    return false;
  }
  $("entry-status").textContent = state.lastEntryPayload.entry_mode === "paper"
    ? `Paper entry #${data.id} saved${data.settlement_tracking === "verified" ? " for verified calibration." : " with manual final-stat verification required."}`
    : `Entry #${data.id} saved as pending${data.tracking_override ? " by user override" : ""}. Bankroll reserved ${money(state.lastEntryPayload.wager)}.${data.settlement_tracking === "verified" ? "" : " Manual final-stat verification is required for at least one leg."}`;
  playCircuitSound("success");
  finishCircuitFeedback(triggerButton, "success");
  state.entryProps = [];
  state.lastEntryPayload = null;
  state.lastAnalysis = null;
  state.recommendationOrigin = false;
  state.recommendationSnapshotId = "";
  if ($("entry-payout-schedule")) $("entry-payout-schedule").value = "";
  $("prepare-handoff").disabled = true;
  $("place-entry").disabled = true;
  renderEntryProps();
  Promise.allSettled([loadPending(), loadDashboard(), loadCommandCenter()]).then((results) => {
    const failure = results.find((result) => result.status === "rejected");
    if (failure) console.warn("Post-save panel refresh did not finish", failure.reason);
  });
  return true;
}

async function loadProviderSuggestions(platform, sportId, legsId, listId) {
  const list = $(listId);
  const sport = $(sportId).value;
  const legCount = Number($(legsId).value || 3);
  const historyKey = `${platform}|${sport}|${legCount}`;
  const recentPropKeys = state.generatorRecentProps[historyKey] || [];
  list.innerHTML = `<div class="suggestion">Building ${escapeHtml(platform)} ${legCount}-leg entries...</div>`;
  const avoidQuery = recentPropKeys.length ? `&avoid=${encodeURIComponent(recentPropKeys.join(","))}` : "";
  const data = await api(`/api/entries/suggestions?sport=${encodeURIComponent(sport)}&platform=${encodeURIComponent(platform)}&leg_count=${legCount}${avoidQuery}`);
  const generatedPropKeys = [...new Set(
    (data.suggestions || []).flatMap((suggestion) => suggestion.diversification?.prop_keys || []),
  )];
  if (generatedPropKeys.length) state.generatorRecentProps[historyKey] = generatedPropKeys.slice(0, 32);
  const diversity = data.diversification || {};
  const diversityNote = data.suggestions.length
    ? `<div class="generator-diversity-note">
        <strong>${Number(diversity.unique_props || 0)} unique props</strong>
        <span>${Number(diversity.reused_props || 0) ? `${Number(diversity.reused_props)} repeated only where the quality pool required it` : "No exact props repeated across this batch"}</span>
      </div>`
    : "";
  list.innerHTML = diversityNote + data.suggestions.map((suggestion, index) => `
    <div class="suggestion ${gradeClass(suggestion.grade)}">
      <div class="suggestion-top">
        <span class="pill">${escapeHtml(platform)} #${suggestion.rank} · ${suggestion.leg_count} Legs</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
        <span class="subtle">${suggestion.risk_tier || "Standard"} · Score ${suggestion.score}</span>
      </div>
      ${suggestionMetaRow(suggestion)}
      <p>${propPickList(suggestion.entry.props)}</p>
      ${confidenceMoveNotes(suggestion.entry.props)}
      ${releaseStatusBlock(suggestion.release_status)}
      ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
      <div class="button-row">
        <button class="secondary" data-load-provider-suggestion="${index}">Load ${escapeHtml(platform)}</button>
        <button class="secondary" data-explain-provider-suggestion="${index}">Why?</button>
      </div>
    </div>
  `).join("") || `<div class="suggestion">No ${escapeHtml(platform)} ${legCount}-leg card cleared the current filters. Try fewer legs or use paper calibration.</div>`;
  list.querySelectorAll("[data-load-provider-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.loadProviderSuggestion)];
      renderEntryPropsFromAnalyzed(suggestion.entry.props);
      const baseMultiplier = providerBaseMultiplier(platform, suggestion.leg_count);
      if (baseMultiplier && $("entry-multiplier")) $("entry-multiplier").value = String(baseMultiplier);
      if ($("entry-payout-type")) $("entry-payout-type").value = "standard";
      state.recommendationOrigin = true;
      setView("entries");
      $("entry-status").textContent = `Loaded ${suggestion.leg_count}-leg ${platform} entry #${suggestion.rank}. The builder detected ${platform} from its source lines.`;
    });
  });
  list.querySelectorAll("[data-explain-provider-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.explainProviderSuggestion)];
      openExplanationDrawer(suggestionExplanation(suggestion, `${platform} Entry #${suggestion.rank}`));
    });
  });
}

async function loadConfirmedEntries() {
  $("confirmed-entries-list").innerHTML = `<div class="suggestion">Building confirmed entries...</div>`;
  const sport = $("confirmed-sport").value;
  const platform = $("confirmed-platform").value;
  const data = await api(`/api/entries/confirmed-suggestions?sport=${encodeURIComponent(sport)}&platform=${encodeURIComponent(platform)}`);
  $("confirmed-props-status").textContent = `${data.confirmed_count} confirmed props used for entry generation · ${data.platform} ${data.sport}`;
  $("confirmed-entries-list").innerHTML = data.suggestions.map((suggestion, index) => `
    <div class="suggestion ${gradeClass(suggestion.grade)}">
      <div class="suggestion-top">
        <span class="pill">Confirmed #${suggestion.rank} · ${suggestion.leg_count} Legs</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
        <span class="subtle">${suggestion.risk_tier || "Standard"} · Score ${suggestion.score}</span>
      </div>
      ${suggestionMetaRow(suggestion)}
      <p>${propPickList(suggestion.entry.props)}</p>
      ${confidenceMoveNotes(suggestion.entry.props)}
      ${releaseStatusBlock(suggestion.release_status)}
      ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
      <div class="button-row">
        <button class="secondary" data-load-confirmed-entry="${index}">Load Confirmed Entry</button>
        <button class="secondary" data-explain-confirmed-entry="${index}">Why?</button>
      </div>
    </div>
  `).join("") || `<div class="suggestion">Not enough confirmed props to build entries for this filter.</div>`;
  document.querySelectorAll("[data-load-confirmed-entry]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.loadConfirmedEntry)];
      renderEntryPropsFromAnalyzed(suggestion.entry.props);
      state.recommendationOrigin = true;
      $("entry-status").textContent = `Loaded confirmed ${suggestion.leg_count}-leg entry #${suggestion.rank}. Analyze/place when ready.`;
    });
  });
  document.querySelectorAll("[data-explain-confirmed-entry]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.explainConfirmedEntry)];
      openExplanationDrawer(suggestionExplanation(suggestion, `Confirmed Entry #${suggestion.rank}`));
    });
  });
}

async function runOptimizer(portfolioBatch = false) {
  $("optimizer-list").innerHTML = `<div class="suggestion">${portfolioBatch ? "Building five diversified cards..." : "Optimizing slips..."}</div>`;
  await loadPortfolioIntelligence();
  const [minLegs, maxLegs] = $("optimizer-legs").value.split("-").map(Number);
  const platform = $("optimizer-platform").value;
  const sport = $("optimizer-sport").value;
  const params = new URLSearchParams({
    platform,
    sport,
    min_legs: minLegs,
    max_legs: maxLegs,
    min_confidence: $("optimizer-min-confidence").value || "62",
    min_edge: $("optimizer-min-edge").value || "0",
    max_same_team: $("optimizer-max-same-team").value || "5",
    exclude_correlated: $("optimizer-exclude-correlated").checked ? "true" : "false",
    apply_feedback: $("optimizer-apply-feedback").checked ? "true" : "false",
    limit: portfolioBatch ? "5" : "5",
  });
  const data = await api(`/api/entries/optimizer?${params.toString()}`);
  const suggestionsHtml = data.suggestions.map((suggestion, index) => `
    <div class="suggestion ${gradeClass(suggestion.grade)}">
      <div class="suggestion-top">
        <span class="pill">#${suggestion.rank} · ${suggestion.leg_count} Legs</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
        <span class="subtle">Score ${suggestion.score} · Value ${Number(suggestion.value_adjusted_score || suggestion.score || 0).toFixed(1)}</span>
      </div>
      ${suggestionMetaRow(suggestion)}
      ${platformValueBlock(suggestion.platform_value)}
      ${portfolioSuggestionBlock(suggestion)}
      <p>${propPickList(suggestion.entry.props)}</p>
      ${confidenceMoveNotes(suggestion.entry.props)}
      ${releaseStatusBlock(suggestion.release_status)}
      ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
      <div class="button-row">
        <button class="secondary" data-load-optimized="${index}">Load Slip</button>
        ${(suggestion.portfolio?.replacements || []).length ? `<button class="secondary" data-load-portfolio-adjusted="${index}">Load Lower-Exposure Version</button>` : ""}
        <button class="secondary" data-explain-optimized="${index}">Why?</button>
      </div>
    </div>
  `).join("") || `<div class="suggestion">No optimized slips available.</div>`;
  $("optimizer-list").innerHTML = optimizerSummaryBlock(data) + suggestionsHtml;
  document.querySelectorAll("[data-load-optimized]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.loadOptimized)];
      renderEntryPropsFromAnalyzed(suggestion.entry.props);
      state.recommendationOrigin = true;
      $("entry-status").textContent = `Loaded optimized ${suggestion.leg_count}-leg slip #${suggestion.rank}.`;
    });
  });
  document.querySelectorAll("[data-explain-optimized]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.explainOptimized)];
      openExplanationDrawer(suggestionExplanation(suggestion, `Optimized Slip #${suggestion.rank}`));
    });
  });
  document.querySelectorAll("[data-load-portfolio-adjusted]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.loadPortfolioAdjusted)];
      const props = portfolioAdjustedProps(suggestion);
      renderEntryPropsFromAnalyzed(props);
      state.recommendationOrigin = true;
      $("entry-status").textContent = `Loaded a lower-exposure ${props.length}-leg version. Analyze it to confirm current value and release checks.`;
    });
  });
}

async function loadPending() {
  const data = await api("/api/entries/pending");
  $("pending-list").innerHTML = data.entries.map((entry) => {
    const maxDnp = Math.max(0, entry.props.length - 1);
    const isPaper = entry.entry_mode === "paper";
    return `
    <div class="suggestion">
      <div class="suggestion-top">
        <span class="pill">#${entry.id}</span>
        <strong>${entry.platform}</strong>
        ${isPaper ? `<span class="pill paper-pill">Paper</span>` : ""}
        <span class="subtle">${formatDateTime(entry.placed_at)}</span>
      </div>
      <p>${propPickList(entry.props)}</p>
      <p>${isPaper ? "Paper calibration entry · no bankroll impact" : `${money(entry.wager)} wagered · ${Number(entry.multiplier || 1).toFixed(1)}x · ${money(entry.potential_payout)} payout`}</p>
      <div class="form-grid compact-controls">
        <input id="dnp-legs-${entry.id}" type="number" min="0" max="${maxDnp}" step="1" value="0" placeholder="DNP legs" aria-label="DNP legs for entry ${entry.id}" />
      </div>
      <div class="button-row">
        <button data-settle="${entry.id}:Win">Win</button>
        <button class="danger" data-settle="${entry.id}:Loss">Loss</button>
        <button class="secondary" data-settle="${entry.id}:Push">Push</button>
        <button class="secondary" data-settle="${entry.id}:DNP">DNP Refund</button>
      </div>
    </div>
  `;
  }).join("") || `<div class="suggestion">No pending entries.</div>`;
  document.querySelectorAll("[data-settle]").forEach((button) => {
    button.addEventListener("click", async () => {
      const [id, result] = button.dataset.settle.split(":");
      await api(`/api/entries/${id}/settle`, {
        method: "POST",
        body: JSON.stringify({
          result,
          dnp_legs: Number($(`dnp-legs-${id}`)?.value || 0),
        }),
      });
      await loadPending();
      await loadDashboard();
      await loadPerformance();
    });
  });
}

async function loadDnpSetting() {
  const data = await api("/api/settings/dnp");
  $("dnp-handling").value = data.mode;
}

async function saveDnpSetting() {
  const data = await api("/api/settings/dnp", {
    method: "POST",
    body: JSON.stringify({ mode: $("dnp-handling").value }),
  });
  $("auto-check-status").textContent = `DNP handling saved: ${data.mode}.`;
}

async function autoCheckEntries() {
  $("auto-check-status").textContent = "Checking pending entries...";
  const data = await api("/api/entries/auto-check", { method: "POST" });
  const estimateNote = data.estimated ? " Some entries used projection estimates." : "";
  const refresh = data.final_stats_refresh || {};
  const refreshNote = refresh.provider
    ? ` ESPN refreshed ${refresh.imported || 0} final stat rows.`
    : "";
  const errorNote = refresh.errors && refresh.errors.length
    ? ` ${refresh.errors.length} ESPN refresh issue${refresh.errors.length === 1 ? "" : "s"}.`
    : "";
  const pendingNote = data.settled === 0 ? " Waiting on matching final stats for any unsettled legs." : "";
  $("auto-check-status").textContent = `Checked ${data.checked}, settled ${data.settled}.${refreshNote}${estimateNote}${errorNote}${pendingNote}`;
  await loadPending();
  await loadDashboard();
  await loadEntryProgress({ autoCheck: false });
}

async function expediteEntries() {
  const confirmed = window.confirm("Expedite stale entries using projection estimates where final stat data is unavailable?");
  if (!confirmed) return;
  $("auto-check-status").textContent = "Expediting stale entries with estimate fallback...";
  const data = await api("/api/entries/auto-check?allow_estimates=true", { method: "POST" });
  const refresh = data.final_stats_refresh || {};
  const refreshNote = refresh.provider
    ? ` Provider refresh imported ${refresh.imported || 0} final stat rows.`
    : "";
  $("auto-check-status").textContent = `Expedited ${data.settled} of ${data.checked} entries.${refreshNote} Estimated settlements are marked as projection-based.`;
  await loadPending();
  await loadDashboard();
  await loadEntryProgress({ autoCheck: false });
  await loadBets();
  await loadPerformance();
}

async function runSync() {
  $("sync-status").textContent = "Syncing provider stats, imports, and pending entries...";
  const data = await api("/api/sync/run", { method: "POST" });
  const auto = data.auto_check || {};
  const finalFile = data.final_stats_file || {};
  const betFile = data.bet_history_file || {};
  const liveStats = data.live_stats || {};
  $("sync-status").textContent = `Sync complete: checked ${auto.checked || 0}, settled ${auto.settled || 0}, live rows ${liveStats.imported || 0}, final rows ${finalFile.imported || 0}, bet rows ${betFile.imported || 0}.`;
  await loadPending();
  await loadDashboard();
  await loadEntryProgress();
  await loadPerformance();
}

async function classifyDefaultWagers() {
  $("auto-check-status").textContent = "Classifying missing entry wagers...";
  const data = await api("/api/entries/classify-default-wagers", { method: "POST" });
  $("auto-check-status").textContent = data.updated
    ? `Classified ${data.updated} entries as ${money(data.default_wager)} default wagers.`
    : "No placed entries needed default wager classification.";
  await loadPending();
  await loadDashboard();
  await loadPerformance();
}

async function shopLines(event) {
  event.preventDefault();
  const player = $("shop-player").value.trim();
  const stat = $("shop-stat").value.trim();
  if (!player || !stat) return;
  const params = new URLSearchParams({
    player,
    stat,
    sport: $("shop-sport").value,
    platform: $("shop-platform").value,
  });
  if ($("shop-over-odds").value) params.set("over_odds", $("shop-over-odds").value);
  if ($("shop-under-odds").value) params.set("under_odds", $("shop-under-odds").value);
  const data = await api(`/api/market/line-shop?${params.toString()}`);
  $("line-shop-result").classList.remove("muted-card");
  if (!data.available) {
    $("line-shop-result").innerHTML = `<h2>No Match</h2><p>${data.message}</p>`;
    return;
  }
  $("line-shop-result").innerHTML = `
    <div class="suggestion-top">
      <div>
        <span class="pill">${data.sport}</span>
        <strong>${data.player} · ${data.stat}</strong>
      </div>
      <span class="subtle">${data.provider_count || 0} provider${Number(data.provider_count || 0) === 1 ? "" : "s"} · ${data.market_count || data.lines.length} active lines</span>
    </div>
    <div class="stats-grid line-shop-metrics" style="margin-top:14px">
      <div class="line-shop-metric"><strong>${data.best_over.platform}</strong><span>Best Over ${data.best_over.line}</span></div>
      <div class="line-shop-metric"><strong>${data.best_under.platform}</strong><span>Best Under ${data.best_under.line}</span></div>
      <div class="line-shop-metric"><strong>${data.consensus_line}</strong><span>Consensus Line</span></div>
      <div class="line-shop-metric"><strong>${data.line_spread}</strong><span>Line Spread</span></div>
    </div>
    <p>${data.value_note}</p>
    ${data.adjusted_market_count ? `<p class="subtle">${data.adjusted_market_count} payout-adjusted line${data.adjusted_market_count === 1 ? " was" : "s were"} excluded from the standard-line comparison.</p>` : ""}
    ${data.no_vig ? `<p>No-vig fair price: Over ${pct(data.no_vig.over_probability)} (${data.no_vig.over_fair_odds}) · Under ${pct(data.no_vig.under_probability)} (${data.no_vig.under_fair_odds}) · Hold ${data.no_vig.hold == null ? "unavailable" : pct(data.no_vig.hold)}</p><p class="subtle">${escapeHtml(data.no_vig_source || "Supplied odds")}${data.no_vig.book_count ? ` · ${Number(data.no_vig.book_count)} exact-line books` : ""}</p>` : `<p class="subtle">No paired exact-line sportsbook price is available. You can enter over and under odds manually.</p>`}
  `;
}

async function loadPlayerResearch(event) {
  event.preventDefault();
  const player = $("research-player").value.trim();
  const stat = $("research-stat").value.trim();
  if (!player || !stat) return;
  $("player-research-result").classList.add("muted-card");
  $("player-research-result").textContent = "Loading player research...";
  const params = new URLSearchParams({
    stat,
    sport: $("research-sport").value,
    platform: $("research-platform").value,
  });
  if ($("research-line").value) params.set("line", $("research-line").value);
  const data = await api(`/api/players/${encodeURIComponent(player)}/research?${params.toString()}`);
  const split = data.splits || {};
  const trend = data.trend || {};
  const distribution = data.forecast?.distribution || {};
  const sensitivity = data.projection_sensitivity || {};
  const maxActual = Math.max(1, ...((data.chart || []).map((row) => Number(row.actual) || 0)), Number(data.line) || 0);
  $("player-research-result").classList.remove("muted-card");
  $("player-research-result").innerHTML = `
    <div class="suggestion-top">
      <div>
        <span class="pill">${data.sport}</span>
        <strong>${data.player} · ${data.stat}</strong>
      </div>
      <span class="subtle">${data.history_count} finals · ${data.active_props.length} active</span>
    </div>
    <div class="stats-grid" style="margin-top:14px">
      ${researchSplitCard("Last 5", split.last_5)}
      ${researchSplitCard("Last 10", split.last_10)}
      ${researchSplitCard("Last 20", split.last_20)}
      ${researchSplitCard("Season", split.season)}
      ${researchSplitCard("Home", split.home)}
      ${researchSplitCard("Away", split.away)}
      ${researchSplitCard("Starter", split.starter)}
      ${researchSplitCard("Bench", split.bench)}
      ${researchSplitCard(data.opponent ? `vs ${data.opponent}` : "Opponent", split.opponent)}
      <div class="stat-card"><div class="stat-value">${data.line ?? "-"}</div><div class="stat-label">Research Line</div></div>
      <div class="stat-card"><div class="stat-value">${trend.delta > 0 ? "+" : ""}${Number(trend.delta || 0).toFixed(1)}</div><div class="stat-label">Recent Trend</div></div>
      <div class="stat-card"><div class="stat-value">${pct(trend.consistency_score || 0)}</div><div class="stat-label">Consistency</div></div>
    </div>
    <section class="research-distribution">
      <div class="section-heading compact-heading">
        <div><p class="eyebrow">Projection Distribution</p><h3>Range, not just one number</h3></div>
        <span class="status-pill ${distribution.uncertainty_level === "High" ? "status-warning" : "status-positive"}">${escapeHtml(distribution.uncertainty_level || "Unknown")} uncertainty</span>
      </div>
      <div class="metric-strip research-distribution-metrics">
        <span><strong>${distribution.expected_result ?? "-"}</strong><small>Expected</small></span>
        <span><strong>${distribution.median ?? "-"}</strong><small>Median</small></span>
        <span><strong>${distribution.percentile_25 ?? "-"}–${distribution.percentile_75 ?? "-"}</strong><small>Middle 50%</small></span>
        <span><strong>${distribution.floor ?? "-"}–${distribution.ceiling ?? "-"}</strong><small>Floor–Ceiling</small></span>
        <span><strong>${pct(distribution.probability_over_exact_line ?? 50)}</strong><small>Exact-line Over</small></span>
        <span><strong>${distribution.expected_minutes ?? distribution.expected_opportunities ?? "-"}</strong><small>Minutes / Chances</small></span>
      </div>
      <div class="sensitivity-grid">
        ${(sensitivity.scenarios || []).map((scenario) => `<span><strong>${scenario.line}</strong><small>${pct(scenario.probability)} ${escapeHtml(data.recommendation?.direction || "Over")}</small></span>`).join("")}
      </div>
      ${(sensitivity.drivers || []).map((driver) => `<p class="subtle">What changes this: ${escapeHtml(driver)}</p>`).join("")}
    </section>
    <div class="player-research-bars">
      ${(data.chart || []).map((row) => `
        <div class="research-bar-row">
          <span>${escapeHtml(row.game || row.game_date || "Tracked game")}</span>
          <div class="research-bar"><i style="width:${Math.min(100, ((Number(row.actual) || 0) / maxActual) * 100)}%"></i></div>
          <strong>${Number(row.actual).toFixed(1)}</strong>
          <span class="${row.hit ? "positive" : "negative"}">${row.hit === null ? "Line needed" : row.hit ? "Over hit" : "Miss"}</span>
        </div>
      `).join("") || `<p class="subtle">No final-stat chart data yet.</p>`}
    </div>
    <div class="research-market-lines">
      ${(data.market_lines || []).map((row) => `
        <span>
          <strong>${escapeHtml(row.platform)}</strong>
          ${escapeHtml(row.direction || "Over")} ${row.line}
          <small>${escapeHtml(row.offer_type || "standard")} · ${pct(row.confidence || 0)}</small>
        </span>
      `).join("") || `<p class="subtle">No active market lines found.</p>`}
    </div>
    ${(data.closing_lines || []).length ? `<p class="subtle">Recent recorded lines: ${(data.closing_lines || []).slice(0, 6).map((row) => Number(row.line).toFixed(1)).join(" → ")}</p>` : `<p class="subtle">Historical closing lines are not available for this exact market yet.</p>`}
    ${(data.teammate_splits || []).map((row) => `<p class="subtle">With ${escapeHtml(row.teammate)}: ${pct(row.with.hit_rate || 0)} · Without: ${pct(row.without.hit_rate || 0)}</p>`).join("") || `<p class="subtle">With/without teammate splits will appear when lineup participation history is available.</p>`}
    ${data.recommendation ? `<p>Best active look: ${data.recommendation.platform} ${directionBadge(data.recommendation.direction || "Over")} ${data.recommendation.line} · confidence ${pct(data.recommendation.confidence)}</p>` : ""}
    ${(data.notes || []).map((note) => `<p class="subtle">${escapeHtml(note)}</p>`).join("")}
  `;
}

function researchSplitCard(label, split = {}) {
  return `
    <div class="stat-card">
      <div class="stat-value">${split.hit_rate === null || split.hit_rate === undefined ? "-" : pct(split.hit_rate)}</div>
      <div class="stat-label">${label} · ${split.sample || 0} games · avg ${split.average ?? "-"}</div>
    </div>
  `;
}

async function loadSharpConsensus(event) {
  event.preventDefault();
  const player = $("consensus-player").value.trim();
  const stat = $("consensus-stat").value.trim();
  if (!player || !stat) return;
  $("sharp-consensus-result").classList.add("muted-card");
  $("sharp-consensus-result").textContent = "Checking consensus...";
  const params = new URLSearchParams({
    player,
    stat,
    sport: $("consensus-sport").value,
    platform: $("consensus-platform").value,
  });
  if ($("consensus-over-odds").value) params.set("over_odds", $("consensus-over-odds").value);
  if ($("consensus-under-odds").value) params.set("under_odds", $("consensus-under-odds").value);
  const data = await api(`/api/market/sharp-consensus?${params.toString()}`);
  $("sharp-consensus-result").classList.remove("muted-card");
  if (!data.available) {
    $("sharp-consensus-result").innerHTML = `<h2>No active market</h2><p>${data.message || "No matching provider lines found."}</p>`;
    return;
  }
  $("sharp-consensus-result").innerHTML = `
    <div class="suggestion-top">
      <div>
        <span class="pill">${data.confidence} consensus</span>
        <strong>${data.player} · ${data.stat}</strong>
      </div>
      <span class="subtle">${data.platform_count} platforms</span>
    </div>
    <div class="stats-grid" style="margin-top:14px">
      <div class="stat-card"><div class="stat-value">${data.fair_line}</div><div class="stat-label">Fair Line</div></div>
      <div class="stat-card"><div class="stat-value">${data.market_width}</div><div class="stat-label">Market Width</div></div>
      <div class="stat-card"><div class="stat-value">${data.best_over.platform}</div><div class="stat-label">Best Over ${data.best_over.line}</div></div>
      <div class="stat-card"><div class="stat-value">${data.best_under.platform}</div><div class="stat-label">Best Under ${data.best_under.line}</div></div>
    </div>
    ${data.no_vig ? `<p>No-vig: Over ${pct(data.no_vig.over_probability)} (${data.no_vig.over_fair_odds}) · Under ${pct(data.no_vig.under_probability)} (${data.no_vig.under_fair_odds}) · ${escapeHtml(data.no_vig_source || "Supplied odds")}</p>` : ""}
    ${(data.notes || []).map((note) => `<p class="subtle">${escapeHtml(note)}</p>`).join("")}
  `;
}

async function calculateHedge(event) {
  event.preventDefault();
  const payload = {
    original_odds: Number($("hedge-original-odds").value),
    hedge_odds: Number($("hedge-odds").value),
    original_stake: Number($("hedge-stake").value),
    target: $("hedge-target").value,
  };
  const data = await api("/api/market/hedge-calculator", { method: "POST", body: JSON.stringify(payload) });
  $("hedge-result").classList.remove("muted-card");
  $("hedge-result").innerHTML = calculatorResultHtml(`Hedge ${money(data.hedge_stake)}`, data);
}

async function calculateMiddle(event) {
  event.preventDefault();
  const payload = {
    over_line: Number($("middle-over-line").value),
    under_line: Number($("middle-under-line").value),
    over_odds: Number($("middle-over-odds").value || -110),
    under_odds: Number($("middle-under-odds").value || -110),
    over_stake: Number($("middle-over-stake").value || 0),
    under_stake: Number($("middle-under-stake").value || 0),
  };
  const data = await api("/api/market/middle-calculator", { method: "POST", body: JSON.stringify(payload) });
  $("middle-result").classList.remove("muted-card");
  const zone = data.middle_available ? `${data.middle_zone.from} to ${data.middle_zone.to}` : "No middle";
  $("middle-result").innerHTML = calculatorResultHtml(zone, data);
}

function calculatorResultHtml(title, data) {
  return `
    <h2>${title}</h2>
    <div class="stats-grid" style="margin-top:14px">
      ${(data.outcomes || []).map((outcome) => `
        <div class="stat-card">
          <div class="stat-value">${outcome.profit === null ? "-" : money(outcome.profit)}</div>
          <div class="stat-label">${escapeHtml(outcome.label)}</div>
        </div>
      `).join("")}
    </div>
    <p class="subtle">${escapeHtml(data.note || "")}</p>
  `;
}

async function runEvScanner(event) {
  event.preventDefault();
  $("ev-scanner-result").classList.add("muted-card");
  $("ev-scanner-result").textContent = "Scanning the board...";
  const params = new URLSearchParams({
    platform: $("scan-platform").value,
    sport: $("scan-sport").value,
    min_ev: $("scan-min-ev").value || "0",
    odds: $("scan-odds").value || "-110",
    limit: "25",
  });
  const data = await api(`/api/market/ev-scanner?${params.toString()}`);
  $("ev-scanner-result").classList.remove("muted-card");
  $("ev-scanner-result").innerHTML = data.props.map((prop, index) => `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <span class="pill">#${index + 1} · ${prop.expected_value > 0 ? "+" : ""}${pct(prop.expected_value)} EV</span>
        <strong>${prop.player}</strong>
        <span class="subtle">${prop.platform}</span>
      </div>
      <p>${prop.sport} · ${directionBadge(prop.direction || "Over")} ${prop.stat} ${prop.line} · Projection ${prop.projection} · Adjusted hit ${pct(prop.estimated_probability)}</p>
      ${prop.probability_adjustment ? `<p class="subtle">${escapeHtml(prop.probability_adjustment)}</p>` : ""}
      ${dataStrengthBadges([prop])}
      <p class="subtle">Best over ${prop.best_over?.platform || "-"} ${prop.best_over?.line ?? "-"} · Consensus ${prop.consensus_line ?? "-"}</p>
      <button class="secondary" data-load-scan-prop="${index}">Add Prop</button>
    </div>
  `).join("") || `<div class="suggestion">No props met the EV filter.</div>`;
  document.querySelectorAll("[data-load-scan-prop]").forEach((button) => {
    button.addEventListener("click", () => addFeedProp({
      ...data.props[Number(button.dataset.loadScanProp)],
      league: data.props[Number(button.dataset.loadScanProp)].sport,
    }));
  });
}

async function loadClvReport() {
  const data = await api("/api/market/clv");
  $("clv-result").classList.remove("muted-card");
  $("clv-result").innerHTML = `
    <div class="stats-grid" style="margin-top:0">
      <div class="stat-card"><div class="stat-value">${Number(data.average_clv).toFixed(2)}</div><div class="stat-label">Avg CLV</div></div>
      <div class="stat-card"><div class="stat-value">${pct(data.positive_clv_rate)}</div><div class="stat-label">Positive CLV</div></div>
      <div class="stat-card"><div class="stat-value">${data.tracked_legs}</div><div class="stat-label">Tracked Legs</div></div>
      <div class="stat-card"><div class="stat-value">${data.quarantined_legs || 0}</div><div class="stat-label">Legacy Excluded</div></div>
    </div>
    ${data.entries.slice(0, 8).map((entry) => `
      <div class="suggestion compact-suggestion">
        <div class="suggestion-top">
          <strong>Entry #${entry.id}</strong>
          <span class="subtle">${entry.status} ${entry.result || ""}</span>
        </div>
        <p>${entry.legs.some((leg) => leg.clv != null)
          ? `Avg CLV ${Number(entry.average_clv).toFixed(2)} · ${entry.positive_legs}/${entry.legs.filter((leg) => leg.clv != null).length} positive verified legs`
          : "CLV unavailable: this legacy entry lacks exact market provenance."}</p>
      </div>
    `).join("") || `<div class="suggestion">No CLV data yet.</div>`}
  `;
}

async function loadGradingReport() {
  if (!$("grading-report-list")) return;
  const data = await api("/api/entries/grading-report?compact=true");
  const summary = data.summary || {};
  $("grading-report-status").textContent = `${summary.pending_entries || 0} pending · ${summary.unknown_legs || 0} unknown legs · ${pct(summary.verification_rate || 0)} verified`;
  $("grading-report-list").innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${summary.pending_entries || 0}</div><div class="stat-label">Pending</div></div>
      <div class="stat-card"><div class="stat-value">${summary.unknown_legs || 0}</div><div class="stat-label">Unknown Legs</div></div>
      <div class="stat-card"><div class="stat-value">${pct(summary.positive_clv_rate || 0)}</div><div class="stat-label">Positive CLV</div></div>
      <div class="stat-card"><div class="stat-value">${Number(summary.average_clv || 0).toFixed(2)}</div><div class="stat-label">Avg CLV</div></div>
      <div class="stat-card"><div class="stat-value">${summary.quarantined_clv_legs || 0}</div><div class="stat-label">Legacy CLV Excluded</div></div>
    </div>
    ${(data.next_actions || []).map((action) => `<p class="subtle">${escapeHtml(action)}</p>`).join("")}
    ${(data.pending || []).slice(0, 4).map((entry) => `
      <div class="suggestion compact-suggestion">
        <div class="suggestion-top">
          <strong>Pending #${entry.id}</strong>
          <span class="subtle">${escapeHtml(entry.timeline_label || entry.status || "")}</span>
        </div>
        <p>${(entry.legs || []).map((leg) => `${leg.player}: ${leg.timeline_label || leg.status}`).join(" · ")}</p>
      </div>
    `).join("")}
  `;
}

async function loadSettlementAudit() {
  if (!$("settlement-audit-list")) return;
  const data = await api("/api/entries/settlement-audit?limit=150");
  $("settlement-audit-status").textContent = `${data.verified || 0} verified · ${data.scheduled || 0} scheduled · ${data.waiting || 0} waiting · ${data.blocked || 0} currently blocked · ${data.historical_review || 0} historical review`;
  $("settlement-audit-list").innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="stat-value">${data.verified || 0}</div><div class="stat-label">Verified</div></div>
      <div class="stat-card"><div class="stat-value">${data.scheduled || 0}</div><div class="stat-label">Scheduled</div></div>
      <div class="stat-card"><div class="stat-value">${data.waiting || 0}</div><div class="stat-label">Automatic Retry</div></div>
      <div class="stat-card"><div class="stat-value">${data.blocked || 0}</div><div class="stat-label">Currently Blocked</div></div>
      <div class="stat-card"><div class="stat-value">${data.historical_review || 0}</div><div class="stat-label">Historical Review</div></div>
    </div>
    ${(data.items || []).slice(0, 30).map((item) => `
      <div class="suggestion compact-suggestion insight-${item.status === "verified" ? "positive" : item.status === "scheduled" ? "neutral" : "warning"}">
        <div class="suggestion-top">
          <strong>Entry #${item.entry_id} · ${escapeHtml(item.requested_player || "Unknown player")}</strong>
          <span class="pill">${escapeHtml(item.status || "waiting")}</span>
        </div>
        ${item.scope === "historical" ? `<p class="subtle">Historical record · entry ${escapeHtml(item.entry_status || "archived")}</p>` : ""}
        <p>${escapeHtml(item.details?.stat || "Stat")} ${item.details?.line ?? ""} · ${escapeHtml(item.result || "Pending")} ${item.actual == null ? "" : `· Final ${item.actual}`}</p>
        <p class="subtle">${escapeHtml(item.message || "Waiting for provider result.")} · ${escapeHtml(item.provider || "Provider pending")} · ${item.attempt_count || 1} attempt${Number(item.attempt_count || 1) === 1 ? "" : "s"}</p>
        <p class="subtle">Match confidence ${Number(item.match_confidence || 0)}% · ${item.next_retry_at ? `Next retry ${formatDateTime(item.next_retry_at)}` : "No retry scheduled"}</p>
        ${item.status !== "verified" ? `<p class="human-error">${escapeHtml(item.blocking_reason || "Waiting for verified final data.")}</p>` : ""}
        ${item.matched_player ? `<p class="subtle">Matched ${escapeHtml(item.matched_player)} · ${escapeHtml(item.matched_game || "game unavailable")}</p>` : ""}
      </div>
    `).join("") || `<div class="suggestion">No settlement attempts have been recorded yet. Recheck final stats to populate the audit.</div>`}
  `;
}

async function loadLossProtection() {
  if (!$("entry-loss-protection")) return;
  const data = await api("/api/loss-protection");
  const metrics = data.metrics || {};
  const active = Boolean(data.active);
  const enabled = data.enabled !== false;
  const toggleLabel = data.forced && active && !enabled ? "Auto warning" : enabled ? "On" : "Off";
  $("entry-loss-protection").classList.remove("muted-card");
  $("entry-loss-protection").classList.toggle("protection-active", active);
  $("entry-loss-protection").classList.toggle("protection-clear", !active);
  $("entry-loss-protection").innerHTML = `
    <div class="suggestion-top">
      <div>
        <span class="pill">${escapeHtml(data.mode || "normal")}</span>
        <strong>${escapeHtml(data.label || "Paid Entries Enabled")}</strong>
      </div>
      <label class="toggle-control" title="Turn Loss Protection enforcement on or off">
        <input id="loss-protection-toggle" type="checkbox" ${enabled ? "checked" : ""} />
        <span class="toggle-track" aria-hidden="true"></span>
        <span>${toggleLabel}</span>
      </label>
    </div>
    <p>${escapeHtml((data.reasons || [])[0] || "Recovery checks are clear.")}</p>
    ${!enabled && data.triggered ? `<p class="warning">Current performance would activate protection if you turn it back on.</p>` : ""}
    <div class="briefing-metric-row compact-metrics">
      <span>Month ${money(metrics.monthly_profit || 0)}</span>
      <span>ROI ${pct(metrics.roi || 0)}</span>
      <span>CLV ${Number(metrics.average_clv || 0).toFixed(2)}</span>
      <span>${Number(metrics.positive_clv_rate || 0).toFixed(0)}% +CLV</span>
    </div>
    ${(data.paid_rules || []).slice(0, active ? 3 : 1).map((rule) => `<p class="subtle">${escapeHtml(rule)}</p>`).join("")}
  `;
  $("loss-protection-toggle").addEventListener("change", async (event) => {
    const nextEnabled = Boolean(event.target.checked);
    event.target.disabled = true;
    $("entry-status").textContent = `${nextEnabled ? "Turning on" : "Turning off"} Loss Protection...`;
    try {
      const updated = await api("/api/loss-protection", {
        method: "POST",
        body: JSON.stringify({ enabled: nextEnabled }),
      });
      $("entry-status").textContent = updated.active
        ? "Loss Protection is active. EdgeIQ will warn against paid entries, but user-selected paid entries can still be tracked after confirmation."
        : updated.enabled
          ? "Loss Protection is on and monitoring performance."
          : "Loss Protection is off. Standard bankroll and provider checks still apply.";
      await Promise.allSettled([loadLossProtection(), loadCommandCenter()]);
    } catch (error) {
      event.target.checked = !nextEnabled;
      event.target.disabled = false;
      $("entry-status").textContent = humanizeErrorText(error.message);
    }
  });
}

async function loadLossReview() {
  if (!$("loss-review-list")) return;
  const data = await api("/api/analytics/loss-review");
  const summary = data.summary || {};
  const profiles = data.profiles || {};
  const wins = profiles.wins || {};
  const losses = profiles.losses || {};
  $("loss-review-status").textContent = `${summary.wins_reviewed || 0} wins vs ${summary.losses_reviewed || 0} losses · verified finals only`;
  $("loss-review-list").innerHTML = `
    <div class="coaching-card">
      <div>
        <span class="pill">Outcome Learning</span>
        <strong>${data.model_feedback?.active ? "Verified segments are informing confidence" : "Building a trustworthy learning sample"}</strong>
        <p>${escapeHtml(data.model_feedback?.message || "Only verified final stats influence recommendation confidence.")}</p>
      </div>
      <button class="secondary" type="button" data-view-shortcut="entries">Build Safer Entry</button>
    </div>
    <div class="comparison-grid">
      ${outcomeProfileCard("Winning Entries", wins, "positive")}
      ${outcomeProfileCard("Losing Entries", losses, "danger")}
    </div>
    <div class="analysis-card">
      <strong>What separates them</strong>
      ${(data.insights || []).map((insight) => `<p>${escapeHtml(insight)}</p>`).join("")}
      ${summary.excluded_unverified ? `<p class="subtle">${summary.excluded_unverified} unverified settled entries were excluded from learning.</p>` : ""}
    </div>
    <div class="suggestion-list">
      ${(data.learning_segments || []).slice(0, 8).map((segment) => `
        <div class="suggestion compact-suggestion">
          <div class="suggestion-top">
            <strong>${escapeHtml(segment.dimension)} · ${escapeHtml(segment.name)}</strong>
            <span class="pill ${segment.model_eligible ? "status-verified" : ""}">${segment.model_eligible ? "Learning active" : "Tracking"}</span>
          </div>
          <p>${segment.wins}-${segment.losses} verified legs · ${pct(segment.hit_rate)} hit rate · ${pct(segment.avg_confidence)} expected · ${Number(segment.calibration_gap || 0).toFixed(1)} pt gap</p>
        </div>
      `).join("") || `<div class="suggestion">No segment has five verified decisions yet.</div>`}
    </div>
    ${(data.entries || []).map((entry) => `
      <div class="suggestion compact-suggestion ${entry.result === "Win" ? "positive" : "danger"}">
        <div class="suggestion-top">
          <strong>${escapeHtml(entry.result)} #${entry.id} · ${entry.leg_count} legs</strong>
          <span class="subtle">${escapeHtml(entry.platform || "")} · ${formatDateTime(entry.placed_at)}</span>
        </div>
        <div class="pill-row">${(entry.reasons || []).map((reason) => `<span class="pill">${escapeHtml(reason)}</span>`).join("")}</div>
        <div class="mini-leg-list">
          ${(entry.legs || []).map((leg) => `
            <span>${escapeHtml(leg.player)} ${escapeHtml(leg.direction || "Over")} ${escapeHtml(leg.stat || "")} ${escapeHtml(leg.line ?? "")} · ${escapeHtml(leg.result || "Unknown")} · ${escapeHtml(leg.source || "")}</span>
          `).join("")}
        </div>
      </div>
    `).join("") || `<div class="suggestion">No fully verified winning or losing entries to compare yet.</div>`}
  `;
  document.querySelectorAll("#loss-review-list [data-view-shortcut]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.viewShortcut));
  });
}

function outcomeProfileCard(title, profile, tone) {
  return `
    <div class="suggestion ${tone}">
      <div class="suggestion-top"><strong>${escapeHtml(title)}</strong><span class="subtle">${profile.entries || 0} entries</span></div>
      <div class="metric-strip">
        <span><strong>${Number(profile.avg_legs || 0).toFixed(1)}</strong><small>Avg Legs</small></span>
        <span><strong>${pct(profile.avg_confidence || 0)}</strong><small>Confidence</small></span>
        <span><strong>${pct(profile.provider_backed_pct || 0)}</strong><small>Provider Backed</small></span>
        <span><strong>${pct(profile.positive_clv_pct || 0)}</strong><small>Positive CLV</small></span>
      </div>
    </div>
  `;
}

function lossCoachHeadline(summary, buckets) {
  if (!Number(summary.losses_reviewed || 0)) return "No loss pattern yet";
  const top = buckets[0]?.reason || "Result variance";
  return `Biggest leak: ${top}`;
}

function lossCoachBody(buckets) {
  const reasons = buckets.slice(0, 3).map((bucket) => bucket.reason);
  if (reasons.includes("Negative CLV")) return "EdgeIQ should line-shop harder and avoid paying worse numbers than the market.";
  if (reasons.includes("Too many legs")) return "EdgeIQ should stay in singles or 2-leg mode until the recovery score improves.";
  if (reasons.includes("Auto-projected leg")) return "Auto-projected props should stay in paper mode until they prove themselves by segment.";
  if (reasons.includes("Unknown final stats")) return "The next best move is rechecking finals before trusting the calibration report.";
  return "Keep tracking verified results. EdgeIQ will turn repeated loss causes into stricter rules.";
}

async function loadAlertDeliverySettings() {
  const data = await api("/api/settings/alert-delivery");
  const settings = data.settings || {};
  $("alert-browser-enabled").checked = Boolean(settings.browser_enabled);
  $("alert-email-enabled").checked = Boolean(settings.email_enabled);
  $("alert-email-address").value = settings.email_address || "";
  $("alert-sms-enabled").checked = Boolean(settings.sms_enabled);
  $("alert-sms-number").value = settings.sms_number || "";
  $("alert-webhook-enabled").checked = Boolean(settings.webhook_enabled);
  $("alert-webhook-url").value = settings.webhook_url || "";
  $("alert-min-priority").value = settings.min_priority ?? 65;
  renderAlertDeliveryStatus(data);
}

async function saveAlertDeliverySettings(event) {
  event.preventDefault();
  const payload = {
    browser_enabled: $("alert-browser-enabled").checked,
    email_enabled: $("alert-email-enabled").checked,
    email_address: $("alert-email-address").value.trim(),
    sms_enabled: $("alert-sms-enabled").checked,
    sms_number: $("alert-sms-number").value.trim(),
    webhook_enabled: $("alert-webhook-enabled").checked,
    webhook_url: $("alert-webhook-url").value.trim(),
    min_priority: Number($("alert-min-priority").value || 65),
  };
  const data = await api("/api/settings/alert-delivery", { method: "POST", body: JSON.stringify(payload) });
  renderAlertDeliveryStatus(data);
}

function renderAlertDeliveryStatus(data) {
  const settings = data.settings || {};
  const hooks = data.delivery_hooks || {};
  $("alert-delivery-status").classList.remove("muted-card");
  $("alert-delivery-status").innerHTML = `
    <div class="suggestion-top">
      <strong>${(settings.channels || []).join(", ") || "No channels"}</strong>
      <span class="subtle">Min ${pct(settings.min_priority || 0)}</span>
    </div>
    <p>Browser ${hooks.browser || "-"} · Email ${hooks.email || "-"} · SMS ${hooks.sms || "-"} · Webhook ${hooks.webhook || "-"}</p>
    <p class="subtle">Browser alerts can run immediately. Webhook delivery can bridge push, email, SMS, or automation tools.</p>
  `;
}

async function testAlertDelivery() {
  $("alert-delivery-status").classList.remove("muted-card");
  $("alert-delivery-status").textContent = "Sending test alert...";
  const data = await api("/api/alerts/test-delivery", {
    method: "POST",
    body: JSON.stringify({
      title: "EdgeIQ alert test",
      message: "Alert delivery is connected.",
      priority: Number($("alert-min-priority").value || 65),
      severity: "positive",
    }),
  });
  $("alert-delivery-status").innerHTML = `
    <h2>${data.delivered ? "Delivery Ready" : "Skipped"}</h2>
    ${(data.channels || []).map((row) => `<p>${escapeHtml(row.channel)} · ${escapeHtml(row.status)} · ${escapeHtml(row.detail)}</p>`).join("") || `<p>${escapeHtml(data.reason || "No channels configured.")}</p>`}
  `;
}

async function loadImportWizard() {
  const data = await api("/api/import-wizard");
  $("import-wizard-result").classList.remove("muted-card");
  $("import-wizard-result").innerHTML = `
    <h2>${escapeHtml(data.title)}</h2>
    <p>${escapeHtml(data.summary)}</p>
    <div class="wizard-step-list">
      ${(data.steps || []).map((step, index) => `
        <div class="wizard-step">
          <span class="pill">Step ${index + 1}</span>
          <strong>${escapeHtml(step.label)}</strong>
          <p class="subtle">${escapeHtml(step.detail)}</p>
        </div>
      `).join("")}
    </div>
    ${(data.templates || []).map((template) => `
      <div class="import-template">
        <strong>${escapeHtml(template.platform)} template</strong>
        <code>${escapeHtml(template.sample)}</code>
      </div>
    `).join("")}
  `;
}

async function calculateEv(event) {
  event.preventDefault();
  const payload = { odds: Number($("ev-odds").value), probability: Number($("ev-prob").value) };
  const data = await api("/api/analysis/ev", { method: "POST", body: JSON.stringify(payload) });
  $("ev-result").classList.remove("muted-card");
  $("ev-result").innerHTML = `
    <div class="grade">${data.recommendation.grade}</div>
    <h2>${data.recommendation.action}</h2>
    <p>${data.recommendation.summary}</p>
    <p>Sportsbook: ${pct(data.sportsbook_probability)} · Edge: ${pct(data.edge)} · EV: ${pct(data.expected_value)}</p>
    <p>Break-even: ${pct(data.break_even)} · Half Kelly: ${pct(data.half_kelly)} · Wager: ${money(data.suggested_wager)}</p>
  `;
}

async function loadLineMovement(event) {
  event.preventDefault();
  const player = $("movement-player").value.trim();
  const stat = $("movement-stat").value.trim();
  const platform = $("movement-platform").value;
  if (!player || !stat) return;
  const data = await api(`/api/players/${encodeURIComponent(player)}/line-movement?stat=${encodeURIComponent(stat)}&platform=${encodeURIComponent(platform)}`);
  $("movement-result").classList.remove("muted-card");
  $("movement-result").innerHTML = `
    <h2>${data.player} · ${data.stat}</h2>
    <p>${data.platform} · ${formatMovement(data)} · Current ${data.current ?? "-"} · Previous ${data.previous ?? "-"}</p>
    <p>${data.snapshots.length} line snapshots recorded.</p>
  `;
}

async function estimateHitRate(event) {
  event.preventDefault();
  const player = $("hit-player").value.trim();
  const stat = $("hit-stat").value.trim();
  const line = Number($("hit-line").value);
  const projection = $("hit-projection").value;
  if (!player || !stat || Number.isNaN(line)) return;
  const projectionParam = projection === "" ? "" : `&projection=${encodeURIComponent(projection)}`;
  const data = await api(`/api/players/${encodeURIComponent(player)}/hit-rate?stat=${encodeURIComponent(stat)}&line=${encodeURIComponent(line)}${projectionParam}`);
  $("hit-rate-result").classList.remove("muted-card");
  $("hit-rate-result").innerHTML = `
    <h2>${pct(data.estimated_hit_rate)}</h2>
    <p>${data.player} ${data.stat} ${data.line} · Projection ${data.projection} · Edge ${Number(data.edge).toFixed(2)}</p>
    <div class="stats-grid" style="margin-top:14px">
      <div class="stat-card"><div class="stat-value">${pct(data.last_5)}</div><div class="stat-label">Last 5</div></div>
      <div class="stat-card"><div class="stat-value">${pct(data.last_10)}</div><div class="stat-label">Last 10</div></div>
      <div class="stat-card"><div class="stat-value">${pct(data.season)}</div><div class="stat-label">Season</div></div>
      <div class="stat-card"><div class="stat-value">${data.source}</div><div class="stat-label">Source</div></div>
    </div>
    <p class="subtle">${data.note}</p>
  `;
}

async function assistProjection(event) {
  event.preventDefault();
  const payload = {
    player: $("assist-player").value.trim(),
    sport: $("assist-sport").value,
    stat: $("assist-stat").value.trim(),
    line: Number($("assist-line").value),
    projection: $("assist-projection").value === "" ? null : Number($("assist-projection").value),
    trending_count: Number($("assist-trending").value || 0),
  };
  if (!payload.player || !payload.stat || Number.isNaN(payload.line)) return;
  const data = await api("/api/analysis/projection-assist", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  $("projection-assist-result").classList.remove("muted-card");
  $("projection-assist-result").innerHTML = `
    <div class="grade">${data.grade}</div>
    <h2>${data.recommendation}</h2>
    <p>${data.player} ${data.stat} ${data.line} · Projection ${data.projection} · Edge ${Number(data.edge).toFixed(2)}</p>
    <p>Confidence ${pct(data.confidence)} · Hit rate ${pct(data.estimated_hit_rate)} · ${data.source}</p>
    <p>${data.reason}</p>
  `;
}

async function importFinalStats(event) {
  event.preventDefault();
  const payload = $("final-stats-payload").value;
  const source = $("final-stats-source").value || "manual";
  const data = await api("/api/final-stats/import", {
    method: "POST",
    body: JSON.stringify({ payload, source }),
  });
  $("final-stats-result").classList.remove("muted-card");
  $("final-stats-result").innerHTML = `<h2>${data.imported}</h2><p>Final stat rows imported from ${data.source}.</p>`;
}

async function importBetHistory(event) {
  event.preventDefault();
  const data = await api("/api/bets/import-history", {
    method: "POST",
    body: JSON.stringify({
      payload: $("bet-history-payload").value,
      source: $("bet-history-source").value || "imported",
    }),
  });
  $("bet-history-result").classList.remove("muted-card");
  $("bet-history-result").innerHTML = `<h2>${data.imported}</h2><p>Imported bets · ${data.skipped} skipped. Performance and calibration are refreshed.</p>`;
  await loadBets();
  await loadDashboard();
  await loadPerformance();
}

async function analyzeUpload(event) {
  event.preventDefault();
  const file = $("upload-file").files[0];
  if (!file) {
    $("upload-result").textContent = "Choose a screenshot or file first.";
    return;
  }
  $("upload-result").classList.add("muted-card");
  const targetLabel = $("upload-target").value === "bet_history" ? "bet history screenshot or file" : "screenshot or file";
  $("upload-result").textContent = `Analyzing ${targetLabel}...`;
  const contentBase64 = await fileToBase64(file);
  const data = await api("/api/uploads/analyze", {
    method: "POST",
    body: JSON.stringify({
      file_name: file.name,
      mime_type: file.type,
      content_base64: contentBase64,
      target: $("upload-target").value,
      source: $("upload-source").value || "upload",
    }),
  });
  renderUploadResult(data);
  await loadDashboard();
  await loadPerformance();
}

function renderUploadResult(data) {
  const props = data.props || [];
  const rows = props.map((prop, index) => `
    <tr>
      <td><input type="checkbox" data-upload-prop-index="${index}" checked aria-label="Load ${escapeHtml(prop.player)}"></td>
      <td>${escapeHtml(prop.player)}</td>
      <td>${escapeHtml(prop.sport)}</td>
      <td>${directionBadge(prop.direction)} ${escapeHtml(prop.stat)}</td>
      <td>${escapeHtml(prop.line)}</td>
      <td>${escapeHtml(prop.platform || "")}</td>
    </tr>
  `).join("");
  $("upload-result").classList.remove("muted-card");
  $("upload-result").innerHTML = `
    <h2>${data.prop_count ?? data.imported ?? 0}</h2>
    <p>${data.message}</p>
    ${Number(data.duplicates_removed || 0) ? `<p class="subtle">${Number(data.duplicates_removed)} duplicate ${Number(data.duplicates_removed) === 1 ? "pick was" : "picks were"} removed.</p>` : ""}
    ${Number(data.rejected_unverified || 0) ? `<p class="warning">${Number(data.rejected_unverified)} ${Number(data.rejected_unverified) === 1 ? "row was" : "rows were"} not loaded because the pick could not be verified against the live provider board.</p>` : ""}
    ${data.local_ocr ? `<p class="positive">Processed privately on this Mac with on-device text recognition.</p>` : ""}
    ${data.ai_enabled === false && !data.local_ocr ? `<p class="warning">A clearer crop may work locally. OpenAI is optional and can improve difficult screenshots.</p>` : ""}
    ${data.ocr_text && !props.length ? `<details class="ocr-preview"><summary>Recognized text</summary><pre>${escapeHtml(data.ocr_text)}</pre></details>` : ""}
    ${props.length ? `
      <div class="table-wrap compact">
        <table>
          <thead><tr><th>Load</th><th>Player</th><th>Sport</th><th>Stat</th><th>Line</th><th>Platform</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <button class="secondary" id="load-upload-props">Load Selected Picks</button>
    ` : ""}
  `;
  if (props.length) {
    $("load-upload-props").addEventListener("click", () => {
      const selected = [...document.querySelectorAll("[data-upload-prop-index]:checked")]
        .map((input) => props[Number(input.dataset.uploadPropIndex)])
        .filter(Boolean);
      if (!selected.length) {
        $("upload-result").querySelector("p").textContent = "Select at least one verified pick to load.";
        return;
      }
      renderEntryPropsFromAnalyzed(selected);
      setView("entries");
      $("entry-status").textContent = `Loaded ${selected.length} verified uploaded picks. Analyze before placing.`;
    });
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function saveBet(event) {
  event.preventDefault();
  const payload = {
    sport: $("bet-sport").value,
    game: $("bet-game").value,
    description: $("bet-description").value,
    odds: Number($("bet-odds").value),
    wager: Number($("bet-wager").value),
    result: $("bet-result").value,
    platform: $("bet-platform").value,
    stat_type: $("bet-stat").value,
  };
  await api("/api/bets", { method: "POST", body: JSON.stringify(payload) });
  $("bet-form").reset();
  await loadBets();
  await loadDashboard();
}

async function loadBets() {
  const data = await api("/api/bets?limit=100&entry_limit=20");
  const entries = data.entries || [];
  const summary = data.summary || {};
  const savedCount = summary.saved_bets ?? data.bets.length;
  const completedCount = summary.completed_entries ?? entries.length;
  const displayNote = (summary.displayed_bets < savedCount || summary.displayed_entries < completedCount)
    ? ` · showing newest ${summary.displayed_bets || 0} bets and ${summary.displayed_entries || 0} entries`
    : "";
  $("bets-status").textContent = `${savedCount} saved bets · ${completedCount} completed entries${displayNote}`;
  $("bets-table").innerHTML = data.bets.map((bet) => `
    <tr>
      <td>${escapeHtml(bet.sport)}</td>
      <td>${escapeHtml(bet.game)}</td>
      <td>${escapeHtml(bet.description)}</td>
      <td>${escapeHtml(bet.source || "Manual")}</td>
      <td>${escapeHtml(bet.result)}</td>
      <td class="${bet.profit < 0 ? "danger-text" : ""}">${money(bet.profit)}</td>
    </tr>
  `).join("");
  renderCompletedEntryHistory(entries);
}

function renderCompletedEntryHistory(entries) {
  const target = $("entry-history-list");
  if (!target) return;
  $("entry-history-status").textContent = entries.length
    ? `${entries.length} completed entries · ${entries.reduce((sum, entry) => sum + Number(entry.calibration_legs || 0), 0)} provider-backed calibration legs`
    : "No completed entries with leg details yet.";
  target.innerHTML = entries.map((entry) => `
    <div class="suggestion entry-history-card">
      <div class="suggestion-top">
        <div>
          <span class="pill">#${entry.id}</span>
          <strong>${escapeHtml(entry.platform)} · ${escapeHtml(entry.result)}</strong>
          ${entry.entry_mode === "paper" ? `<span class="pill paper-pill">Paper</span>` : ""}
        </div>
        <span class="subtle">${entry.settled_at ? `Settled ${formatDateTime(entry.settled_at)}` : `Placed ${formatDateTime(entry.placed_at)}`}</span>
      </div>
      <div class="metric-strip">
        <span><strong>${money(entry.wager)}</strong><small>Wager</small></span>
        <span><strong>${Number(entry.multiplier || 1).toFixed(1)}x</strong><small>Multiplier</small></span>
        <span><strong class="${entry.profit < 0 ? "danger-text" : ""}">${money(entry.profit)}</strong><small>Profit</small></span>
        <span><strong>${Number(entry.calibration_legs || 0)}</strong><small>Calibration Legs</small></span>
      </div>
      <div class="entry-leg-history">
        ${(entry.props || []).map(renderCompletedEntryLeg).join("")}
      </div>
    </div>
  `).join("") || `<div class="suggestion">No completed entries yet. Settled entries will appear here with final stat details.</div>`;
}

function renderCompletedEntryLeg(prop) {
  const resultClass = prop.result === "Loss" ? "danger-text" : "";
  const actual = prop.actual === null || prop.actual === undefined || prop.actual === "" ? "No final stat" : Number(prop.actual).toLocaleString();
  const needsDetail = prop.actual === null || prop.actual === undefined || prop.actual === "";
  const source = prop.source === "projection_estimate"
    ? "Projection estimate"
    : prop.source === "unmatched"
      ? "No source matched"
      : friendlyStatus(prop.source);
  return `
    <div class="entry-leg-row">
      <div>
        <strong>${escapeHtml(prop.player)}</strong>
        <span>${escapeHtml(prop.team || prop.game || prop.sport || "")}</span>
      </div>
      <div>
        <span>${directionBadge(prop.direction || "Over")} ${escapeHtml(prop.stat)}</span>
        <strong>${escapeHtml(prop.line)}</strong>
      </div>
      <div>
        <span>Projection</span>
        <strong>${prop.projection == null ? "Auto" : Number(prop.projection).toLocaleString()}</strong>
      </div>
      <div>
        <span>Final Stat</span>
        <strong>${actual}</strong>
      </div>
      <div>
        <span>${escapeHtml(source)}</span>
        <strong class="${resultClass}">${escapeHtml(prop.result || "Pending")}</strong>
      </div>
      <div>
        <span>CLV</span>
        <strong class="${prop.clv?.clv < 0 ? "danger-text" : ""}">${prop.clv && prop.clv.clv !== null ? Number(prop.clv.clv).toFixed(1) : "-"}</strong>
      </div>
      ${renderSettlementEvidence(prop.settlement_evidence || {})}
      ${needsDetail ? `<p class="subtle entry-leg-detail">${escapeHtml(prop.match_detail || "No matching final stat row found.")}</p>` : ""}
    </div>
  `;
}

function renderSettlementEvidence(evidence) {
  const matchedPlayer = evidence.matched_player || "No confirmed player match";
  const matchedGame = evidence.matched_game || "No confirmed matchup";
  const matchedDate = evidence.matched_game_date || "No confirmed final date";
  return `
    <details class="settlement-evidence-drawer">
      <summary>Settlement Evidence</summary>
      <div class="settlement-evidence-grid">
        <span><small>Status</small><strong>${escapeHtml(friendlyStatus(evidence.verification_status || "unknown"))}</strong></span>
        <span><small>Final-stat source</small><strong>${escapeHtml(friendlyStatus(evidence.provider || "unmatched"))}</strong></span>
        <span><small>Requested player</small><strong>${escapeHtml(evidence.requested_player || "Unknown")}</strong></span>
        <span><small>Matched player</small><strong>${escapeHtml(matchedPlayer)}</strong></span>
        <span><small>Requested matchup</small><strong>${escapeHtml(evidence.requested_game || "Unavailable")}</strong></span>
        <span><small>Matched matchup</small><strong>${escapeHtml(matchedGame)}</strong></span>
        <span><small>Requested start</small><strong>${escapeHtml(evidence.requested_game_time ? formatDateTime(evidence.requested_game_time) : "Unavailable")}</strong></span>
        <span><small>Matched final date</small><strong>${escapeHtml(matchedDate)}</strong></span>
        <span><small>Player identity</small><strong>${escapeHtml(evidence.player_identity_id || "Not linked")}</strong></span>
        <span><small>Last checked</small><strong>${escapeHtml(evidence.last_checked_at ? formatDateTime(evidence.last_checked_at) : "No audit attempt")}</strong></span>
      </div>
      <p>${escapeHtml(evidence.message || "No settlement audit explanation is available.")}</p>
    </details>
  `;
}

function renderGroup(target, group) {
  const rows = Object.entries(group || {}).map(([name, stats]) => `
    <div class="suggestion">
      <strong>${name}</strong>
      <p>${Number(stats.tracked ?? ((stats.bets || 0) + (stats.entries || 0))).toLocaleString()} tracked · ${pct(stats.win_pct)} win · ${money(stats.profit)} profit · ${pct(stats.roi)} ROI</p>
    </div>
  `).join("");
  $(target).innerHTML = rows || `<p>No data yet.</p>`;
}

const PIE_COLORS = ["#39ff88", "#19e6ff", "#7c3cff", "#f8c14a", "#ff4d6d", "#9aa6ff", "#27d69b", "#f27dd4"];

function renderSportSuccessPie(group) {
  const rows = Object.entries(group || {})
    .map(([sport, stats]) => ({
      sport,
      wins: Number(stats.wins || 0),
      losses: Number(stats.losses || 0),
      pushes: Number(stats.pushes || 0),
      profit: Number(stats.profit || 0),
      roi: Number(stats.roi || 0),
      decisions: Number(stats.wins || 0) + Number(stats.losses || 0),
      winPct: Number(stats.win_pct || 0),
    }))
    .filter((row) => row.decisions > 0)
    .sort((a, b) => b.decisions - a.decisions || b.winPct - a.winPct)
    .slice(0, 8);

  const pie = $("sport-success-pie");
  const legend = $("sport-success-legend");
  if (!rows.length) {
    pie.style.background = "rgba(16, 21, 34, .92)";
    pie.innerHTML = `<span>No Data</span>`;
    legend.innerHTML = `<div class="suggestion">Settle tracked results to build the sport success chart.</div>`;
    return;
  }

  const total = rows.reduce((sum, row) => sum + row.decisions, 0);
  let cursor = 0;
  const stops = rows.map((row, index) => {
    const start = cursor;
    cursor += (row.decisions / total) * 100;
    const color = PIE_COLORS[index % PIE_COLORS.length];
    return `${color} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  });
  pie.style.background = `conic-gradient(${stops.join(", ")})`;
  pie.innerHTML = `<span>${rows[0].sport}<small>${pct(rows[0].winPct)}</small></span>`;
  legend.innerHTML = rows.map((row, index) => `
    <div class="pie-legend-row">
      <span class="pie-swatch" style="background:${PIE_COLORS[index % PIE_COLORS.length]}"></span>
      <strong>${row.sport}</strong>
      <span>${row.wins}-${row.losses}${row.pushes ? `-${row.pushes}` : ""}</span>
      <span>${pct(row.winPct)}</span>
      <span class="${row.profit < 0 ? "danger-text" : ""}">${money(row.profit)}</span>
    </div>
  `).join("");
}

function renderPerformanceInsights(insights) {
  $("performance-insights").innerHTML = (insights || []).map((insight) => `
    <div class="suggestion insight-${insight.tone || "neutral"}">
      <div class="suggestion-top">
        <strong>${insight.title}</strong>
        <span class="subtle">${insight.tone || "neutral"}</span>
      </div>
      <p>${insight.summary}</p>
    </div>
  `).join("") || `<div class="suggestion">No insights available yet.</div>`;
}

async function loadBankrollTransactions() {
  const data = await api("/api/bankroll/transactions");
  const summary = data.summary || {};
  $("bankroll-ledger-status").textContent = `Deposits ${money(summary.deposits)} · Withdrawals ${money(summary.withdrawals)} · Net ${money(summary.net)}`;
  $("bankroll-transaction-list").innerHTML = (data.transactions || []).slice(0, 8).map((transaction) => `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${transaction.transaction_type}</strong>
        <span class="subtle">${formatDateTime(transaction.created_at)}</span>
      </div>
      <p>${money(transaction.amount)}${transaction.note ? ` · ${transaction.note}` : ""}</p>
    </div>
  `).join("") || `<div class="suggestion">No bankroll transactions yet.</div>`;
}

async function saveBankrollTransaction(event) {
  event.preventDefault();
  const payload = {
    transaction_type: $("bankroll-transaction-type").value,
    amount: Number($("bankroll-transaction-amount").value),
    note: $("bankroll-transaction-note").value.trim(),
  };
  if (!payload.amount || payload.amount <= 0) return;
  await api("/api/bankroll/transactions", { method: "POST", body: JSON.stringify(payload) });
  $("bankroll-transaction-form").reset();
  await loadBankrollTransactions();
  await loadDashboard();
  await loadPerformance();
}

function showOnboardingIfNeeded() {
  const stored = localStorage.getItem("edgeiq.onboardingComplete");
  syncDefaultInputs();
  if (!stored) {
    $("onboarding-modal").hidden = false;
    $("onboarding-bankroll").focus();
  }
}

async function saveOnboarding(event) {
  event.preventDefault();
  const setup = {
    bankroll: Number($("onboarding-bankroll").value || 0),
    platform: $("onboarding-platform").value,
    sport: $("onboarding-sport").value,
    risk: $("onboarding-risk").value,
    defaultWager: Number($("onboarding-default-wager").value || 0),
  };
  localStorage.setItem("edgeiq.onboarding", JSON.stringify(setup));
  localStorage.setItem("edgeiq.onboardingComplete", "true");
  if (setup.bankroll > 0) {
    await api("/api/settings/bankroll", {
      method: "POST",
      body: JSON.stringify({ amount: setup.bankroll }),
    });
  }
  $("onboarding-modal").hidden = true;
  syncDefaultInputs();
  await loadDashboard();
  await loadCommandCenter();
}

function skipOnboarding() {
  localStorage.setItem("edgeiq.onboardingComplete", "true");
  $("onboarding-modal").hidden = true;
}

function openHistoryUploadFromOnboarding() {
  localStorage.setItem("edgeiq.onboardingComplete", "true");
  $("onboarding-modal").hidden = true;
  setView("analysis");
  activateWorkspace(document.querySelector('[data-workspace="research-workspace"]'), "imports");
  $("upload-target").value = "bet_history";
  $("upload-file").focus();
}

function openScreenshotImport() {
  setView("analysis");
  activateWorkspace(document.querySelector('[data-workspace="research-workspace"]'), "imports");
  $("upload-target").value = "bet_history";
  $("upload-source").value = "screenshot";
  $("upload-result").classList.add("muted-card");
  $("upload-result").textContent = "Choose a phone screenshot of a previous bet, then click Analyze Screenshot / File.";
  $("upload-file").focus();
}

function toggleMobileSlip() {
  const panel = $("mobile-slip-panel");
  panel.hidden = !panel.hidden;
  syncMobileSlip();
}

async function mobileAnalyzeEntry() {
  if ($("mobile-slip-wager").value) $("entry-wager").value = $("mobile-slip-wager").value;
  if ($("mobile-slip-multiplier").value) $("entry-multiplier").value = $("mobile-slip-multiplier").value;
  await analyzeEntry();
  $("mobile-slip-panel").hidden = true;
}

async function mobilePlaceEntry() {
  if ($("mobile-slip-wager").value) $("entry-wager").value = $("mobile-slip-wager").value;
  if ($("mobile-slip-multiplier").value) $("entry-multiplier").value = $("mobile-slip-multiplier").value;
  if (!state.lastEntryPayload && state.entryProps.length >= 2) {
    await analyzeEntry();
  }
  const placed = await placeEntryFromButton($("mobile-place-entry"));
  if (placed) $("mobile-slip-panel").hidden = true;
}

async function loadPerformance() {
  const data = await api("/api/performance");
  $("performance-summary").innerHTML = [
    ["Record", data.summary.record],
    ["Profit", money(data.summary.profit)],
    ["ROI", pct(data.summary.roi)],
    ["Bankroll", money(data.summary.bankroll)],
    ["Entry Profit", money(data.entries.profit)],
    ["Pending Exposure", money(data.entries.pending_exposure)],
  ].map(([label, value]) => `
    <div class="stat-card"><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>
  `).join("");
  renderGroup("perf-sport", data.by_sport);
  renderGroup("perf-stat", data.by_stat);
  renderGroup("perf-platform", data.by_platform);
  renderSportSuccessPie(data.by_sport);
  renderMonthlyProfit(data.monthly_profit || data.summary.monthly_profit || {});
  renderPerformanceInsights(data.summary.performance_insights);
  renderEntryPerformance(data.entries);
  renderEntryPlatformProfitability(data.summary.entry_platform_profitability || data.entries.platform_profitability || []);
}

function renderMonthlyProfit(monthly) {
  const current = monthly.current_month || {};
  const months = monthly.months || [];
  $("monthly-profit-current").innerHTML = `
    <div class="suggestion ${Number(current.profit || 0) < 0 ? "insight-warning" : "insight-positive"}">
      <div class="suggestion-top">
        <strong>${escapeHtml(current.label || "Current Month")}</strong>
        <span class="subtle">${Number(current.tracked || 0)} tracked</span>
      </div>
      <div class="metric-strip">
        <span><strong class="${Number(current.profit || 0) < 0 ? "danger-text" : ""}">${money(current.profit)}</strong><small>Profit</small></span>
        <span><strong>${current.wins || 0}-${current.losses || 0}-${current.pushes || 0}</strong><small>Record</small></span>
        <span><strong>${pct(current.roi || 0)}</strong><small>ROI</small></span>
        <span><strong>${money(current.cumulative_profit || 0)}</strong><small>YTD/Running</small></span>
      </div>
    </div>
  `;
  $("monthly-profit-log").innerHTML = months.map((month) => `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${escapeHtml(month.label || month.month)}</strong>
        <span class="${Number(month.profit || 0) < 0 ? "danger-text" : "subtle"}">${money(month.profit)}</span>
      </div>
      <p>${month.wins || 0}-${month.losses || 0}-${month.pushes || 0} · ${Number(month.tracked || 0)} tracked · ${pct(month.roi || 0)} ROI · ${money(month.cumulative_profit || 0)} running</p>
    </div>
  `).join("") || `<div class="suggestion">No settled monthly profit yet.</div>`;
}

function renderEntryPlatformProfitability(platforms) {
  $("entry-platform-profitability").innerHTML = platforms.map((platform) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>#${platform.rank} ${platform.platform}</strong>
        <span class="subtle">${platform.entries} tracked results</span>
      </div>
      <p>${money(platform.profit)} profit · ${money(platform.wagered)} wagered · ${pct(platform.roi)} ROI · ${pct(platform.win_pct)} win</p>
    </div>
  `).join("") || `<div class="suggestion">No settled platform results yet.</div>`;
}

function renderEntryPerformance(entries) {
  const resultRows = Object.entries(entries.by_result || {}).map(([result, stats]) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>${result} Results</strong>
        <span class="subtle">${stats.entries} tracked</span>
      </div>
      <p>${money(stats.profit)} profit · ${money(stats.wagered)} wagered · ${pct(stats.roi)} ROI</p>
    </div>
  `).join("");
  $("entry-result-performance").innerHTML = resultRows || `<div class="suggestion">No settled tracked results yet.</div>`;
}

async function loadBacktest() {
  const data = await api("/api/analytics/backtest");
  const scorecard = data.scorecard || {};
  const sources = data.calibration_sources || {};
  const holdout = data.holdout_validation || {};
  const walkForward = data.walk_forward_validation || {};
  const grouped = data.grouped_validation || {};
  const ledger = data.prediction_ledger || {};
  const shadow = data.shadow_evaluation || {};
  const projectionAccuracy = ledger.projection_accuracy || {};
  const readiness = data.validation_readiness || {};
  $("backtest-summary").innerHTML = `
    <div class="suggestion ${readiness.status === "validated" ? "insight-positive" : "insight-warning"}">
      <div class="suggestion-top">
        <strong>${escapeHtml(readiness.release || "Release Validation")}</strong>
        <span class="score-pill">${Number(readiness.progress_pct || 0).toFixed(0)}%</span>
      </div>
      <p>${readiness.status === "validated"
        ? "The required validation evidence is complete."
        : `${readiness.passed_gates || 0} of ${readiness.total_gates || 0} reliability gates passed.`}</p>
      <div class="validation-gates">
        ${(readiness.gates || []).map((gate) => `
          <div class="validation-gate">
            <div class="suggestion-top">
              <strong>${escapeHtml(gate.label)}</strong>
              <span class="status-pill ${gate.passed ? "status-connected" : "status-degraded"}">${gate.passed ? "Passed" : "Collecting"}</span>
            </div>
            <progress value="${Number(gate.progress_pct || 0)}" max="100"></progress>
            <p class="subtle">${escapeHtml(gate.detail || "")}</p>
          </div>
        `).join("")}
      </div>
      ${(readiness.next_actions || []).length ? `
        <div class="scorecard-next-actions">
          <strong>How to reach v2.2</strong>
          ${(readiness.next_actions || []).map((action) => `<p>${escapeHtml(action)}</p>`).join("")}
        </div>
      ` : ""}
    </div>
    <div class="suggestion ${grouped.passed ? "insight-positive" : "insight-warning"}">
      <div class="suggestion-top">
        <strong>Versioned Out-of-Sample Validation</strong>
        <span class="status-pill ${grouped.passed ? "status-connected" : "status-degraded"}">${grouped.passed ? "Proven" : "Paper Mode"}</span>
      </div>
      <div class="metric-strip">
        <span><strong>${grouped.unique_predictions || 0}</strong><small>Independent</small></span>
        <span><strong>${grouped.evaluated_predictions || 0}</strong><small>Rolling Tests</small></span>
        <span><strong>${Number(grouped.brier_score || 0).toFixed(3)}</strong><small>Brier</small></span>
        <span><strong>${Number(grouped.expected_calibration_error || 0).toFixed(1)}%</strong><small>Calibration Error</small></span>
      </div>
      <p class="subtle">${escapeHtml(grouped.message || "New versioned predictions will be evaluated after their verified results arrive.")}</p>
      <p class="subtle">${ledger.versioned_records || 0} versioned records · ${ledger.legacy_quarantined || 0} legacy records quarantined</p>
    </div>
    <div class="suggestion ${shadow.release_ready ? "insight-positive" : "insight-warning"}">
      <div class="suggestion-top">
        <strong>v2.2 Shadow Evaluation</strong>
        <span class="status-pill ${shadow.release_ready ? "status-connected" : "status-degraded"}">${shadow.release_ready ? "Release Review" : "Shadow Mode"}</span>
      </div>
      <div class="metric-strip">
        <span><strong>${Number(shadow.queued || 0)}</strong><small>Queued</small></span>
        <span><strong>${Number(shadow.settled || 0)}</strong><small>Verified Finals</small></span>
        <span><strong>${pct(shadow.accuracy || 0)}</strong><small>Accuracy</small></span>
      </div>
      <p class="subtle">Shadow predictions cannot affect paid recommendations until 100 verified decisions settle at 55% accuracy or better.</p>
    </div>
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>Projection Accuracy</strong>
        <span class="status-pill ${Number(projectionAccuracy.verified_predictions || 0) >= 100 ? "status-connected" : "status-degraded"}">${projectionAccuracy.verified_predictions || 0} verified</span>
      </div>
      <div class="metric-strip">
        <span><strong>${projectionAccuracy.mae == null ? "-" : Number(projectionAccuracy.mae).toFixed(2)}</strong><small>Historical MAE</small></span>
        <span><strong>${projectionAccuracy.market_line_mae == null ? "-" : Number(projectionAccuracy.market_line_mae).toFixed(2)}</strong><small>Market MAE</small></span>
        <span><strong>${projectionAccuracy.regularized_mae == null ? "-" : Number(projectionAccuracy.regularized_mae).toFixed(2)}</strong><small>Blended MAE</small></span>
        <span><strong>${projectionAccuracy.regularization_improvement_pct == null ? "-" : pct(projectionAccuracy.regularization_improvement_pct)}</strong><small>Improvement</small></span>
      </div>
      <p class="subtle">EdgeIQ v2.2 blends verified player history with the provider's standard market line and tracks its error only after official finals arrive.</p>
    </div>
    <div class="suggestion accuracy-scorecard">
      <div>
        <div class="suggestion-top">
          <strong>${scorecard.verdict || "Collect more samples"}</strong>
          <span class="score-pill">${Number(scorecard.score || 0).toFixed(1)} / 100</span>
        </div>
        <p>${scorecard.recommendation || "Log more results to unlock model guidance."}</p>
      </div>
      <div class="accuracy-grid">
        <div><strong>${scorecard.sample_size || 0}</strong><span>Samples</span></div>
        <div><strong>${pct(scorecard.win_rate || 0)}</strong><span>Win Rate</span></div>
        <div><strong>${pct(scorecard.roi || 0)}</strong><span>ROI</span></div>
        <div><strong>${pct(scorecard.calibration_gap || 0)}</strong><span>Cal Gap</span></div>
      </div>
    </div>
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>All Tracked Results</strong>
        <span class="subtle">${data.tracked.count} records</span>
      </div>
      <div class="metric-strip">
        <span><strong>${data.tracked.wins}-${data.tracked.losses}-${data.tracked.pushes}</strong><small>Record</small></span>
        <span><strong>${pct(data.tracked.win_rate)}</strong><small>Win Rate</small></span>
        <span><strong>${money(data.tracked.profit)}</strong><small>Profit</small></span>
        <span><strong>${pct(data.tracked.roi)}</strong><small>ROI</small></span>
      </div>
    </div>
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>EdgeIQ Confidence Check</strong>
        <span class="subtle">${data.entries.count} records</span>
      </div>
      <div class="metric-strip">
        <span><strong>${pct(data.entries.confidence.actual_win_rate)}</strong><small>Actual</small></span>
        <span><strong>${pct(data.entries.confidence.average_confidence)}</strong><small>Avg Confidence</small></span>
        <span><strong>${pct(data.entries.confidence.edge)}</strong><small>Gap</small></span>
      </div>
      <p class="subtle">Shows whether EdgeIQ has been under-rating or over-rating placed entries.</p>
    </div>
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>Calibration Inputs</strong>
        <span class="subtle">${sources.total_rows || 0} samples</span>
      </div>
      <div class="metric-strip">
        <span><strong>${sources.entry_rows || 0}</strong><small>Entries</small></span>
        <span><strong>${sources.prop_rows || 0}</strong><small>Legs</small></span>
        <span><strong>${sources.provider_rows || 0}</strong><small>Provider Truth</small></span>
        <span><strong>${sources.bet_rows || 0}</strong><small>Imported Bets</small></span>
      </div>
      <p class="subtle">Official ESPN final stats provide the verified leg-level outcomes used for calibration.</p>
    </div>
    <div class="suggestion ${holdout.passed ? "insight-positive" : "insight-warning"}">
      <div class="suggestion-top">
        <strong>Time-Based Holdout</strong>
        <span class="subtle">${holdout.ready ? `${holdout.holdout_count || 0} unseen results` : "Building sample"}</span>
      </div>
      <div class="metric-strip">
        <span><strong>${pct(holdout.predicted_win_rate || 0)}</strong><small>Predicted</small></span>
        <span><strong>${pct(holdout.actual_win_rate || 0)}</strong><small>Actual</small></span>
        <span><strong>${pct(holdout.calibration_gap || 0)}</strong><small>Gap</small></span>
      </div>
      <p class="subtle">${escapeHtml(holdout.message || "More settled entries are needed before paid release validation.")}</p>
    </div>
    <div class="suggestion ${walkForward.passed ? "insight-positive" : "insight-warning"}">
      <div class="suggestion-top">
        <strong>Walk-Forward Validation</strong>
        <span class="subtle">${walkForward.ready ? `${walkForward.folds || 0} historical folds` : "Building sample"}</span>
      </div>
      <div class="metric-strip">
        <span><strong>${Number(walkForward.brier_score || 0).toFixed(3)}</strong><small>Brier Score</small></span>
        <span><strong>${pct(walkForward.predicted_win_rate || 0)}</strong><small>Predicted</small></span>
        <span><strong>${pct(walkForward.actual_win_rate || 0)}</strong><small>Actual</small></span>
        <span><strong>${walkForward.leakage_free ? "Yes" : "No"}</strong><small>No Future Data</small></span>
      </div>
      <p class="subtle">${escapeHtml(walkForward.message || "Only outcomes available before each historical pick are used for training.")}</p>
    </div>
    ${Object.entries(data.entries.by_grade).map(([grade, stats]) => `
      <div class="suggestion">
        <div class="suggestion-top">
          <strong>Grade ${grade}</strong>
          <span class="subtle">${stats.entries} entries</span>
        </div>
        <div class="metric-strip">
          <span><strong>${pct(stats.win_rate)}</strong><small>Win Rate</small></span>
          <span><strong>${stats.wins}-${stats.losses}-${stats.pushes}</strong><small>Record</small></span>
        </div>
      </div>
    `).join("")}
  `;
  $("calibration-list").innerHTML = `
    ${(data.calibration_rules || []).map((rule) => `
      <div class="suggestion insight-${rule.severity || "neutral"} rule-card">
        <div class="suggestion-top">
          <strong>${rule.segment}</strong>
          <span class="subtle">${rule.sample_size} samples</span>
        </div>
        <div class="rule-action">${rule.action}</div>
        <p class="subtle">${rule.reason}</p>
      </div>
    `).join("") || `<div class="suggestion">No calibration rules yet. Add more settled or paper entries.</div>`}
    ${data.calibration.map((bucket) => `
      <div class="suggestion compact-suggestion">
        <div class="suggestion-top">
          <strong>${bucket.label}</strong>
          <span class="subtle">${bucket.bets} picks</span>
        </div>
        <div class="metric-strip">
          <span><strong>${pct(bucket.predicted_mid)}</strong><small>Predicted</small></span>
          <span><strong>${pct(bucket.actual_pct)}</strong><small>Actual</small></span>
          <span><strong>${pct(bucket.error)}</strong><small>Error</small></span>
        </div>
      </div>
    `).join("")}
  `;
  $("backtest-works").innerHTML = renderSegmentList(data.what_works, "No proven winning segments yet.");
  $("backtest-fails").innerHTML = renderSegmentList(data.what_fails, "No failing segments detected yet.");
}

async function refreshCalibrationData() {
  $("entry-status").textContent = "Checking unresolved final stats for calibration...";
  const data = await api("/api/analytics/refresh-calibration-data", { method: "POST" });
  $("entry-status").textContent = `Calibration refresh checked ${data.entries_targeted || 0} relevant entries: ${data.provider_refresh.imported || 0} stat rows saved, ${data.backfill.provider_rows || 0} provider leg results linked.`;
  await Promise.allSettled([loadBacktest(), loadPerformance(), loadAccuracyLab(), loadDataHealth(), loadNotifications()]);
}

async function repairDataIntegrity() {
  const status = $("data-integrity-repair-status");
  status.textContent = "Scanning historical entries without changing records...";
  const preview = await api("/api/analytics/data-integrity-repair?dry_run=true", { method: "POST" });
  if (!preview.candidate_entries) {
    status.textContent = "Integrity scan complete. No unquarantined invalid markets were found.";
    return;
  }
  const confirmed = window.confirm(
    `EdgeIQ found ${preview.candidate_entries} entries containing ${preview.invalid_props} implausible markets. `
    + "A database backup will be created, affected cards will be excluded from results, and calibration will be rebuilt. Continue?",
  );
  if (!confirmed) {
    status.textContent = `Preview complete: ${preview.candidate_entries} entries need repair. No records changed.`;
    return;
  }
  status.textContent = "Backing up data and repairing invalid markets...";
  const result = await api("/api/analytics/data-integrity-repair?dry_run=false", { method: "POST" });
  status.textContent = `${result.message} Backup: ${result.backup?.path || "created"}.`;
  await Promise.allSettled([loadBacktest(), loadPerformance(), loadAccuracyLab(), loadDataHealth(), loadPending()]);
}

async function previewFinalStatsRepair() {
  const preview = await api("/api/entries/recheck-final-stats/preview");
  const target = $("settlement-repair-preview");
  if (target) {
    target.hidden = false;
    target.innerHTML = `
      <div class="suggestion compact-suggestion ${preview.local_changes ? "insight-positive" : "insight-neutral"}">
        <div class="suggestion-top">
          <strong>Read-only repair preview</strong>
          <span class="pill">No records changed</span>
        </div>
        <p>${escapeHtml(preview.message || "Repair preview complete.")}</p>
        <div class="metric-strip">
          <span><strong>${Number(preview.entries_reviewed || 0)}</strong><small>Entries Reviewed</small></span>
          <span><strong>${Number(preview.local_changes || 0)}</strong><small>Local Updates</small></span>
          <span><strong>${Number(preview.provider_refresh_needed || 0)}</strong><small>Provider Checks</small></span>
        </div>
      </div>
      ${(preview.items || []).filter((item) => item.will_change).slice(0, 12).map((item) => `
        <div class="suggestion compact-suggestion">
          <div class="suggestion-top">
            <strong>Entry #${Number(item.entry_id || 0)} · ${escapeHtml(item.player || "Unknown player")}</strong>
            <span class="status-pill status-connected">Update available</span>
          </div>
          <p>${escapeHtml(item.direction || "Over")} ${escapeHtml(item.line)} ${escapeHtml(item.stat || "Stat")} · ${escapeHtml(item.current?.result || "Pending")} to ${escapeHtml(item.proposed?.result || "Pending")}</p>
          <p class="subtle">${escapeHtml(item.reason || "Confirmed local evidence matched.")}</p>
        </div>
      `).join("")}
    `;
  }
  return preview;
}

async function recheckFinalStats() {
  $("entry-history-status").textContent = "Preparing a read-only final stat preview...";
  const preview = await previewFinalStatsRepair();
  const confirmed = window.confirm(
    `${preview.message || "Preview complete."}\n\nContinue with the provider refresh and apply verified settlement updates?`,
  );
  if (!confirmed) {
    $("entry-history-status").textContent = "Final stat recheck canceled. No records were changed.";
    return;
  }
  $("entry-history-status").textContent = "Checking previous entries against final stat providers...";
  const data = await api("/api/entries/recheck-final-stats", { method: "POST" });
  const imported = data.provider_refresh?.imported || 0;
  const linked = data.backfill?.provider_rows || 0;
  const settled = data.auto_check?.settled || 0;
  const corrected = data.result_review?.corrected || 0;
  const reviewed = data.result_review?.reviewed || 0;
  $("entry-history-status").textContent = `Final stat recheck complete: ${data.cleared_unknowns || 0} unknown legs cleared, ${data.unknown_after || 0} still unknown. ${imported} provider rows imported, ${linked} leg results linked, ${settled} pending settled, ${corrected}/${reviewed} previous results corrected.`;
  await Promise.allSettled([loadBets(), loadEntryProgress({ autoCheck: false, refreshProviders: false }), loadPerformance(), loadBacktest(), loadSettlementAudit(), loadAccuracyLab(), loadNotifications()]);
}

async function createAutoPaperCalibrationEntries() {
  const sport = $("auto-paper-sport")?.value || "All Sports";
  const platform = $("auto-paper-platform")?.value || "PrizePicks";
  $("auto-paper-calibration-status").textContent = `Building five ${sport} calibration cards from weak confidence buckets...`;
  const data = await api("/api/entries/auto-paper-calibration", {
    method: "POST",
    body: JSON.stringify({
      platform,
      sport,
      leg_count: 2,
      max_entries: 5,
      standard_batch: true,
      prefer_confirmed: true,
      dry_run: false,
    }),
  });
  const skippedText = (data.skipped || []).slice(0, 2).map((row) => escapeHtml(row.reason || "")).filter(Boolean).join(" ");
  const plan = (data.created_plan || []).map((legs) => `${Number(legs)}-leg`).join(", ");
  const diagnostics = data.board_diagnostics || {};
  const sportResults = (data.sport_results || []).map((row) => `
    <span class="status-pill ${Number(row.shortfall || 0) ? "status-warning" : "status-connected"}">${escapeHtml(row.sport)} ${Number(row.created_count || 0)}/5</span>
  `).join("");
  $("auto-paper-calibration-status").innerHTML = `
    Created ${data.created_count} of ${data.requested_count || 5} ${escapeHtml(sport)} paper calibration entries${plan ? `: ${escapeHtml(plan)}` : "."}
    ${sportResults}
    ${(data.created || []).map((row) => `
      <span class="status-pill status-paper">${escapeHtml(row.target?.name || row.target?.type || "Target")}</span>
    `).join("") || (skippedText ? `<span class="subtle">${skippedText}</span>` : "")}
    ${data.shortfall ? `<span class="subtle">${Number(data.shortfall)} card${Number(data.shortfall) === 1 ? "" : "s"} could not be built. EdgeIQ found ${Number(diagnostics.eligible_same_day_props || 0)} unique same-day verified props across ${escapeHtml((diagnostics.sports || []).join(", ") || "no available sports")}; ${Number(diagnostics.pending_paper_cards || 0)} paper cards are already pending.</span>` : ""}
  `;
  $("entry-status").textContent = data.created_count
    ? `Created ${data.created_count} pending paper calibration entries.`
    : "No new paper entries created; current targets may already be covered.";
  await Promise.allSettled([loadPending(), loadBacktest(), loadDashboard(), loadAccuracyLab()]);
}

function renderSegmentList(segments, emptyText) {
  return (segments || []).map((segment) => `
    <div class="suggestion segment-card">
      <div class="suggestion-top">
        <strong>${segment.type}: ${segment.name}</strong>
        <span class="subtle">${segment.tracked} tracked</span>
      </div>
      <div class="metric-strip">
        <span><strong>${segment.wins}-${segment.losses}-${segment.pushes}</strong><small>Record</small></span>
        <span><strong>${pct(segment.win_rate)}</strong><small>${segment.basis === "leg_outcomes" ? "Verified Hit Rate" : "Win Rate"}</small></span>
        ${segment.basis === "leg_outcomes"
          ? `<span><strong>${segment.tracked}</strong><small>Verified Legs</small></span>`
          : `<span><strong>${money(segment.profit)}</strong><small>Profit</small></span><span><strong>${pct(segment.roi)}</strong><small>ROI</small></span>`}
      </div>
      <div class="card-action">${segment.action}</div>
    </div>
  `).join("") || `<div class="suggestion">${emptyText}</div>`;
}

async function loadPreferences() {
  const data = await api("/api/settings/preferences");
  const prefs = data.preferences || data;
  if ($("pref-display-name")) $("pref-display-name").value = prefs.display_name || "Joshua";
  $("pref-risk-style").value = prefs.risk_style || "balanced";
  $("pref-legs").value = prefs.preferred_legs || "2-3";
  $("pref-max-wager-pct").value = prefs.max_wager_pct || 5;
  $("pref-high-risk").checked = prefs.allow_high_risk !== false;
  $("pref-avoid-same-game").checked = prefs.avoid_same_game !== false;
  const audio = window.EdgeIQAudio?.settings() || { enabled: true, volume: 0.42 };
  $("pref-sound-effects").checked = audio.enabled;
  $("pref-sound-volume").value = Math.round(audio.volume * 100);
  $("preview-sound").disabled = !audio.enabled;
}

async function savePreferences(event) {
  event.preventDefault();
  const payload = {
    risk_style: $("pref-risk-style").value,
    preferred_legs: $("pref-legs").value,
    allow_high_risk: $("pref-high-risk").checked,
    avoid_same_game: $("pref-avoid-same-game").checked,
    max_wager_pct: Number($("pref-max-wager-pct").value || 5),
    default_platform: $("entry-platform").value,
    default_sport: $("props-sport").value,
    display_name: $("pref-display-name")?.value || "Joshua",
  };
  await api("/api/settings/preferences", { method: "POST", body: JSON.stringify(payload) });
  window.EdgeIQAudio?.save({
    enabled: $("pref-sound-effects").checked,
    volume: Number($("pref-sound-volume").value || 0) / 100,
  });
  $("preferences-status").textContent = "Preferences saved. Recommendations and guardrails now use this profile.";
  await loadCommandCenter();
}

async function loadAccuracyLab() {
  const data = await api("/api/analytics/accuracy-lab");
  $("accuracy-lab").innerHTML = `
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>Audit Coverage</strong>
        <span class="subtle">${data.summary.audit_snapshots} snapshots</span>
      </div>
      <p>${data.summary.settled_entries} settled entries · ${data.summary.recommended_settled} recommended settled entries.</p>
    </div>
    ${data.confidence_buckets.map((bucket) => `
      <div class="suggestion compact-suggestion">
        <strong>Confidence ${bucket.label}</strong>
        <p>${bucket.entries} entries · ${bucket.wins}-${bucket.losses} · ${pct(bucket.win_pct)} win · avg confidence ${pct(bucket.avg_confidence)}</p>
      </div>
    `).join("")}
    ${(data.audit_trail || []).slice(0, 8).map((row) => `
      <div class="suggestion compact-suggestion">
        <div class="suggestion-top">
          <strong>Entry #${row.entry_id} · ${row.grade || "Ungraded"}</strong>
          <span class="subtle">${formatDateTime(row.placed_at)}</span>
        </div>
        <p>${row.result || "Pending"} · locked ${row.line_snapshot_count} legs · ${row.recommendation.action || "No action saved"}</p>
      </div>
    `).join("")}
  `;
}

function bindEvents() {
  setupWorkspaces();
  setupButtonSounds();
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-workspace-jump]");
    if (button) jumpToWorkspace(button);
    const opportunityButton = event.target.closest("[data-focus-opportunity-board]");
    if (opportunityButton) focusOpportunityBoard();
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  document.querySelectorAll("[data-view-shortcut]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.viewShortcut));
  });
  document.querySelectorAll("[data-phone-scan]").forEach((button) => {
    button.addEventListener("click", () => withButtonBusy(button, "Scanning...", startDailyBriefingScan));
  });
  document.querySelectorAll("[data-phone-install]").forEach((button) => {
    button.addEventListener("click", installPwa);
  });
  $("refresh-all").addEventListener("click", () => withButtonBusy("refresh-all", "Refreshing...", () => loadAll({ refresh: true })));
  $("install-app").addEventListener("click", installPwa);
  $("dismiss-install-hint").addEventListener("click", () => {
    window.localStorage.setItem("edgeiq-install-dismissed", "1");
    $("install-hint").hidden = true;
  });
  $("refresh-daily-briefing").addEventListener("click", () => withButtonBusy("refresh-daily-briefing", "Scanning...", startDailyBriefingScan));
  $("refresh-command-center").addEventListener("click", () => withButtonBusy("refresh-command-center", "Checking...", loadCommandCenter));
  $("refresh-advantage-center").addEventListener("click", () => withButtonBusy("refresh-advantage-center", "Checking...", loadAdvantageCenter));
  $("refresh-data-health").addEventListener("click", () => withButtonBusy("refresh-data-health", "Checking...", loadDataHealth));
  $("refresh-runtime-status")?.addEventListener("click", () => withButtonBusy("refresh-runtime-status", "Checking...", loadRuntimeStatus));
  $("backup-database").addEventListener("click", () => withButtonBusy("backup-database", "Backing up...", () => manageDatabase("backup")));
  $("export-database").addEventListener("click", () => withButtonBusy("export-database", "Exporting...", () => manageDatabase("export")));
  $("refresh-notifications").addEventListener("click", () => withButtonBusy("refresh-notifications", "Checking...", loadNotifications));
  $("refresh-deploy-readiness").addEventListener("click", () => withButtonBusy("refresh-deploy-readiness", "Checking...", loadDeployReadiness));
  $("run-daily-refresh").addEventListener("click", () => withButtonBusy("run-daily-refresh", "Running...", runDailyRefresh));
  $("refresh-timing-alerts").addEventListener("click", () => withButtonBusy("refresh-timing-alerts", "Checking...", loadTimingAlerts));
  ["timing-min-confidence", "timing-min-ev", "timing-alert-type", "timing-hide-outliers"].forEach((id) => {
    $(id).addEventListener("change", loadTimingAlerts);
  });
  $("refresh-progress").addEventListener("click", () => withButtonBusy("refresh-progress", "Checking...", () => loadEntryProgress({ autoCheck: true, refreshProviders: true })));
  $("sync-now").addEventListener("click", () => withButtonBusy("sync-now", "Syncing...", runSync));
  $("refresh-games").addEventListener("click", () => withButtonBusy("refresh-games", "Loading...", () => loadTrendingGames()));
  $("ask-ai-parlay").addEventListener("click", askAiParlay);
  document.querySelectorAll("[data-ai-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      $("ai-parlay-input").value = button.dataset.aiPrompt;
      askAiParlay();
    });
  });
  $("load-props").addEventListener("click", () => withButtonBusy("load-props", "Loading...", loadProps));
  $("prop-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const prop = propFromForm();
    if (!prop.player || !prop.line) return;
    const maximumLegs = providerMaximumLegs(prop.platform);
    if (state.entryProps.length >= maximumLegs) {
      $("entry-status").textContent = `${prop.platform} entries support at most ${maximumLegs} legs.`;
      playCircuitSound("warning");
      return;
    }
    const entryDefaults = {
      platform: $("entry-platform").value,
      mode: $("entry-mode").value,
      wager: $("entry-wager").value,
      multiplier: $("entry-multiplier").value,
      payoutType: $("entry-payout-type").value,
    };
    state.entryProps.push(prop);
    $("prop-form").reset();
    $("entry-platform").value = entryDefaults.platform;
    $("entry-mode").value = entryDefaults.mode;
    $("entry-wager").value = entryDefaults.wager;
    $("entry-multiplier").value = entryDefaults.multiplier || "3";
    $("entry-payout-type").value = entryDefaults.payoutType || "standard";
    renderEntryProps();
  });
  $("entry-platform").addEventListener("change", () => {
    const platform = $("entry-platform").value;
    const sourcePlatforms = entrySourcePlatforms();
    if (sourcePlatforms.length === 1 && sourcePlatforms[0] !== platform) {
      $("entry-platform").value = sourcePlatforms[0];
      $("entry-status").textContent = `These legs came from ${sourcePlatforms[0]}. Clear them before building a ${platform} entry.`;
      playCircuitSound("warning");
      return;
    }
    state.lastEntryPayload = null;
    state.lastAnalysis = null;
    state.recommendationOrigin = false;
    state.recommendationSnapshotId = "";
    $("ai-review-entry").disabled = true;
    $("prepare-handoff").disabled = true;
    $("place-entry").disabled = true;
    renderEntryProps();
    $("entry-status").textContent = `New props will be validated against ${platform}.`;
  });
  $("entry-mode").addEventListener("change", () => {
    state.lastEntryPayload = null;
    state.lastAnalysis = null;
    $("ai-review-entry").disabled = true;
    $("prepare-handoff").disabled = true;
    $("place-entry").disabled = true;
    syncEntryActionLabels();
    $("entry-status").textContent = $("entry-mode").value === "paper"
      ? "Paper mode selected. Analyze, then save a zero-wager calibration entry."
      : "Paid mode selected. Analyze again to run provider EV and release checks.";
  });
  $("analyze-entry").addEventListener("click", () => withButtonBusy("analyze-entry", "Analyzing...", analyzeEntry));
  $("ai-review-entry").addEventListener("click", reviewEntryWithAi);
  $("prepare-handoff").addEventListener("click", () => withButtonBusy("prepare-handoff", "Preparing...", prepareEntryHandoff));
  $("place-entry").addEventListener("click", (event) => placeEntryFromButton(event.currentTarget));
  syncEntryActionLabels();
  $("clear-entry").addEventListener("click", () => {
    state.entryProps = [];
    state.lastEntryPayload = null;
    state.lastAnalysis = null;
    state.recommendationOrigin = false;
    $("ai-review-entry").disabled = true;
    $("prepare-handoff").disabled = true;
    $("place-entry").disabled = true;
    $("entry-handoff").classList.add("muted-card");
    $("entry-handoff").textContent = "No handoff prepared yet.";
    renderEntryProps();
  });
  $("generate-confirmed-entries").addEventListener("click", () => withButtonBusy("generate-confirmed-entries", "Building...", loadConfirmedEntries));
  $("generate-prizepicks").addEventListener("click", () => withButtonBusy(
    "generate-prizepicks",
    "Building...",
    () => loadProviderSuggestions("PrizePicks", "prizepicks-generator-sport", "prizepicks-generator-legs", "prizepicks-suggestions-list"),
  ));
  $("generate-underdog").addEventListener("click", () => withButtonBusy(
    "generate-underdog",
    "Building...",
    () => loadProviderSuggestions("Underdog", "underdog-generator-sport", "underdog-generator-legs", "underdog-suggestions-list"),
  ));
  $("run-optimizer").addEventListener("click", () => withButtonBusy("run-optimizer", "Optimizing...", () => runOptimizer(false)));
  $("run-portfolio-batch").addEventListener("click", () => withButtonBusy("run-portfolio-batch", "Diversifying...", () => runOptimizer(true)));
  $("refresh-portfolio-lines").addEventListener("click", () => withButtonBusy("refresh-portfolio-lines", "Refreshing...", refreshPortfolioLines));
  $("ask-copilot").addEventListener("click", () => withButtonBusy("ask-copilot", "Researching...", askCopilot));
  $("evaluate-copilot-model").addEventListener("click", () => withButtonBusy("evaluate-copilot-model", "Checking...", evaluateCopilotModel));
  document.querySelectorAll("[data-copilot-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      $("copilot-question").value = button.dataset.copilotPrompt;
      askCopilot();
    });
  });
  $("refresh-sportsbook-sync").addEventListener("click", () => withButtonBusy("refresh-sportsbook-sync", "Checking...", loadSportsbookSync));
  $("refresh-trending-props").addEventListener("click", () => withButtonBusy("refresh-trending-props", "Loading...", loadTrendingProps));
  $("send-selected-trending").addEventListener("click", sendSelectedTrendingProps);
  $("clear-selected-trending").addEventListener("click", clearTrendingPropSelection);
  $("refresh-pending").addEventListener("click", () => withButtonBusy("refresh-pending", "Checking...", loadPending));
  $("classify-default-wagers").addEventListener("click", () => withButtonBusy("classify-default-wagers", "Classifying...", classifyDefaultWagers));
  $("save-dnp-handling").addEventListener("click", saveDnpSetting);
  $("auto-check-entries").addEventListener("click", () => withButtonBusy("auto-check-entries", "Checking...", autoCheckEntries));
  $("expedite-entries").addEventListener("click", () => withButtonBusy("expedite-entries", "Clearing...", expediteEntries));
  $("line-shop-form").addEventListener("submit", shopLines);
  $("player-research-form").addEventListener("submit", loadPlayerResearch);
  $("research-context-form").addEventListener("submit", runFullResearch);
  $("sharp-consensus-form").addEventListener("submit", loadSharpConsensus);
  $("hedge-form").addEventListener("submit", calculateHedge);
  $("middle-form").addEventListener("submit", calculateMiddle);
  $("ev-scanner-form").addEventListener("submit", runEvScanner);
  $("load-clv").addEventListener("click", loadClvReport);
  $("alert-delivery-form").addEventListener("submit", saveAlertDeliverySettings);
  $("test-alert-delivery").addEventListener("click", () => withButtonBusy("test-alert-delivery", "Testing...", testAlertDelivery));
  $("load-import-wizard").addEventListener("click", loadImportWizard);
  $("ev-form").addEventListener("submit", calculateEv);
  $("line-movement-form").addEventListener("submit", loadLineMovement);
  $("hit-rate-form").addEventListener("submit", estimateHitRate);
  $("projection-assist-form").addEventListener("submit", assistProjection);
  $("final-stats-form").addEventListener("submit", importFinalStats);
  $("upload-analyzer-form").addEventListener("submit", analyzeUpload);
  $("bet-history-form").addEventListener("submit", importBetHistory);
  $("refresh-grading-report").addEventListener("click", () => withButtonBusy("refresh-grading-report", "Checking...", loadGradingReport));
  $("refresh-settlement-audit").addEventListener("click", () => withButtonBusy("refresh-settlement-audit", "Refreshing...", loadSettlementAudit));
  $("preview-settlement-repair").addEventListener("click", () => withButtonBusy("preview-settlement-repair", "Previewing...", previewFinalStatsRepair));
  $("refresh-loss-review").addEventListener("click", () => withButtonBusy("refresh-loss-review", "Reviewing...", loadLossReview));
  $("open-screenshot-import").addEventListener("click", openScreenshotImport);
  $("bet-form").addEventListener("submit", saveBet);
  $("bankroll-transaction-form").addEventListener("submit", saveBankrollTransaction);
  $("refresh-bets").addEventListener("click", () => withButtonBusy("refresh-bets", "Checking...", loadBets));
  document.querySelectorAll(".recheck-final-stats").forEach((button) => {
    button.addEventListener("click", () => withButtonBusy(button, "Checking...", recheckFinalStats));
  });
  $("refresh-backtest").addEventListener("click", () => withButtonBusy("refresh-backtest", "Refreshing...", loadBacktest));
  $("refresh-calibration-data").addEventListener("click", () => withButtonBusy("refresh-calibration-data", "Refreshing...", refreshCalibrationData));
  $("repair-data-integrity").addEventListener("click", () => withButtonBusy("repair-data-integrity", "Scanning...", repairDataIntegrity));
  $("auto-paper-calibration").addEventListener("click", () => withButtonBusy("auto-paper-calibration", "Creating...", createAutoPaperCalibrationEntries));
  $("refresh-accuracy-lab").addEventListener("click", () => withButtonBusy("refresh-accuracy-lab", "Checking...", loadAccuracyLab));
  $("preferences-form").addEventListener("submit", savePreferences);
  $("preview-sound").addEventListener("click", () => {
    window.EdgeIQAudio?.save({
      enabled: $("pref-sound-effects").checked,
      volume: Number($("pref-sound-volume").value || 0) / 100,
    });
    playCircuitSound("success");
  });
  $("pref-sound-effects").addEventListener("change", (event) => {
    $("preview-sound").disabled = !event.target.checked;
  });
  $("watchlist-form").addEventListener("submit", saveWatchlistItem);
  $("boost-form").addEventListener("submit", analyzeBoost);
  $("bankroll-strategy-form").addEventListener("submit", saveBankrollStrategy);
  document.querySelectorAll("[data-close-drawer]").forEach((button) => {
    button.addEventListener("click", closeExplanationDrawer);
  });
  $("mobile-slip-toggle").addEventListener("click", toggleMobileSlip);
  $("mobile-analyze-entry").addEventListener("click", () => withButtonBusy("mobile-analyze-entry", "Analyzing...", mobileAnalyzeEntry));
  $("mobile-place-entry").addEventListener("click", mobilePlaceEntry);
  $("mobile-slip-wager").addEventListener("input", () => { $("entry-wager").value = $("mobile-slip-wager").value; });
  $("mobile-slip-multiplier").addEventListener("input", () => { $("entry-multiplier").value = $("mobile-slip-multiplier").value; });
  $("onboarding-form").addEventListener("submit", saveOnboarding);
  $("onboarding-skip").addEventListener("click", skipOnboarding);
  $("onboarding-upload-history").addEventListener("click", openHistoryUploadFromOnboarding);
}

function startLiveEntryPolling() {
  window.setInterval(() => {
    if (document.hidden) return;
    loadEntryProgress({ autoCheck: false, refreshProviders: false, marketDetail: false }).catch((error) => {
      console.warn("Live entry progress polling failed", error);
    });
  }, 60000);
}

async function loadDeferredSignals() {
  const root = document.querySelector('[data-workspace="decision-desk"]');
  const activeTab = root?.querySelector("[data-workspace-tab].active");
  if (root && activeTab) loadWorkspacePaneData(root, activeTab.dataset.workspaceTab);
}

async function loadAll(options = {}) {
  syncDefaultInputs();
  const essentials = await Promise.allSettled([
    loadDashboard(),
    loadEntryProgress({ autoCheck: false, refreshProviders: false, marketDetail: false }),
  ]);
  const failure = essentials.find((result) => result.status === "rejected");
  if (failure) {
    handleLoadError(failure.reason);
    return;
  }
  hideRuntimeNotice();

  if (!state.backgroundLoadPromise) {
    const backgroundTasks = options.refresh
      ? [loadDailyBriefing(), loadDailyScanStatus(), loadRuntimeStatus(), loadDataHealth(), loadNotifications(), loadPerformance(), loadSettlementAudit()]
      : [
          loadModelHealth(), loadDailyBriefing(), loadDailyScanStatus(), loadRuntimeStatus(), loadDataHealth(), loadNotifications(),
        ];
    state.backgroundLoadPromise = Promise.allSettled(backgroundTasks).then((results) => {
      const backgroundFailure = results.find((result) => result.status === "rejected");
      if (backgroundFailure) console.warn("Background EdgeIQ panel refresh failed", backgroundFailure.reason);
    }).finally(() => { state.backgroundLoadPromise = null; });
  }

  if (!state.ledgerLoadScheduled) {
    state.ledgerLoadScheduled = true;
    deferWork(() => {
      Promise.allSettled([
        loadEntryProgress({ autoCheck: true, refreshProviders: false, marketDetail: false }),
      ]).then((results) => {
        const backgroundFailure = results.find((result) => result.status === "rejected");
        if (backgroundFailure) console.warn("Deferred EdgeIQ ledger refresh failed", backgroundFailure.reason);
      });
    }, 2500);
  }

  if (!state.deferredSignalsScheduled) {
    state.deferredSignalsScheduled = true;
    deferWork(() => { loadDeferredSignals(); }, 5000);
  }
}

registerPwa();
bindEvents();
applyViewFromUrl();
showOnboardingIfNeeded();
showInitialSkeletons();
loadAll();
startLiveEntryPolling();
