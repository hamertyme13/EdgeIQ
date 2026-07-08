const state = {
  entryProps: [],
  lastEntryPayload: null,
  lastAnalysis: null,
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

function setView(viewId) {
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.remove("active"));
  $(viewId).classList.add("active");
  document.querySelector(`[data-view="${viewId}"]`).classList.add("active");
  $("view-title").textContent = document.querySelector(`[data-view="${viewId}"]`).textContent;
}

function renderStats(stats) {
  const items = [
    ["Record", stats.record],
    ["Win %", stats.wins + stats.losses ? pct((stats.wins / (stats.wins + stats.losses)) * 100) : "0.0%"],
    ["Net Profit", money(stats.profit)],
    ["ROI", pct(stats.roi)],
    ["Bankroll", money(stats.bankroll)],
    ["Wagered", money(stats.wagered)],
    ["Pending Entry Exposure", money(stats.pending_entry_exposure)],
    ["Current Streak", stats.current_streak > 0 ? `W${stats.current_streak}` : stats.current_streak < 0 ? `L${Math.abs(stats.current_streak)}` : "-"],
    ["Max Drawdown", money(stats.max_drawdown)],
  ];
  $("dashboard-stats").innerHTML = items.map(([label, value]) => `
    <div class="stat-card">
      <div class="stat-value">${value}</div>
      <div class="stat-label">${label}</div>
    </div>
  `).join("");
}

async function loadDashboard() {
  const stats = await api("/api/dashboard");
  renderStats(stats);
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
        <strong>${entry.projected_result}</strong>
        <span class="subtle">${entry.completed_legs}/${entry.total_legs} legs final · ${entry.source}</span>
      </div>
      <p>Confidence ${pct(entry.average_confidence)} · Edge ${Number(entry.average_edge).toFixed(2)} · ${entry.placed_at || ""}</p>
      <div class="progress-legs">
        ${entry.legs.map((leg) => `
          <div class="progress-leg">
            <strong>${leg.player}</strong>
            <span>${leg.stat} ${leg.line}</span>
            <span>${leg.progress_text}</span>
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
  const [data] = await Promise.all([
    api(`/api/props/top?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}`),
    loadDashboardParlay(platform, sport),
    loadTrendingGames(platform, sport),
  ]);
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
    <p>${suggestion.entry.props.map((prop) => `${prop.player} ${prop.stat} ${prop.line}`).join(" + ")}</p>
    ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
    <button class="secondary" id="load-dashboard-parlay">Load Parlay</button>
  `;
  $("load-dashboard-parlay").addEventListener("click", () => {
    renderEntryPropsFromAnalyzed(suggestion.entry.props);
    setView("entries");
    $("entry-status").textContent = "Loaded recommended 3-leg parlay. Analyze/place when ready.";
  });
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
              <td>${playerProp.stat}</td>
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
      $("place-entry").disabled = true;
      renderEntryProps();
    });
  });
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
    platform: $("entry-platform").value,
    game: "",
    trending_count: 0,
  };
}

function entryPayload() {
  return {
    platform: $("entry-platform").value,
    wager: Number($("entry-wager").value || 0),
    multiplier: Number($("entry-multiplier").value || 1),
    props: state.entryProps,
  };
}

function renderAnalysis(data) {
  const rec = data.recommendation;
  const risk = data.risk;
  const warnings = data.warnings || [];
  $("entry-analysis").classList.remove("muted-card");
  $("entry-analysis").innerHTML = `
    <div class="grade">${rec.grade}</div>
    <h2>${rec.action}</h2>
    <p>${rec.reason}</p>
    <div class="stats-grid" style="margin-top:14px">
      <div class="stat-card"><div class="stat-value">${pct(risk.average_confidence)}</div><div class="stat-label">Avg Confidence</div></div>
      <div class="stat-card"><div class="stat-value">${Number(risk.average_edge).toFixed(2)}</div><div class="stat-label">Avg Edge</div></div>
      <div class="stat-card"><div class="stat-value">${risk.level}</div><div class="stat-label">Risk</div></div>
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
  renderAnalysis(data);
  renderEntryPropsFromAnalyzed(data.entry.props);
  $("place-entry").disabled = false;
  $("entry-status").textContent = "Entry analyzed. Review before placing.";
}

function renderEntryPropsFromAnalyzed(props) {
  state.entryProps = props.map((prop) => ({
    player: prop.player,
    team: prop.team,
    sport: prop.sport,
    stat: prop.stat,
    line: prop.line,
    projection: prop.projection,
    platform: prop.platform,
    game: prop.game,
    trending_count: prop.trending_count,
  }));
  renderEntryProps();
}

async function placeEntry() {
  if (!state.lastEntryPayload) return;
  state.lastEntryPayload.wager = Number($("entry-wager").value || state.lastEntryPayload.wager || 0);
  state.lastEntryPayload.multiplier = Number($("entry-multiplier").value || state.lastEntryPayload.multiplier || 1);
  if (state.lastEntryPayload.wager <= 0) {
    $("entry-status").textContent = "Enter the amount wagered before placing.";
    return;
  }
  const confirmed = window.confirm("Will you place this entry?");
  if (!confirmed) return;
  const data = await api("/api/entries/place", { method: "POST", body: JSON.stringify(state.lastEntryPayload) });
  $("entry-status").textContent = `Entry #${data.id} saved as pending. Bankroll reserved ${money(state.lastEntryPayload.wager)}.`;
  state.entryProps = [];
  state.lastEntryPayload = null;
  $("place-entry").disabled = true;
  renderEntryProps();
  await loadPending();
  await loadDashboard();
}

async function loadSuggestions() {
  $("suggestions-list").innerHTML = `<div class="suggestion">Generating...</div>`;
  const sport = $("suggest-sport").value;
  const platform = $("suggest-platform").value;
  const data = await api(`/api/entries/suggestions?sport=${encodeURIComponent(sport)}&platform=${encodeURIComponent(platform)}`);
  $("suggestions-list").innerHTML = data.suggestions.map((suggestion, index) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <span class="pill">#${suggestion.rank}</span>
        <strong>${suggestion.grade} · ${suggestion.action}</strong>
        <span class="subtle">Score ${suggestion.score}</span>
      </div>
      <p>${suggestion.entry.props.map((prop) => `${prop.player} ${prop.stat} ${prop.line}`).join(" + ")}</p>
      ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
      <button class="secondary" data-load-suggestion="${index}">Load Suggestion</button>
    </div>
  `).join("") || `<div class="suggestion">No suggestions available.</div>`;
  document.querySelectorAll("[data-load-suggestion]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.loadSuggestion)];
      renderEntryPropsFromAnalyzed(suggestion.entry.props);
      $("entry-status").textContent = `Loaded suggestion #${suggestion.rank}. Analyze/place when ready.`;
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
      <p>${suggestion.entry.props.map((prop) => `${prop.player} ${prop.stat} ${prop.line}`).join(" + ")}</p>
      ${suggestion.warnings.length ? `<p class="warning">${suggestion.warnings.join(" · ")}</p>` : ""}
      <button class="secondary" data-load-optimized="${index}">Load Slip</button>
    </div>
  `).join("") || `<div class="suggestion">No optimized slips available.</div>`;
  document.querySelectorAll("[data-load-optimized]").forEach((button) => {
    button.addEventListener("click", () => {
      const suggestion = data.suggestions[Number(button.dataset.loadOptimized)];
      renderEntryPropsFromAnalyzed(suggestion.entry.props);
      $("entry-status").textContent = `Loaded optimized ${suggestion.leg_count}-leg slip #${suggestion.rank}.`;
    });
  });
}

async function loadPending() {
  const data = await api("/api/entries/pending");
  $("pending-list").innerHTML = data.entries.map((entry) => `
    <div class="suggestion">
      <div class="suggestion-top">
        <span class="pill">#${entry.id}</span>
        <strong>${entry.platform}</strong>
        <span class="subtle">${entry.placed_at || ""}</span>
      </div>
      <p>${entry.props.map((prop) => `${prop.player} ${prop.stat} ${prop.line}`).join(" + ")}</p>
      <p>${money(entry.wager)} wagered · ${Number(entry.multiplier || 1).toFixed(1)}x · ${money(entry.potential_payout)} payout</p>
      <div class="button-row">
        <button data-settle="${entry.id}:Win">Win</button>
        <button class="danger" data-settle="${entry.id}:Loss">Loss</button>
        <button class="secondary" data-settle="${entry.id}:Push">Push</button>
      </div>
    </div>
  `).join("") || `<div class="suggestion">No pending entries.</div>`;
  document.querySelectorAll("[data-settle]").forEach((button) => {
    button.addEventListener("click", async () => {
      const [id, result] = button.dataset.settle.split(":");
      await api(`/api/entries/${id}/settle`, { method: "POST", body: JSON.stringify({ result }) });
      await loadPending();
      await loadDashboard();
      await loadPerformance();
    });
  });
}

async function autoCheckEntries() {
  $("auto-check-status").textContent = "Checking pending entries...";
  const data = await api("/api/entries/auto-check", { method: "POST" });
  const estimateNote = data.estimated ? " Some entries used projection estimates." : "";
  const pendingNote = data.settled === 0 ? " Final stat data may not be connected yet." : "";
  $("auto-check-status").textContent = `Checked ${data.checked}, settled ${data.settled}.${estimateNote}${pendingNote}`;
  await loadPending();
  await loadDashboard();
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
      <p>${stats.bets} bets · ${pct(stats.win_pct)} win · ${money(stats.profit)} profit · ${pct(stats.roi)} ROI</p>
    </div>
  `).join("");
  $(target).innerHTML = rows || `<p>No data yet.</p>`;
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
  renderEntryPerformance(data.entries);
  await loadBacktest();
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

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  $("refresh-all").addEventListener("click", loadAll);
  $("refresh-progress").addEventListener("click", loadEntryProgress);
  $("refresh-games").addEventListener("click", () => loadTrendingGames());
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
  $("place-entry").addEventListener("click", placeEntry);
  $("clear-entry").addEventListener("click", () => {
    state.entryProps = [];
    state.lastEntryPayload = null;
    $("place-entry").disabled = true;
    renderEntryProps();
  });
  $("generate-suggestions").addEventListener("click", loadSuggestions);
  $("run-optimizer").addEventListener("click", runOptimizer);
  $("refresh-pending").addEventListener("click", loadPending);
  $("auto-check-entries").addEventListener("click", autoCheckEntries);
  $("ev-form").addEventListener("submit", calculateEv);
  $("line-movement-form").addEventListener("submit", loadLineMovement);
  $("hit-rate-form").addEventListener("submit", estimateHitRate);
  $("final-stats-form").addEventListener("submit", importFinalStats);
  $("bet-form").addEventListener("submit", saveBet);
  $("refresh-bets").addEventListener("click", loadBets);
  $("refresh-backtest").addEventListener("click", loadBacktest);
}

async function loadAll() {
  const results = await Promise.allSettled([
    loadDashboard(),
    loadEntryProgress(),
    loadProps(),
    loadPending(),
    loadBets(),
    loadPerformance(),
  ]);
  const failure = results.find((result) => result.status === "rejected");
  if (failure) {
    handleLoadError(failure.reason);
  } else {
    hideRuntimeNotice();
  }
}

bindEvents();
loadAll();
