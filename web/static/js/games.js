(function () {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const escape = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
  const percent = (value) => `${(Number(value || 0) * 100).toFixed(1)}%`;

  async function request(path, options = {}) {
    if (window.EdgeIQApi?.api) return window.EdgeIQApi.api(path, options);
    const response = await fetch(path, options);
    if (!response.ok) throw new Error("Game Intelligence could not load right now.");
    return response.json();
  }

  async function waitForJob(job) {
    let current = job;
    for (let attempt = 0; attempt < 300 && ["queued", "running", "canceling"].includes(current.status); attempt += 1) {
      const status = byId("game-intelligence-status");
      if (status) status.textContent = `${current.phase || "Refreshing games..."} ${Number(current.progress || 0)}%`;
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      current = await request(`/api/jobs/${encodeURIComponent(current.job_id)}`);
    }
    if (current.status === "failed") throw new Error(current.error || "Game predictions could not be refreshed.");
    if (current.status === "canceled") throw new Error("The game refresh was canceled.");
    return current;
  }

  function predictionCard(row) {
    const prediction = row.champion || row;
    const challenger = row.challenger || null;
    const home = escape(prediction.home_team || "Home");
    const away = escape(prediction.away_team || "Away");
    const evidence = prediction.evidence || {};
    return `<article class="game-intelligence-card">
      <div class="suggestion-top"><div><span class="pill">${escape(prediction.sport)}</span><h3>${away} vs ${home}</h3></div><span class="data-badge">${escape(prediction.data_quality)} data</span></div>
      <div class="game-win-bars" aria-label="Win probabilities"><div><span>${away}</span><strong>${percent(prediction.away_win_probability)}</strong></div><div><span>${home}</span><strong>${percent(prediction.home_win_probability)}</strong></div></div>
      <div class="game-intelligence-metrics">
        <span><small>Projected Score</small><strong>${Number(prediction.expected_away_points).toFixed(1)} – ${Number(prediction.expected_home_points).toFixed(1)}</strong></span>
        <span><small>Expected Margin</small><strong>${prediction.expected_margin >= 0 ? home : away} ${Math.abs(Number(prediction.expected_margin)).toFixed(1)}</strong></span>
        <span><small>Expected Total</small><strong>${Number(prediction.expected_total).toFixed(1)}</strong></span>
        <span><small>Blowout Risk</small><strong>${percent(prediction.blowout_probability)}</strong></span>
        <span><small>Game Script</small><strong>${escape(String(prediction.game_script || "neutral").replaceAll("_", " "))}</strong></span>
        <span><small>Model</small><strong>${escape(prediction.model_version)}</strong></span>
      </div>
      <details data-game-evidence><summary>Why this prediction?</summary><ul>
        <li>Moneyline: no-vig market baseline from ${Number(evidence.market_snapshot?.bookmakers?.length || 0)} paired books.</li>
        <li>Spread and total: ${evidence.market_home_margin == null ? "not available" : "captured"}; ${evidence.market_total == null ? "not available" : "captured"}.</li>
        <li>Challenger: ${challenger ? `${(Number(row.comparison?.home_probability_delta || 0) * 100).toFixed(1)} point home-probability residual` : "not generated in this saved row"}.</li>
        <li>Game context adjusts opportunity assumptions only. It does not directly increase prop confidence.</li>
      </ul></details>
      <button class="secondary game-to-props" type="button" data-game-to-props data-sport="${escape(prediction.sport)}" data-game="${escape(prediction.game)}">Research Props</button>
    </article>`;
  }

  function governance(data) {
    const models = data.registry?.models || [];
    return models.map((model) => `<div class="suggestion"><div class="suggestion-top"><strong>${escape(model.version)}</strong><span class="pill">${escape(model.role)}</span></div><p>${escape(model.reason || (model.paid_eligible ? "Production baseline." : "Not eligible for paid recommendations."))}</p></div>`).join("");
  }

  function propContextMarkup(context, championProjection, shadowProjection) {
    if (!context) return "";
    const adjustments = context.adjustments || [];
    return `<section class="research-game-context">
      <div class="section-heading compact-heading"><div><p class="eyebrow">Game Context</p><h3>Shadow opportunity check</h3></div><span class="status-pill status-warning">Not used for paid grading</span></div>
      <div class="metric-strip">
        <span><strong>${percent(context.team_win_probability)}</strong><small>Team win chance</small></span>
        <span><strong>${Number(context.expected_margin || 0).toFixed(1)}</strong><small>Team margin</small></span>
        <span><strong>${percent(context.blowout_probability)}</strong><small>Blowout risk</small></span>
        <span><strong>${escape(String(context.game_script || "neutral").replaceAll("_", " "))}</strong><small>Expected script</small></span>
        <span><strong>${championProjection ?? "-"}</strong><small>Current projection</small></span>
        <span><strong>${shadowProjection ?? championProjection ?? "-"}</strong><small>Game-aware shadow</small></span>
      </div>
      ${adjustments.map((row) => `<p class="subtle"><strong>${escape(row.metric)}:</strong> ${escape(row.reason)} (${Number(row.absolute_delta || 0) >= 0 ? "+" : ""}${Number(row.absolute_delta || 0).toFixed(2)} opportunity)</p>`).join("") || '<p class="subtle">Neutral game context produced no opportunity adjustment.</p>'}
      <p class="subtle">${escape(context.anti_double_counting || "Residual opportunity adjustments only.")}</p>
    </section>`;
  }

  async function load(refresh = false) {
    const sport = byId("game-intelligence-sport")?.value || "WNBA";
    const status = byId("game-intelligence-status");
    const list = byId("game-intelligence-list");
    if (!status || !list) return;
    status.textContent = refresh ? "Refreshing game evidence and predictions..." : "Loading saved game predictions...";
    list.innerHTML = '<div class="loading-skeleton"></div><div class="loading-skeleton"></div>';
    try {
      if (refresh) {
        const job = await request(`/api/game-intelligence/refresh?sport=${encodeURIComponent(sport)}`, { method: "POST" });
        await waitForJob(job);
      }
      const data = await request(`/api/game-intelligence/slate?sport=${encodeURIComponent(sport)}`);
      list.innerHTML = (data.games || []).map(predictionCard).join("") || '<div class="empty-state"><strong>No saved game predictions yet.</strong><p>Refresh Games after provider lines become available.</p></div>';
      byId("game-intelligence-governance").innerHTML = governance(data);
      status.textContent = `${(data.games || []).length} ${sport} game predictions · challenger remains shadow-only.`;
      window.trackProductEvent?.("game_prediction_viewed", "game_prediction", sport, { count: (data.games || []).length });
    } catch (error) {
      list.innerHTML = `<div class="empty-state"><strong>Game predictions are temporarily unavailable.</strong><p>${escape(error.message)}</p></div>`;
      status.textContent = "Game Intelligence needs attention.";
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    byId("refresh-game-intelligence")?.addEventListener("click", () => load(true));
    byId("game-intelligence-sport")?.addEventListener("change", () => load(false));
    document.addEventListener("click", (event) => {
      const button = event.target?.closest?.("[data-game-to-props]");
      if (!button) return;
      const detail = { sport: button.dataset.sport || "", game: button.dataset.game || "" };
      window.trackProductEvent?.("game_prediction_to_prop", "game_prediction", detail.game, { sport: detail.sport });
      document.dispatchEvent(new CustomEvent("edgeiq:game-to-props", { detail }));
    });
    document.addEventListener("toggle", (event) => {
      if (event.target?.matches?.("[data-game-evidence]") && event.target.open) {
        window.trackProductEvent?.("game_evidence_opened", "game_prediction", event.target.closest("article")?.querySelector("h3")?.textContent || "game");
      }
    }, true);
  });

  window.EdgeIQGames = { load, propContextMarkup };
})();
