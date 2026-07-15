const state = {
  entryProps: [],
  lastEntryPayload: null,
  lastAnalysis: null,
  recommendationOrigin: false,
  commandCards: [],
  dailyBriefing: null,
  dailyScanPoll: null,
};

window.EdgeIQLoaded = true;

const $ = (id) => document.getElementById(id);
const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8000" : "";
const deferWork = window.requestIdleCallback
  ? (task, timeout = 1500) => window.requestIdleCallback(task, { timeout })
  : (task, timeout = 1500) => window.setTimeout(task, Math.min(timeout, 800));

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    cache: "no-store",
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json();
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

function friendlyStatus(value) {
  return String(value || "unknown")
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function sortProviderHealth(providers) {
  const rank = {
    missing_key: 0,
    not_configured: 1,
    error: 2,
    degraded: 3,
    connected: 4,
    available: 5,
  };
  return [...(providers || [])].sort((a, b) => {
    const aRank = rank[a.status] ?? 9;
    const bRank = rank[b.status] ?? 9;
    if (aRank !== bRank) return aRank - bRank;
    return String(a.name || "").localeCompare(String(b.name || ""));
  });
}

function sortNotifications(notifications) {
  const rank = { danger: 0, warning: 1, watch: 2, positive: 3, neutral: 4 };
  return [...(notifications || [])].sort((a, b) => {
    const aRank = rank[a.severity] ?? 9;
    const bRank = rank[b.severity] ?? 9;
    if (aRank !== bRank) return aRank - bRank;
    return String(a.type || "").localeCompare(String(b.type || ""));
  });
}

function showRuntimeNotice(message) {
  const notice = $("runtime-notice");
  if (!notice) return;
  notice.textContent = message;
  notice.hidden = false;
}

function hideRuntimeNotice() {
  const notice = $("runtime-notice");
  if (!notice) return;
  notice.hidden = true;
}

function handleLoadError(error) {
  const fileHint = window.location.protocol === "file:"
    ? " The page is open from a file, so start the EdgeIQ server and use http://127.0.0.1:8000 for live data."
    : "";
  showRuntimeNotice(`EdgeIQ could not reach the app server.${fileHint}`);
  $("props-status").textContent = "Waiting for app server...";
  $("dashboard-parlay").textContent = "Start the app server to load recommendations.";
  console.error(error);
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

const DISPLAY_TIME_ZONE = "America/New_York";

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
  if (!date) return value;
  if (Number.isNaN(date.getTime())) return value;
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
  if (!date) return value;
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    timeZone: DISPLAY_TIME_ZONE,
    weekday: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZoneName: "short",
  }).format(date);
}

function propPickText(prop) {
  const direction = prop.direction || "Over";
  return `<span class="prop-pick-text">${directionBadge(direction)} <span>${prop.player} ${prop.stat} ${prop.line}</span></span>`;
}

function propPickList(props) {
  return (props || []).map(propPickText).join(", ");
}

function shortPropPickText(prop) {
  return `<span class="prop-pick-text">${directionBadge(prop.direction || "Over")} <span>${prop.player} ${prop.stat}</span></span>`;
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

function syncDefaultInputs() {
  const defaults = JSON.parse(localStorage.getItem("edgeiq.onboarding") || "{}");
  if (defaults.platform && $("props-platform")) $("props-platform").value = defaults.platform;
  if (defaults.platform && $("entry-platform")) $("entry-platform").value = defaults.platform;
  if (defaults.sport && $("props-sport")) $("props-sport").value = defaults.sport;
  if (defaults.defaultWager && $("entry-wager")) $("entry-wager").value = defaults.defaultWager;
  if (defaults.risk === "conservative" && $("entry-multiplier")) $("entry-multiplier").value = "2";
  if (defaults.risk === "aggressive" && $("entry-multiplier")) $("entry-multiplier").value = "5";
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
  const navButton = document.querySelector(`[data-view="${viewId}"]`);
  if (navButton) navButton.classList.add("active");
  const titles = { dashboard: "Today", performance: "Results", analysis: "Tools", bets: "Bet Ledger" };
  $("view-title").textContent = titles[viewId] || navButton?.textContent || viewId;
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
}

async function startDailyBriefingScan() {
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const params = new URLSearchParams({ platform, sport });
  const scan = await api(`/api/daily-briefing/scan?${params.toString()}`, { method: "POST" });
  renderDailyScanStatus({ current: scan, runs: [] });
  pollDailyScanStatus(true);
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

function renderDailyBriefing(data) {
  const cacheLabel = data.cache?.stale
    ? `expired cache ${formatDateTime(data.cache.created_at)} · refresh recommended`
    : data.cache?.hit
      ? `cached ${formatDateTime(data.cache.created_at)}`
      : "fresh scan";
  $("daily-briefing-status").textContent = `${data.headline} · ${data.sport} · ${cacheLabel}`;
  const health = data.summary?.model_health || {};
  const slate = data.summary?.slate || [];
  const opportunities = data.top_opportunities || [];
  const suggestedEntries = data.suggested_entries || [];
  const gamesToday = data.games_today || [];
  const providerBadges = data.provider_badges || [];
  const ev = Number(data.summary?.expected_value || 0);
  if ($("daily-greeting")) $("daily-greeting").textContent = data.user?.greeting || "Good Morning Joshua.";
  $("daily-briefing-summary").classList.remove("muted-card");
  $("daily-briefing-summary").innerHTML = `
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
      <div class="briefing-market-section opportunities-section">
        <div class="briefing-section-title">Top Opportunities</div>
        <div class="opportunity-list">
          ${opportunities.slice(0, 3).map((prop, index) => `
            <button class="opportunity-row" data-load-opportunity="${index}">
              <span class="stars">${escapeHtml(prop.stars || "★★★☆☆")}</span>
              <strong>${escapeHtml(prop.player)} ${escapeHtml(prop.direction || "Over")} ${escapeHtml(prop.line ?? "")} ${escapeHtml(prop.stat || "")}</strong>
              <em>${Number(prop.confidence || prop.score || 0).toFixed(0)}%</em>
            </button>
          `).join("") || `<div class="suggestion compact-suggestion">No top opportunities cleared the current filter.</div>`}
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
    <div class="briefing-metric-row">
      <span>Bankroll ${money(data.summary?.bankroll)}</span>
      <span>Month ${money(data.summary?.monthly_profit)} · ${pct(data.summary?.monthly_roi)}</span>
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
}

function renderDailyGame(game, index) {
  const best = game.best_prop || {};
  const matchup = game.matchup_label || game.game || "Matchup TBD";
  return `
    <details class="daily-game-card">
      <summary>
        <div>
          <span class="pill">${escapeHtml(game.sport || "Game")}</span>
          <strong>${escapeHtml(matchup)}</strong>
          <small>${Number(game.prop_count || 0)} props · AI ${Number(game.ai_score || 0).toFixed(0)} · ${pct(game.probability || 0)}</small>
        </div>
        <button class="secondary" type="button" data-generate-game-entry="${index}">Generate Entry</button>
      </summary>
      <div class="daily-game-grid">
        ${renderGameMetric("Projected Winner", game.projected_winner)}
        ${renderGameMetric("Team Pace", game.team_pace)}
        ${renderGameMetric("Injuries", game.injuries)}
        ${renderGameMetric("Best Prop", propLabel(game.best_prop))}
        ${renderGameMetric("Best Value Prop", propLabel(game.best_value_prop))}
        ${renderGameMetric("Highest Confidence", propLabel(game.highest_confidence))}
        ${renderGameMetric("Fade Candidate", propLabel(game.fade_candidate))}
        ${renderGameMetric("Vegas Line", game.vegas_line)}
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
    return `
      <div class="briefing-card ${card.grade ? gradeClass(card.grade) : ""}" data-briefing-card="${elementId}:${index}">
        <div class="suggestion-top">
          <span class="pill">${escapeHtml(card.title || "Card")}</span>
          <strong>${escapeHtml(card.grade || card.type || "")}${card.score ? ` · ${Number(card.score || 0).toFixed(1)}` : ""}</strong>
        </div>
        <h3>${escapeHtml(card.action || card.summary || "Review")}</h3>
        <p>${escapeHtml(card.reason || card.summary || "")}</p>
        ${props.length ? `
          <div class="command-leg-list">
            ${props.slice(0, 4).map((prop) => `<span>${shortPropPickText(prop)} <b>${escapeHtml(prop.line ?? "")}</b></span>`).join("")}
          </div>
        ` : ""}
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
        </div>
      </div>
    `;
  }).join("") || `<div class="suggestion compact-suggestion">${emptyMessage}</div>`;
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
}

function bindDailyBriefingSummaryActions() {
  document.querySelectorAll("[data-load-opportunity]").forEach((button) => {
    button.addEventListener("click", () => {
      const opportunity = state.dailyBriefing?.top_opportunities?.[Number(button.dataset.loadOpportunity)];
      if (!opportunity) return;
      renderEntryPropsFromAnalyzed([{
        player: opportunity.player,
        team: "",
        sport: opportunity.sport,
        stat: opportunity.stat,
        line: opportunity.line,
        projection: null,
        direction: opportunity.direction || "Over",
        platform: opportunity.platform || state.dailyBriefing.platform,
        game: "",
        game_time: "",
        season_type: "",
        trending_count: 0,
      }]);
      state.recommendationOrigin = true;
      setView("entries");
      $("entry-status").textContent = "Loaded top opportunity. Add another prop before analyzing.";
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

function handleDailyBriefingAction(card) {
  if (!card) return;
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
  $("command-center-status").textContent = `${data.cards.length} release-ready recommendations · ${data.sport}`;
  $("command-center-list").innerHTML = data.cards.map((card, index) => `
    <div class="command-card ${gradeClass(card.grade)}">
      <div class="suggestion-top">
        <span class="pill">${card.title}</span>
        <strong>${card.grade} · ${card.score}</strong>
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
      <span class="subtle">${health.settled_entries} settled entries · ${health.calibrated_picks} calibrated picks</span>
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

async function loadDataHealth() {
  const data = await api("/api/data-health");
  const providers = sortProviderHealth(data.providers);
  $("data-health-list").innerHTML = `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${data.summary.connected}/${data.summary.total} sources available</strong>
        <span class="status-pill ${data.summary.warnings ? "status-warning" : "status-connected"}">${data.summary.warnings} warnings</span>
      </div>
      <p>${data.summary.last_daily_refresh ? `Last refresh ${formatDateTime(data.summary.last_daily_refresh)}` : "No scheduled refresh run recorded yet."}</p>
    </div>
    ${providers.map((provider) => `
      <div class="suggestion compact-suggestion health-${provider.status}">
        <div class="suggestion-top">
          <strong>${provider.name}</strong>
          <span class="status-pill status-${provider.status}">${friendlyStatus(provider.status)}</span>
        </div>
        <p>${provider.purpose} · ${provider.message}</p>
      </div>
    `).join("")}
  `;
}

async function loadNotifications() {
  const data = await api("/api/notifications");
  const notifications = sortNotifications(data.notifications);
  $("notification-list").innerHTML = notifications.map((note) => `
    <div class="suggestion compact-suggestion notification-${note.severity || "neutral"}">
      <div class="suggestion-top">
        <strong>${note.title}</strong>
        <span class="status-pill status-${note.severity || "neutral"}">${friendlyStatus(note.type)}</span>
      </div>
      <p>${note.message}</p>
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
  $("advantage-center-status").textContent = top
    ? `${data.competitive_features.length} competitive features active · ${data.sport}`
    : "Advantage Center is active, but no top recommendation is available for this board.";
  $("advantage-center-list").innerHTML = `
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
      <p>${Number(data.closing_line_value?.positive_clv_rate || 0).toFixed(1)}% positive CLV · Avg ${Number(data.closing_line_value?.average_clv || 0).toFixed(2)}</p>
      <p class="subtle">${data.closing_line_value?.tracked_legs || 0} tracked legs</p>
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
  $("watchlist-list").innerHTML = (data.watchlist_alerts || []).map((alert) => `
    <div class="suggestion compact-suggestion">
      <strong>${alert.player} · ${alert.direction} ${alert.stat}</strong>
      <p>${alert.platform} ${alert.line} · ${alert.reason}</p>
    </div>
  `).join("") || `<div class="suggestion compact-suggestion">No watchlist alerts yet.</div>`;
  loadBankrollStrategyFields(data.bankroll_strategy || {});
}

function loadBankrollStrategyFields(strategy) {
  if (!strategy || !$("strategy-mode")) return;
  $("strategy-mode").value = strategy.mode || "balanced";
  $("strategy-unit").value = strategy.unit_size ?? 10;
  $("strategy-max-pct").value = strategy.max_wager_pct ?? 5;
  $("strategy-paper-first").checked = Boolean(strategy.paper_first);
  $("bankroll-strategy-status").textContent = `${strategy.mode || "balanced"} sizing is active.`;
}

async function saveBankrollStrategy(event) {
  event.preventDefault();
  const payload = {
    mode: $("strategy-mode").value,
    unit_size: Number($("strategy-unit").value || 10),
    max_wager_pct: Number($("strategy-max-pct").value || 5),
    paper_first: $("strategy-paper-first").checked,
  };
  const data = await api("/api/settings/bankroll-strategy", { method: "POST", body: JSON.stringify(payload) });
  loadBankrollStrategyFields(data.strategy);
  await loadAdvantageCenter();
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
    min_confidence: $("timing-min-confidence")?.value || "0",
    min_ev: $("timing-min-ev")?.value || "-25",
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
  if (options.autoCheck !== false) params.set("auto_check", "true");
  if (options.refreshProviders !== false) params.set("refresh_providers", "true");
  if (options.marketDetail === false) params.set("market_detail", "false");
  const query = params.toString();
  const data = await api(`/api/entries/progress${query ? `?${query}` : ""}`);
  const settled = data.auto_check && data.auto_check.settled ? ` · settled ${data.auto_check.settled}` : "";
  const liveSync = data.live_stats_sync || {};
  const liveDetail = liveSync.skipped
    ? ""
    : ` · ESPN fetched ${liveSync.fetched_rows || 0}, saved ${liveSync.imported || 0}`;
  $("entry-progress-status").textContent = data.active
    ? `${data.active} active entries · ${data.with_live_stats} with live stat data${settled}${liveDetail}`
    : data.auto_check && data.auto_check.settled
      ? `No active placed entries · settled ${data.auto_check.settled}${liveDetail}`
      : "No active placed entries.";
  $("entry-progress-list").innerHTML = data.entries.map((entry) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <span class="pill">#${entry.id}</span>
        <strong class="${entry.live_result === "Loss" ? "danger-text" : ""}">${entry.tracker_status || entry.live_result}</strong>
        <span class="pill">${formatGameTime(entry.next_game_time_label)}</span>
        <span class="subtle">${entry.completed_legs}/${entry.total_legs} final · ${entry.source}</span>
      </div>
      <p>Confidence ${pct(entry.average_confidence)} · Edge ${Number(entry.average_edge).toFixed(2)} · Projected ${entry.projected_result} · ${formatDateTime(entry.placed_at)}</p>
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
    loadDashboardParlay(platform, sport),
    loadTrendingGames(platform, sport),
    loadDailyBriefing(),
    loadCommandCenter(),
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
      <td>${directionBadge(prop.direction || "Over")}</td>
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
  $("ai-parlay-status").textContent = data.ai_enabled
    ? `OpenAI assisted · ${data.model}`
    : `EdgeIQ Local · ${data.model} · ${data.request?.risk_profile || "balanced"} · ${data.request?.sport_label || "All Sports"} · ${data.request?.leg_count || 3} legs`;
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
        </div>
        <button class="secondary" data-load-ai-suggestion="0">Load</button>
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
            ${escapeHtml(candidate.grade || "-")} · ${escapeHtml(candidate.leg_count)} legs · ${escapeHtml((candidate.entry?.props || []).map((prop) => prop.player).join(", "))}
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

async function loadDashboardParlay(platform = $("props-platform").value, sport = $("props-sport").value) {
  const data = await api(`/api/dashboard/parlay?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}`);
  renderDashboardParlay(data.suggestion);
}

function renderDashboardParlay(suggestion) {
  const parlayCard = $("dashboard-parlay");
  parlayCard.classList.remove("grade-a", "grade-b", "grade-c", "grade-d", "grade-f", "grade-unknown", "recommendation-card");
  if (!suggestion) {
    parlayCard.classList.add("muted-card");
    parlayCard.innerHTML = "No 3-leg parlay is available for the current filters.";
    return;
  }

  parlayCard.classList.remove("muted-card");
  parlayCard.classList.add("recommendation-card", gradeClass(suggestion.grade));
  parlayCard.innerHTML = `
    <div class="suggestion-top">
      <div>
        <span class="pill">3 Leg</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
      </div>
      <span class="subtle">Score ${suggestion.score}</span>
    </div>
    <p>${propPickList(suggestion.entry.props)}</p>
    ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
    <div class="button-row">
      <button class="secondary" id="load-dashboard-parlay">Load Parlay</button>
      <button class="secondary" id="explain-dashboard-parlay">Why?</button>
    </div>
  `;
  $("load-dashboard-parlay").addEventListener("click", () => {
    renderEntryPropsFromAnalyzed(suggestion.entry.props);
    state.recommendationOrigin = true;
    setView("entries");
    $("entry-status").textContent = "Loaded recommended 3-leg parlay. Analyze/place when ready.";
  });
  $("explain-dashboard-parlay").addEventListener("click", () => openExplanationDrawer(suggestionExplanation(suggestion, "Best 3-Leg")));
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

function formatMovement(movement) {
  if (!movement || movement.previous == null) return "flat";
  const prefix = movement.change > 0 ? "+" : "";
  return `${movement.direction} ${prefix}${Number(movement.change).toFixed(1)}`;
}

function addFeedProp(prop) {
  state.entryProps.push({
    player: prop.player,
    team: prop.team || "",
    sport: prop.league || "WNBA",
    stat: prop.stat || "Points",
    line: Number(prop.line || 0),
    projection: null,
    direction: prop.direction || "Over",
    platform: prop.platform || $("entry-platform").value,
    game: prop.game || "",
    game_time: prop.game_time || "",
    season_type: prop.season_type || prop.seasonType || "",
    trending_count: Number(prop.trending_count || 0),
  });
  renderEntryProps();
  setView("entries");
  $("entry-status").textContent = `${prop.player} added. Projection will auto-fill unless you enter one.`;
}

function renderEntryProps() {
  $("entry-props").innerHTML = state.entryProps.map((prop, index) => {
    const projection = prop.projection == null ? "Auto" : Number(prop.projection).toFixed(1);
    const edge = prop.projection == null ? "Auto" : (Number(prop.projection) - Number(prop.line)).toFixed(1);
    return `
      <tr>
        <td>${prop.player}</td>
        <td>${directionBadge(prop.direction || "Over")}</td>
        <td>${prop.stat}</td>
        <td>${prop.line}</td>
        <td>${projection}</td>
        <td>${edge}</td>
        <td><button class="danger" data-remove-prop="${index}">Remove</button></td>
      </tr>
    `;
  }).join("");
  document.querySelectorAll("[data-remove-prop]").forEach((button) => {
    button.addEventListener("click", () => {
      state.entryProps.splice(Number(button.dataset.removeProp), 1);
      state.lastEntryPayload = null;
      $("ai-review-entry").disabled = true;
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
  return {
    platform: $("entry-platform").value,
    wager: entryMode === "paper" ? 0 : Number($("entry-wager").value || 0),
    multiplier: Number($("entry-multiplier").value || 1),
    entry_mode: entryMode,
    recommended_by_app: state.recommendationOrigin || Boolean(state.lastAnalysis && state.lastAnalysis.recommendation && state.lastAnalysis.recommendation.grade !== "F"),
    props: state.entryProps,
  };
}

function renderAnalysis(data) {
  const rec = data.recommendation;
  const risk = data.risk;
  const components = rec.components || {};
  const warnings = data.warnings || [];
  const espn = data.espn_context || {};
  const fusion = data.source_fusion || {};
  const guardrails = data.risk_guardrails || [];
  const checklist = data.confirmation_checklist || [];
  const espnRows = (data.entry.props || [])
    .filter((prop) => prop.espn && prop.espn.sample_size)
    .map((prop) => `
      <div class="suggestion compact-suggestion">
        <strong>${propPickText(prop)}</strong>
        <p>${Number(prop.espn.hit_rate || 0).toFixed(1)}% hit · ${prop.espn.sample_size} ESPN games · Recent avg ${prop.espn.recent_average ?? "-"}</p>
        <p class="subtle">${prop.projection_source === "espn_recent_form" ? "Projection adjusted with ESPN recent form" : "Projection reviewed against ESPN history"} · Confidence ${prop.espn.confidence_adjustment >= 0 ? "+" : ""}${Number(prop.espn.confidence_adjustment || 0).toFixed(1)}</p>
      </div>
    `).join("");
  const signalRows = (data.entry.props || [])
    .flatMap((prop) => (prop.source_signals || []).map((signal) => ({ prop, signal })))
    .map(({ prop, signal }) => `
      <div class="suggestion compact-suggestion">
        <strong>${signal.source} · ${prop.player}</strong>
        <p>${signal.message}</p>
        <p class="subtle">Projection ${signal.projection_delta >= 0 ? "+" : ""}${Number(signal.projection_delta || 0).toFixed(2)} · Confidence ${signal.confidence_delta >= 0 ? "+" : ""}${Number(signal.confidence_delta || 0).toFixed(1)}</p>
      </div>
    `).join("");
  const qualityRows = (data.entry.props || []).map((prop) => `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${prop.player}</strong>
        <span class="subtle">${prop.data_quality?.label || "unscored"} · ${Number(prop.data_quality?.score || 0).toFixed(0)}/100</span>
      </div>
      <p>${(prop.data_quality?.flags || []).join(" · ") || "No major data-quality warnings."}</p>
    </div>
  `).join("");
  $("entry-analysis").classList.remove("muted-card");
  $("entry-analysis").innerHTML = `
    <div class="grade">${rec.grade}</div>
    <h2>${rec.action}</h2>
    <p>${rec.reason}</p>
    <div class="stats-grid" style="margin-top:14px">
      <div class="stat-card"><div class="stat-value">${Number(rec.score ?? 0).toFixed(1)}</div><div class="stat-label">Entry Score</div></div>
      <div class="stat-card"><div class="stat-value">${pct(risk.average_confidence)}</div><div class="stat-label">Avg Confidence</div></div>
      <div class="stat-card"><div class="stat-value">${Number(risk.average_edge).toFixed(2)}</div><div class="stat-label">Avg Edge</div></div>
      <div class="stat-card"><div class="stat-value">${risk.level}</div><div class="stat-label">Risk</div></div>
    </div>
    <p class="subtle">Score blend: confidence ${pct(components.average_confidence)} · edge ${Number(components.average_edge || 0).toFixed(2)} · source support ${Number(components.average_source_score || 0).toFixed(1)}</p>
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
}

async function analyzeEntry() {
  if (state.entryProps.length < 2) {
    $("entry-status").textContent = "Add at least two props.";
    return;
  }
  const payload = entryPayload();
  const data = await api("/api/entries/analyze", { method: "POST", body: JSON.stringify(payload) });
  state.lastEntryPayload = payload;
  state.lastAnalysis = data;
  state.recommendationOrigin = data.recommendation && data.recommendation.grade !== "F";
  renderAnalysis(data);
  renderEntryPropsFromAnalyzed(data.entry.props);
  $("ai-review-entry").disabled = false;
  $("place-entry").disabled = false;
  $("entry-status").textContent = "Entry analyzed. Review before placing.";
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
      <p class="subtle">${data.ai_enabled ? `OpenAI assisted · ${data.model}` : `EdgeIQ Local review${data.ai_error ? ` · ${data.ai_error}` : ""}`}</p>
      <p>${data.review}</p>
    </div>
  `;
  $("entry-status").textContent = data.ai_enabled ? "AI review complete." : "EdgeIQ Local review complete.";
}

function renderEntryPropsFromAnalyzed(props) {
  state.entryProps = props.map((prop) => ({
    player: prop.player,
    team: prop.team,
    sport: prop.sport,
    stat: prop.stat,
    line: prop.line,
    projection: prop.projection,
    direction: prop.direction || "Over",
    platform: prop.platform,
    game: prop.game,
    game_time: prop.game_time || "",
    season_type: prop.season_type || "",
    trending_count: prop.trending_count,
  }));
  renderEntryProps();
}

async function placeEntry() {
  if (!state.lastEntryPayload) return;
  state.lastEntryPayload.entry_mode = $("entry-mode")?.value || state.lastEntryPayload.entry_mode || "real";
  state.lastEntryPayload.wager = state.lastEntryPayload.entry_mode === "paper" ? 0 : Number($("entry-wager").value || state.lastEntryPayload.wager || 0);
  state.lastEntryPayload.multiplier = Number($("entry-multiplier").value || state.lastEntryPayload.multiplier || 1);
  if (state.lastEntryPayload.entry_mode !== "paper" && state.lastEntryPayload.wager <= 0) {
    $("entry-status").textContent = "Enter the amount wagered before placing.";
    return;
  }
  let placementCheck;
  try {
    placementCheck = await api("/api/entries/placement-check", { method: "POST", body: JSON.stringify(state.lastEntryPayload) });
  } catch (error) {
    $("entry-status").textContent = `Provider check failed: ${error.message}`;
    return;
  }
  if (!placementCheck.ok) {
    $("entry-status").textContent = placementCheck.blocks?.[0] || "Provider check blocked this entry.";
    return;
  }
  const checkWarnings = [...(placementCheck.blocks || []), ...(placementCheck.warnings || [])];
  const checkText = checkWarnings.length
    ? `\n\nProvider check:\n${checkWarnings.slice(0, 6).map((warning) => `- ${warning}`).join("\n")}${checkWarnings.length > 6 ? "\n- More warnings hidden." : ""}`
    : "\n\nProvider check passed: current lines and available game times were reviewed.";
  const confirmed = window.confirm(
    (state.lastEntryPayload.entry_mode === "paper" ? "Save this as a paper entry for calibration?" : "Will you place this entry?")
    + checkText
  );
  if (!confirmed) return;
  let data;
  try {
    data = await api("/api/entries/place", { method: "POST", body: JSON.stringify(state.lastEntryPayload) });
  } catch (error) {
    $("entry-status").textContent = error.message;
    return;
  }
  $("entry-status").textContent = state.lastEntryPayload.entry_mode === "paper"
    ? `Paper entry #${data.id} saved for calibration.`
    : `Entry #${data.id} saved as pending. Bankroll reserved ${money(state.lastEntryPayload.wager)}.`;
  state.entryProps = [];
  state.lastEntryPayload = null;
  state.lastAnalysis = null;
  state.recommendationOrigin = false;
  $("place-entry").disabled = true;
  renderEntryProps();
  await loadPending();
  await loadDashboard();
  await loadCommandCenter();
}

async function loadSuggestions() {
  $("suggestions-list").innerHTML = `<div class="suggestion">Generating...</div>`;
  const sport = $("suggest-sport").value;
  const platform = $("suggest-platform").value;
  const data = await api(`/api/entries/suggestions?sport=${encodeURIComponent(sport)}&platform=${encodeURIComponent(platform)}`);
  $("suggestions-list").innerHTML = data.suggestions.map((suggestion, index) => `
    <div class="suggestion ${gradeClass(suggestion.grade)}">
      <div class="suggestion-top">
        <span class="pill">#${suggestion.rank} · ${suggestion.leg_count} Legs</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
        <span class="subtle">${suggestion.risk_tier || "Standard"} · Score ${suggestion.score}</span>
      </div>
      <p>${propPickList(suggestion.entry.props)}</p>
      ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
      <div class="button-row">
        <button class="secondary" data-load-suggestion="${index}">Load Suggestion</button>
        <button class="secondary" data-explain-suggestion="${index}">Why?</button>
      </div>
    </div>
  `).join("") || `<div class="suggestion">No suggestions available.</div>`;
  document.querySelectorAll("[data-load-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.loadSuggestion)];
      renderEntryPropsFromAnalyzed(suggestion.entry.props);
      state.recommendationOrigin = true;
      $("entry-status").textContent = `Loaded ${suggestion.leg_count}-leg ${suggestion.risk_tier || "standard"} suggestion #${suggestion.rank}. Analyze/place when ready.`;
    });
  });
  document.querySelectorAll("[data-explain-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.explainSuggestion)];
      openExplanationDrawer(suggestionExplanation(suggestion, `Suggestion #${suggestion.rank}`));
    });
  });
}

async function loadConfirmedProps() {
  $("confirmed-props-list").innerHTML = `<div class="suggestion">Confirming provider lines...</div>`;
  $("confirmed-entries-list").innerHTML = "";
  const sport = $("confirmed-sport").value;
  const platform = $("confirmed-platform").value;
  const data = await api(`/api/props/confirmed?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}&limit=20`);
  $("confirmed-props-status").textContent = `${data.count} confirmed props · ${data.rejected_count} excluded by data checks · ${data.platform} ${data.sport}`;
  $("confirmed-props-list").innerHTML = data.props.map((prop, index) => `
    <div class="suggestion ${gradeClass(prop.confidence >= 65 ? "A" : prop.confidence >= 58 ? "B" : "C")}">
      <div class="suggestion-top">
        <span class="pill">Confirmed ${prop.confirmed_score}</span>
        <strong>${propPickText(prop)}</strong>
        <span class="subtle">${prop.platform} · ${formatGameTime(prop.game_time)}</span>
      </div>
      <div class="metric-strip">
        <span>Conf ${pct(prop.confidence)}</span>
        <span>Edge ${Number(prop.edge || 0).toFixed(2)}</span>
        <span>${prop.confirmation.history_label}</span>
        <span>${prop.confirmation.quality_label}</span>
      </div>
      ${prop.confirmation.quality_flags?.length ? `<p class="warning">${prop.confirmation.quality_flags.join(" · ")}</p>` : ""}
      <div class="button-row">
        <button class="secondary" data-load-confirmed-prop="${index}">Load Prop</button>
      </div>
    </div>
  `).join("") || `<div class="suggestion">No fully confirmed props for this filter yet.</div>`;
  document.querySelectorAll("[data-load-confirmed-prop]").forEach((button) => {
    button.addEventListener("click", () => {
      addFeedProp(data.props[Number(button.dataset.loadConfirmedProp)]);
      state.recommendationOrigin = true;
      $("entry-status").textContent = "Loaded confirmed prop. Analyze/place when ready.";
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
      <p>${propPickList(suggestion.entry.props)}</p>
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

async function runOptimizer() {
  $("optimizer-list").innerHTML = `<div class="suggestion">Optimizing slips...</div>`;
  const [minLegs, maxLegs] = $("optimizer-legs").value.split("-").map(Number);
  const platform = $("optimizer-platform").value;
  const sport = $("optimizer-sport").value;
  const params = new URLSearchParams({
    platform,
    sport,
    min_legs: minLegs,
    max_legs: maxLegs,
    min_confidence: $("optimizer-min-confidence").value || "0",
    min_edge: $("optimizer-min-edge").value || "-999",
    max_same_team: $("optimizer-max-same-team").value || "5",
    exclude_correlated: $("optimizer-exclude-correlated").checked ? "true" : "false",
    apply_feedback: $("optimizer-apply-feedback").checked ? "true" : "false",
  });
  const data = await api(`/api/entries/optimizer?${params.toString()}`);
  $("optimizer-list").innerHTML = data.suggestions.map((suggestion, index) => `
    <div class="suggestion ${gradeClass(suggestion.grade)}">
      <div class="suggestion-top">
        <span class="pill">#${suggestion.rank} · ${suggestion.leg_count} Legs</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
        <span class="subtle">Score ${suggestion.score}</span>
      </div>
      <p>${propPickList(suggestion.entry.props)}</p>
      ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
      <div class="button-row">
        <button class="secondary" data-load-optimized="${index}">Load Slip</button>
        <button class="secondary" data-explain-optimized="${index}">Why?</button>
      </div>
    </div>
  `).join("") || `<div class="suggestion">No optimized slips available.</div>`;
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
        <input id="dnp-legs-${entry.id}" type="number" min="0" max="${maxDnp}" step="1" value="0" placeholder="DNP legs" />
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
      <span class="subtle">${data.lines.length} books</span>
    </div>
    <div class="stats-grid" style="margin-top:14px">
      <div class="stat-card"><div class="stat-value">${data.best_over.platform}</div><div class="stat-label">Best Over ${data.best_over.line}</div></div>
      <div class="stat-card"><div class="stat-value">${data.best_under.platform}</div><div class="stat-label">Best Under ${data.best_under.line}</div></div>
      <div class="stat-card"><div class="stat-value">${data.consensus_line}</div><div class="stat-label">Consensus Line</div></div>
      <div class="stat-card"><div class="stat-value">${data.line_spread}</div><div class="stat-label">Line Spread</div></div>
    </div>
    <p>${data.value_note}</p>
    ${data.no_vig ? `<p>No-vig fair price: Over ${pct(data.no_vig.over_probability)} (${data.no_vig.over_fair_odds}) · Under ${pct(data.no_vig.under_probability)} (${data.no_vig.under_fair_odds}) · Hold ${pct(data.no_vig.hold)}</p>` : `<p class="subtle">Add over and under odds to calculate a no-vig fair price.</p>`}
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
      <p>${prop.sport} · ${directionBadge(prop.direction || "Over")} ${prop.stat} ${prop.line} · Projection ${prop.projection} · Hit ${pct(prop.estimated_probability)}</p>
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
    </div>
    ${data.entries.slice(0, 8).map((entry) => `
      <div class="suggestion compact-suggestion">
        <div class="suggestion-top">
          <strong>Entry #${entry.id}</strong>
          <span class="subtle">${entry.status} ${entry.result || ""}</span>
        </div>
        <p>Avg CLV ${Number(entry.average_clv).toFixed(2)} · ${entry.positive_legs}/${entry.legs.length} positive legs</p>
      </div>
    `).join("") || `<div class="suggestion">No CLV data yet.</div>`}
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
  const rows = props.map((prop) => `
    <tr>
      <td>${prop.player}</td>
      <td>${prop.sport}</td>
      <td>${directionBadge(prop.direction || "Over")} ${prop.stat}</td>
      <td>${prop.line}</td>
      <td>${prop.platform || ""}</td>
    </tr>
  `).join("");
  $("upload-result").classList.remove("muted-card");
  $("upload-result").innerHTML = `
    <h2>${data.prop_count ?? data.imported ?? 0}</h2>
    <p>${data.message}</p>
    ${data.ai_enabled === false ? `<p class="warning">Add OPENAI_API_KEY to .env to analyze screenshots.</p>` : ""}
    ${props.length ? `
      <div class="table-wrap compact">
        <table>
          <thead><tr><th>Player</th><th>Sport</th><th>Stat</th><th>Line</th><th>Platform</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <button class="secondary" id="load-upload-props">Load Props Into Entry</button>
    ` : ""}
  `;
  if (props.length) {
    $("load-upload-props").addEventListener("click", () => {
      renderEntryPropsFromAnalyzed(props);
      setView("entries");
      $("entry-status").textContent = `Loaded ${props.length} uploaded props. Analyze before placing.`;
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
  const data = await api("/api/bets");
  const entries = data.entries || [];
  $("bets-status").textContent = `${data.bets.length} saved bets · ${entries.length} completed entries`;
  $("bets-table").innerHTML = data.bets.map((bet) => `
    <tr>
      <td>${bet.sport}</td>
      <td>${bet.game}</td>
      <td>${bet.description}</td>
      <td>${bet.source === "edgeiq_entry" ? `EdgeIQ #${bet.source_entry_id || ""}${bet.entry_mode === "paper" ? " · Paper" : ""}` : bet.source || "Manual"}</td>
      <td>${bet.result}</td>
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
          <strong>${entry.platform} · ${entry.result}</strong>
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
  const source = prop.source === "projection_estimate"
    ? "Projection estimate"
    : prop.source === "unmatched"
      ? "No source matched"
      : friendlyStatus(prop.source);
  return `
    <div class="entry-leg-row">
      <div>
        <strong>${prop.player}</strong>
        <span>${prop.team || prop.game || prop.sport || ""}</span>
      </div>
      <div>
        <span>${directionBadge(prop.direction || "Over")} ${prop.stat}</span>
        <strong>${prop.line}</strong>
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
        <span>${source}</span>
        <strong class="${resultClass}">${prop.result || "Pending"}</strong>
      </div>
    </div>
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
  $("upload-target").value = "bet_history";
  $("upload-file").focus();
}

function openScreenshotImport() {
  setView("analysis");
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
  await placeEntry();
  $("mobile-slip-panel").hidden = true;
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
  await loadBacktest();
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
  $("backtest-summary").innerHTML = `
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
      <p class="subtle">SportsDataIO and ESPN final stats strengthen the leg-level samples behind calibration.</p>
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
  $("entry-status").textContent = "Refreshing provider stats for calibration...";
  const data = await api("/api/analytics/refresh-calibration-data", { method: "POST" });
  $("entry-status").textContent = `Calibration refreshed: ${data.provider_refresh.imported || 0} stat rows saved, ${data.backfill.provider_rows || 0} provider leg results linked.`;
  await Promise.allSettled([loadBacktest(), loadPerformance(), loadAccuracyLab(), loadDataHealth(), loadNotifications()]);
}

async function createAutoPaperCalibrationEntries() {
  const sport = $("auto-paper-sport")?.value || "All Sports";
  const platform = $("auto-paper-platform")?.value || "PrizePicks";
  const legCount = Number($("auto-paper-leg-count")?.value || 2);
  const maxEntries = Math.max(1, Math.min(10, Number($("auto-paper-max-entries")?.value || 3)));
  $("auto-paper-calibration-status").textContent = `Creating ${sport} paper-only calibration samples...`;
  const data = await api("/api/entries/auto-paper-calibration", {
    method: "POST",
    body: JSON.stringify({
      platform,
      sport,
      leg_count: legCount,
      max_entries: maxEntries,
      prefer_confirmed: false,
      dry_run: false,
    }),
  });
  const skippedText = (data.skipped || []).slice(0, 2).map((row) => escapeHtml(row.reason || "")).filter(Boolean).join(" ");
  $("auto-paper-calibration-status").innerHTML = `
    Created ${data.created_count} ${escapeHtml(sport)} paper calibration entr${data.created_count === 1 ? "y" : "ies"}.
    ${(data.created || []).slice(0, 3).map((row) => `
      <span class="status-pill status-paper">${escapeHtml(row.target?.type || "Target")}: ${escapeHtml(row.target?.name || "")}</span>
    `).join("") || (skippedText ? `<span class="subtle">${skippedText}</span>` : "")}
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
        <span><strong>${pct(segment.win_rate)}</strong><small>Win Rate</small></span>
        <span><strong>${money(segment.profit)}</strong><small>Profit</small></span>
        <span><strong>${pct(segment.roi)}</strong><small>ROI</small></span>
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
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  document.querySelectorAll("[data-view-shortcut]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.viewShortcut));
  });
  $("refresh-all").addEventListener("click", () => withButtonBusy("refresh-all", "Refreshing...", loadAll));
  $("refresh-daily-briefing").addEventListener("click", () => withButtonBusy("refresh-daily-briefing", "Scanning...", startDailyBriefingScan));
  $("refresh-command-center").addEventListener("click", () => withButtonBusy("refresh-command-center", "Checking...", loadCommandCenter));
  $("refresh-advantage-center").addEventListener("click", () => withButtonBusy("refresh-advantage-center", "Checking...", loadAdvantageCenter));
  $("refresh-data-health").addEventListener("click", () => withButtonBusy("refresh-data-health", "Checking...", loadDataHealth));
  $("refresh-notifications").addEventListener("click", () => withButtonBusy("refresh-notifications", "Checking...", loadNotifications));
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
    state.entryProps.push(prop);
    $("prop-form").reset();
    renderEntryProps();
  });
  $("analyze-entry").addEventListener("click", () => withButtonBusy("analyze-entry", "Analyzing...", analyzeEntry));
  $("ai-review-entry").addEventListener("click", reviewEntryWithAi);
  $("place-entry").addEventListener("click", placeEntry);
  $("clear-entry").addEventListener("click", () => {
    state.entryProps = [];
    state.lastEntryPayload = null;
    state.lastAnalysis = null;
    state.recommendationOrigin = false;
    $("ai-review-entry").disabled = true;
    $("place-entry").disabled = true;
    renderEntryProps();
  });
  $("load-confirmed-props").addEventListener("click", () => withButtonBusy("load-confirmed-props", "Confirming...", loadConfirmedProps));
  $("generate-confirmed-entries").addEventListener("click", () => withButtonBusy("generate-confirmed-entries", "Building...", loadConfirmedEntries));
  $("generate-suggestions").addEventListener("click", () => withButtonBusy("generate-suggestions", "Building...", loadSuggestions));
  $("run-optimizer").addEventListener("click", () => withButtonBusy("run-optimizer", "Optimizing...", runOptimizer));
  $("refresh-pending").addEventListener("click", () => withButtonBusy("refresh-pending", "Checking...", loadPending));
  $("classify-default-wagers").addEventListener("click", () => withButtonBusy("classify-default-wagers", "Classifying...", classifyDefaultWagers));
  $("save-dnp-handling").addEventListener("click", saveDnpSetting);
  $("auto-check-entries").addEventListener("click", () => withButtonBusy("auto-check-entries", "Checking...", autoCheckEntries));
  $("expedite-entries").addEventListener("click", () => withButtonBusy("expedite-entries", "Clearing...", expediteEntries));
  $("line-shop-form").addEventListener("submit", shopLines);
  $("ev-scanner-form").addEventListener("submit", runEvScanner);
  $("load-clv").addEventListener("click", loadClvReport);
  $("ev-form").addEventListener("submit", calculateEv);
  $("line-movement-form").addEventListener("submit", loadLineMovement);
  $("hit-rate-form").addEventListener("submit", estimateHitRate);
  $("projection-assist-form").addEventListener("submit", assistProjection);
  $("final-stats-form").addEventListener("submit", importFinalStats);
  $("upload-analyzer-form").addEventListener("submit", analyzeUpload);
  $("bet-history-form").addEventListener("submit", importBetHistory);
  $("open-screenshot-import").addEventListener("click", openScreenshotImport);
  $("bet-form").addEventListener("submit", saveBet);
  $("bankroll-transaction-form").addEventListener("submit", saveBankrollTransaction);
  $("refresh-bets").addEventListener("click", () => withButtonBusy("refresh-bets", "Checking...", loadBets));
  $("refresh-backtest").addEventListener("click", () => withButtonBusy("refresh-backtest", "Refreshing...", loadBacktest));
  $("refresh-calibration-data").addEventListener("click", () => withButtonBusy("refresh-calibration-data", "Refreshing...", refreshCalibrationData));
  $("auto-paper-calibration").addEventListener("click", () => withButtonBusy("auto-paper-calibration", "Creating...", createAutoPaperCalibrationEntries));
  $("refresh-accuracy-lab").addEventListener("click", () => withButtonBusy("refresh-accuracy-lab", "Checking...", loadAccuracyLab));
  $("preferences-form").addEventListener("submit", savePreferences);
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
    loadEntryProgress({ autoCheck: true, refreshProviders: true }).catch((error) => {
      console.warn("Live entry progress polling failed", error);
    });
  }, 60000);
}

async function loadAll() {
  syncDefaultInputs();
  const essentials = await Promise.allSettled([
    loadDashboard(),
    loadRefreshSchedule(),
    loadPreferences(),
    loadEntryProgress({ autoCheck: false, refreshProviders: false, marketDetail: false }),
    loadDnpSetting(),
    loadPending(),
  ]);
  const failure = essentials.find((result) => result.status === "rejected");
  if (failure) {
    handleLoadError(failure.reason);
    return;
  }
  hideRuntimeNotice();

  Promise.allSettled([
    loadModelHealth(),
    loadDailyBriefing(),
    loadDailyScanStatus(),
    loadDataHealth(),
    loadNotifications(),
    loadPerformance(),
  ]).then((results) => {
    const backgroundFailure = results.find((result) => result.status === "rejected");
    if (backgroundFailure) console.warn("Background EdgeIQ panel refresh failed", backgroundFailure.reason);
  });

  deferWork(() => {
    Promise.allSettled([
      loadEntryProgress({ autoCheck: true, refreshProviders: true }),
      loadBets(),
      loadBankrollTransactions(),
      loadAccuracyLab(),
    ]).then((results) => {
      const backgroundFailure = results.find((result) => result.status === "rejected");
      if (backgroundFailure) console.warn("Deferred EdgeIQ ledger refresh failed", backgroundFailure.reason);
    });
  }, 2500);

  deferWork(() => {
    Promise.allSettled([
      loadAdvantageCenter(),
      loadTimingAlerts(),
      loadCommandCenter(),
      loadDashboardParlay(),
      loadTrendingGames(),
    ]).then((results) => {
      const backgroundFailure = results.find((result) => result.status === "rejected");
      if (backgroundFailure) console.warn("Deferred EdgeIQ signal refresh failed", backgroundFailure.reason);
    });
  }, 5000);
}

bindEvents();
showOnboardingIfNeeded();
loadAll();
startLiveEntryPolling();
