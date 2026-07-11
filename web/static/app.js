const state = {
  entryProps: [],
  lastEntryPayload: null,
  lastAnalysis: null,
  recommendationOrigin: false,
  commandCards: [],
};

window.EdgeIQLoaded = true;

const $ = (id) => document.getElementById(id);
const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8000" : "";

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json();
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

function formatDateTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const month = date.toLocaleString(undefined, { month: "long" });
  const day = date.getDate();
  const year = date.getFullYear();
  let hours = date.getHours();
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const suffix = hours >= 12 ? "PM" : "AM";
  hours = hours % 12 || 12;
  return `${month} ${day}, ${year} ${hours}:${minutes} ${suffix}`;
}

function propPickText(prop) {
  const direction = prop.direction || "Over";
  return `${prop.player} ${direction} ${prop.stat} ${prop.line}`;
}

function shortPropPickText(prop) {
  return `${prop.player} ${prop.direction || "Over"} ${prop.stat}`;
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
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.remove("active"));
  $(viewId).classList.add("active");
  document.querySelector(`[data-view="${viewId}"]`).classList.add("active");
  $("view-title").textContent = document.querySelector(`[data-view="${viewId}"]`).textContent;
}

function renderStats(stats) {
  const accuracy = stats.recommendation_accuracy || {};
  const paper = stats.paper || {};
  const items = [
    ["Record", stats.record],
    ["Win %", stats.wins + stats.losses ? pct((stats.wins / (stats.wins + stats.losses)) * 100) : "0.0%"],
    ["Net Profit", money(stats.profit)],
    ["ROI", pct(stats.roi)],
    ["Bankroll", money(stats.bankroll)],
    ["Deposits", money(stats.bankroll_transactions?.deposits)],
    ["Withdrawals", money(stats.bankroll_transactions?.withdrawals)],
    ["Wagered", money(stats.wagered)],
    ["Pending Entry Exposure", money(stats.pending_entry_exposure)],
    ["Paper Calibration", `${paper.decisions || 0} decisions`],
    ["Current Streak", stats.current_streak > 0 ? `W${stats.current_streak}` : stats.current_streak < 0 ? `L${Math.abs(stats.current_streak)}` : "-"],
    ["Max Drawdown", money(stats.max_drawdown)],
  ];
  $("dashboard-stats").innerHTML = items.map(([label, value]) => `
    <div class="stat-card">
      <div class="stat-value">${value}</div>
      <div class="stat-label">${label}</div>
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
    <div class="command-card">
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
  $("data-health-list").innerHTML = `
    <div class="suggestion compact-suggestion">
      <div class="suggestion-top">
        <strong>${data.summary.connected}/${data.summary.total} sources available</strong>
        <span class="subtle">${data.summary.warnings} warnings</span>
      </div>
      <p>${data.summary.last_daily_refresh ? `Last refresh ${formatDateTime(data.summary.last_daily_refresh)}` : "No scheduled refresh run recorded yet."}</p>
    </div>
    ${data.providers.slice(0, 8).map((provider) => `
      <div class="suggestion compact-suggestion health-${provider.status}">
        <div class="suggestion-top">
          <strong>${provider.name}</strong>
          <span class="subtle">${provider.status}</span>
        </div>
        <p>${provider.purpose} · ${provider.message}</p>
      </div>
    `).join("")}
  `;
}

async function loadNotifications() {
  const data = await api("/api/notifications");
  $("notification-list").innerHTML = (data.notifications || []).map((note) => `
    <div class="suggestion compact-suggestion notification-${note.severity || "neutral"}">
      <div class="suggestion-top">
        <strong>${note.title}</strong>
        <span class="subtle">${note.type}</span>
      </div>
      <p>${note.message}</p>
    </div>
  `).join("") || `<div class="suggestion">No smart notifications right now.</div>`;
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
  await Promise.all([loadRefreshSchedule(), loadDataHealth(), loadNotifications(), loadDashboard(), loadEntryProgress()]);
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

async function loadEntryProgress() {
  const data = await api("/api/entries/progress");
  $("entry-progress-status").textContent = data.active
    ? `${data.active} active entries · ${data.with_live_stats} with live stat data`
    : "No active placed entries.";
  $("entry-progress-list").innerHTML = data.entries.map((entry) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <span class="pill">#${entry.id}</span>
        <strong class="${entry.live_result === "Loss" ? "danger-text" : ""}">${entry.live_result}</strong>
        <span class="subtle">${entry.completed_legs}/${entry.total_legs} legs final · ${entry.source}</span>
      </div>
      <p>Confidence ${pct(entry.average_confidence)} · Edge ${Number(entry.average_edge).toFixed(2)} · Projected ${entry.projected_result} · ${formatDateTime(entry.placed_at)}</p>
      <div class="progress-legs">
        ${entry.legs.map((leg) => `
          <div class="progress-leg">
            <strong>${leg.player}</strong>
            <span>${leg.direction || "Over"} ${leg.stat} ${leg.line}</span>
            <span>
              <span>${leg.progress_text}</span>
              <span class="leg-meter" aria-label="${leg.progress_label}">
                <span class="leg-meter-fill ${leg.status === "Win" ? "is-win" : leg.status === "Loss" ? "is-loss" : ""}" style="width:${Math.min(100, Number(leg.progress_percent || 0))}%"></span>
              </span>
            </span>
            <span class="${leg.clv && leg.clv.clv < 0 ? "danger-text" : ""}">CLV ${leg.clv && leg.clv.clv != null ? Number(leg.clv.clv).toFixed(1) : "-"}</span>
            <span class="${leg.status === "Loss" ? "danger-text" : ""}">${leg.status}</span>
          </div>
        `).join("")}
      </div>
    </div>
  `).join("") || `<div class="suggestion">No active placed entries.</div>`;
}

async function loadProps() {
  $("props-status").textContent = "Loading props...";
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const data = await api(`/api/props/top?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}`);
  $("props-status").textContent = sport === "All Sports"
    ? `Showing up to ${data.per_sport_limit} unique-player props per sport`
    : `Showing top ${data.props.length} unique-player ${sport} props`;
  $("props-table").innerHTML = data.props.map((prop, index) => `
    <tr>
      <td>${prop.sport_rank || index + 1}</td>
      <td>${prop.platform || platform}</td>
      <td>
        <button class="link-button" data-player-detail="${index}">${prop.player}</button>
        <button class="micro-button" data-add-prop="${index}">+</button>
      </td>
      <td>${prop.direction || "Over"}</td>
      <td>${prop.league || ""}</td>
      <td>${prop.stat || ""}</td>
      <td>${prop.line ?? "-"}</td>
      <td>${prop.game || ""}</td>
      <td>${Number(prop.trending_count || 0).toLocaleString()}</td>
      <td><button class="secondary" data-add-prop="${index}">Add</button></td>
    </tr>
  `).join("");
  document.querySelectorAll("[data-add-prop]").forEach((button) => {
    button.addEventListener("click", () => addFeedProp(data.props[Number(button.dataset.addProp)]));
  });
  document.querySelectorAll("[data-player-detail]").forEach((button) => {
    button.addEventListener("click", () => loadPlayerDetail(data.props[Number(button.dataset.playerDetail)]));
  });
  Promise.allSettled([
    loadDashboardParlay(platform, sport),
    loadTrendingGames(platform, sport),
    loadCommandCenter(),
    loadTimingAlerts(),
  ]);
}

async function askAiParlay() {
  $("ai-parlay-status").textContent = "Finding today's best parlay...";
  $("ai-parlay-response").classList.add("muted-card");
  $("ai-parlay-response").textContent = "Thinking through the current board...";
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
    : `Data fallback · ${data.request?.sport_label || "All Sports"} · ${data.request?.leg_count || 3} legs${data.ai_error ? ` · ${data.ai_error}` : ""}`;
  $("ai-parlay-response").classList.remove("muted-card");
  $("ai-parlay-response").innerHTML = `
    <p>${data.message}</p>
    ${data.suggestion ? `<button class="secondary" id="load-ai-parlay">Load Parlay</button>` : ""}
  `;
  if (data.suggestion) {
    $("load-ai-parlay").addEventListener("click", () => {
      renderEntryPropsFromAnalyzed(data.suggestion.entry.props);
      state.recommendationOrigin = true;
      setView("entries");
      $("entry-status").textContent = "Loaded AI parlay suggestion. Analyze/place when ready.";
    });
  }
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
  if (!suggestion) {
    $("dashboard-parlay").classList.add("muted-card");
    $("dashboard-parlay").innerHTML = "No 3-leg parlay is available for the current filters.";
    return;
  }

  $("dashboard-parlay").classList.remove("muted-card");
  $("dashboard-parlay").innerHTML = `
    <div class="suggestion-top">
      <div>
        <span class="pill">3 Leg</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
      </div>
      <span class="subtle">Score ${suggestion.score}</span>
    </div>
    <p>${suggestion.entry.props.map(propPickText).join(" + ")}</p>
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
              <td>${playerProp.direction || "Over"} ${playerProp.stat}</td>
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
        <td>${prop.direction || "Over"}</td>
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
      <p class="subtle">${data.ai_enabled ? `OpenAI assisted · ${data.model}` : `Rules fallback${data.ai_error ? ` · ${data.ai_error}` : ""}`}</p>
      <p>${data.review}</p>
    </div>
  `;
  $("entry-status").textContent = data.ai_enabled ? "AI review complete." : "Rules review complete. Check OpenAI status if you expected AI.";
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
  const confirmed = window.confirm(state.lastEntryPayload.entry_mode === "paper" ? "Save this as a paper entry for calibration?" : "Will you place this entry?");
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
    <div class="suggestion">
      <div class="suggestion-top">
        <span class="pill">#${suggestion.rank} · ${suggestion.leg_count} Legs</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
        <span class="subtle">${suggestion.risk_tier || "Standard"} · Score ${suggestion.score}</span>
      </div>
      <p>${suggestion.entry.props.map(propPickText).join(" + ")}</p>
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
    <div class="suggestion">
      <div class="suggestion-top">
        <span class="pill">#${suggestion.rank} · ${suggestion.leg_count} Legs</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
        <span class="subtle">Score ${suggestion.score}</span>
      </div>
      <p>${suggestion.entry.props.map(propPickText).join(" + ")}</p>
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
      <p>${entry.props.map(propPickText).join(" + ")}</p>
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
}

async function runSync() {
  $("sync-status").textContent = "Syncing provider stats, imports, and pending entries...";
  const data = await api("/api/sync/run", { method: "POST" });
  const auto = data.auto_check || {};
  const finalFile = data.final_stats_file || {};
  const betFile = data.bet_history_file || {};
  $("sync-status").textContent = `Sync complete: checked ${auto.checked || 0}, settled ${auto.settled || 0}, final rows ${finalFile.imported || 0}, bet rows ${betFile.imported || 0}.`;
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
      <p>${prop.sport} · ${prop.direction || "Over"} ${prop.stat} ${prop.line} · Projection ${prop.projection} · Hit ${pct(prop.estimated_probability)}</p>
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
      <td>${prop.direction || "Over"} ${prop.stat}</td>
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
  $("bets-status").textContent = `${data.bets.length} saved bets`;
  $("bets-table").innerHTML = data.bets.map((bet) => `
    <tr>
      <td>${bet.sport}</td>
      <td>${bet.game}</td>
      <td>${bet.description}</td>
      <td>${bet.result}</td>
      <td class="${bet.profit < 0 ? "danger-text" : ""}">${money(bet.profit)}</td>
    </tr>
  `).join("");
}

function renderGroup(target, group) {
  const rows = Object.entries(group || {}).map(([name, stats]) => `
    <div class="suggestion">
      <strong>${name}</strong>
      <p>${stats.bets || 0} bets · ${stats.entries || 0} entries · ${pct(stats.win_pct)} win · ${money(stats.profit)} profit · ${pct(stats.roi)} ROI</p>
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
    legend.innerHTML = `<div class="suggestion">Settle bets or entries to build the sport success chart.</div>`;
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
  renderPerformanceInsights(data.summary.performance_insights);
  renderEntryPerformance(data.entries);
  renderEntryPlatformProfitability(data.summary.entry_platform_profitability || data.entries.platform_profitability || []);
  await loadBacktest();
}

function renderEntryPlatformProfitability(platforms) {
  $("entry-platform-profitability").innerHTML = platforms.map((platform) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>#${platform.rank} ${platform.platform}</strong>
        <span class="subtle">${platform.entries} settled entries</span>
      </div>
      <p>${money(platform.profit)} profit · ${money(platform.wagered)} wagered · ${pct(platform.roi)} ROI · ${pct(platform.win_pct)} win</p>
    </div>
  `).join("") || `<div class="suggestion">No settled platform entries yet.</div>`;
}

function renderEntryPerformance(entries) {
  const resultRows = Object.entries(entries.by_result || {}).map(([result, stats]) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>${result} Entries</strong>
        <span class="subtle">${stats.entries} entries</span>
      </div>
      <p>${money(stats.profit)} profit · ${money(stats.wagered)} wagered · ${pct(stats.roi)} ROI</p>
    </div>
  `).join("");
  $("entry-result-performance").innerHTML = resultRows || `<div class="suggestion">No settled entries yet.</div>`;
}

async function loadBacktest() {
  const data = await api("/api/analytics/backtest");
  $("backtest-summary").innerHTML = `
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>Tracked Bets</strong>
        <span class="subtle">${data.bets.count} bets</span>
      </div>
      <p>${pct(data.bets.win_rate)} win · ${money(data.bets.profit)} profit · ${pct(data.bets.roi)} ROI</p>
    </div>
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>Settled Entries</strong>
        <span class="subtle">${data.entries.count} entries</span>
      </div>
      <p>${data.entries.wins}-${data.entries.losses}-${data.entries.pushes} · Actual ${pct(data.entries.confidence.actual_win_rate)} vs confidence ${pct(data.entries.confidence.average_confidence)}</p>
    </div>
    ${Object.entries(data.entries.by_grade).map(([grade, stats]) => `
      <div class="suggestion">
        <strong>Grade ${grade}</strong>
        <p>${stats.entries} entries · ${pct(stats.win_rate)} win · ${stats.wins}-${stats.losses}-${stats.pushes}</p>
      </div>
    `).join("")}
  `;
  $("calibration-list").innerHTML = data.calibration.map((bucket) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <strong>${bucket.label}</strong>
        <span class="subtle">${bucket.bets} picks</span>
      </div>
      <p>Predicted ${pct(bucket.predicted_mid)} · Actual ${pct(bucket.actual_pct)} · Error ${pct(bucket.error)}</p>
    </div>
  `).join("") || `<div class="suggestion">No calibrated picks yet. Save win probabilities or settle entries to build this.</div>`;
}

async function loadPreferences() {
  const data = await api("/api/settings/preferences");
  const prefs = data.preferences || data;
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
  $("refresh-all").addEventListener("click", loadAll);
  $("refresh-command-center").addEventListener("click", loadCommandCenter);
  $("refresh-advantage-center").addEventListener("click", loadAdvantageCenter);
  $("refresh-data-health").addEventListener("click", loadDataHealth);
  $("refresh-notifications").addEventListener("click", loadNotifications);
  $("run-daily-refresh").addEventListener("click", runDailyRefresh);
  $("refresh-timing-alerts").addEventListener("click", loadTimingAlerts);
  ["timing-min-confidence", "timing-min-ev", "timing-alert-type", "timing-hide-outliers"].forEach((id) => {
    $(id).addEventListener("change", loadTimingAlerts);
  });
  $("refresh-progress").addEventListener("click", loadEntryProgress);
  $("sync-now").addEventListener("click", runSync);
  $("refresh-games").addEventListener("click", () => loadTrendingGames());
  $("ask-ai-parlay").addEventListener("click", askAiParlay);
  $("load-props").addEventListener("click", loadProps);
  $("prop-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const prop = propFromForm();
    if (!prop.player || !prop.line) return;
    state.entryProps.push(prop);
    $("prop-form").reset();
    renderEntryProps();
  });
  $("analyze-entry").addEventListener("click", analyzeEntry);
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
  $("generate-suggestions").addEventListener("click", loadSuggestions);
  $("run-optimizer").addEventListener("click", runOptimizer);
  $("refresh-pending").addEventListener("click", loadPending);
  $("classify-default-wagers").addEventListener("click", classifyDefaultWagers);
  $("save-dnp-handling").addEventListener("click", saveDnpSetting);
  $("auto-check-entries").addEventListener("click", autoCheckEntries);
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
  $("refresh-bets").addEventListener("click", loadBets);
  $("refresh-backtest").addEventListener("click", loadBacktest);
  $("refresh-accuracy-lab").addEventListener("click", loadAccuracyLab);
  $("preferences-form").addEventListener("submit", savePreferences);
  $("watchlist-form").addEventListener("submit", saveWatchlistItem);
  $("boost-form").addEventListener("submit", analyzeBoost);
  $("bankroll-strategy-form").addEventListener("submit", saveBankrollStrategy);
  document.querySelectorAll("[data-close-drawer]").forEach((button) => {
    button.addEventListener("click", closeExplanationDrawer);
  });
  $("mobile-slip-toggle").addEventListener("click", toggleMobileSlip);
  $("mobile-analyze-entry").addEventListener("click", mobileAnalyzeEntry);
  $("mobile-place-entry").addEventListener("click", mobilePlaceEntry);
  $("mobile-slip-wager").addEventListener("input", () => { $("entry-wager").value = $("mobile-slip-wager").value; });
  $("mobile-slip-multiplier").addEventListener("input", () => { $("entry-multiplier").value = $("mobile-slip-multiplier").value; });
  $("onboarding-form").addEventListener("submit", saveOnboarding);
  $("onboarding-skip").addEventListener("click", skipOnboarding);
  $("onboarding-upload-history").addEventListener("click", openHistoryUploadFromOnboarding);
}

async function loadAll() {
  syncDefaultInputs();
  const results = await Promise.allSettled([
    loadDashboard(),
    loadModelHealth(),
    loadAdvantageCenter(),
    loadDataHealth(),
    loadNotifications(),
    loadRefreshSchedule(),
    loadPreferences(),
    loadTimingAlerts(),
    loadEntryProgress(),
    loadProps(),
    loadDnpSetting(),
    loadPending(),
    loadBets(),
    loadBankrollTransactions(),
    loadPerformance(),
    loadAccuracyLab(),
  ]);
  const failure = results.find((result) => result.status === "rejected");
  if (failure) {
    handleLoadError(failure.reason);
  } else {
    hideRuntimeNotice();
  }
}

bindEvents();
showOnboardingIfNeeded();
loadAll();
