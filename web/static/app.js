const state = {
  entryProps: [],
  lastEntryPayload: null,
  lastAnalysis: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json();
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

async function loadProps() {
  $("props-status").textContent = "Loading props...";
  const platform = $("props-platform").value;
  const sport = $("props-sport").value;
  const data = await api(`/api/props/top?platform=${encodeURIComponent(platform)}&sport=${encodeURIComponent(sport)}`);
  $("props-status").textContent = `Showing ${data.props.length} unique-player props`;
  $("props-table").innerHTML = data.props.map((prop, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${prop.platform || platform}</td>
      <td><button class="link-button" data-add-prop="${index}">${prop.player}</button></td>
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
  const confirmed = window.confirm("Will you place this entry?");
  if (!confirmed) return;
  const data = await api("/api/entries/place", { method: "POST", body: JSON.stringify(state.lastEntryPayload) });
  $("entry-status").textContent = `Entry #${data.id} saved as pending.`;
  state.entryProps = [];
  state.lastEntryPayload = null;
  $("place-entry").disabled = true;
  renderEntryProps();
  await loadPending();
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
    });
  });
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
  ].map(([label, value]) => `
    <div class="stat-card"><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div>
  `).join("");
  renderGroup("perf-sport", data.by_sport);
  renderGroup("perf-stat", data.by_stat);
  renderGroup("perf-platform", data.by_platform);
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  $("refresh-all").addEventListener("click", loadAll);
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
  $("refresh-pending").addEventListener("click", loadPending);
  $("ev-form").addEventListener("submit", calculateEv);
  $("bet-form").addEventListener("submit", saveBet);
  $("refresh-bets").addEventListener("click", loadBets);
}

async function loadAll() {
  await Promise.allSettled([
    loadDashboard(),
    loadProps(),
    loadPending(),
    loadBets(),
    loadPerformance(),
  ]);
}

bindEvents();
loadAll();
