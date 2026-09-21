(() => {
  function mount(root, data, { escapeHtml: escape, pct, formatDateTime }) {
    const exact = data.recommendation && data.recommendation.line === data.line;
    const prop = exact ? data.recommendation : {};
    const number = (v) => v != null && Number.isFinite(Number(v)) ? Number(v).toFixed(1) : "Unavailable";
    const fresh = data.edgeiq_score_freshness?.status === "fresh";
    const paid = exact && fresh && prop.forecast_paid_eligible === true && prop.recommendation_eligibility?.paid_ready === true;
    const fields = [["Team", prop.team], ["Opponent", data.opponent],
      ["Game time", prop.game_time ? formatDateTime(prop.game_time) : null],
      ["Platform", exact ? prop.platform : data.platform], ["Stat", data.stat],
      ["Line", number(data.line)], ["Direction", prop.direction || "No exact-line recommendation"],
      ["Hit probability", prop.confidence == null ? "Unavailable" : pct(prop.confidence)],
      ["Projection", number(prop.projection)], ["Model edge", number(prop.edge)],
      ["Evidence", fresh ? "Current" : "Stale or unverified"]];
    const header = document.createElement("section");
    header.className = "player-workspace-overview";
    header.innerHTML = `<h3>${escape(data.player)} <small>${escape(data.sport)}</small></h3>
      <p>${paid ? "Paid-use evidence gates passed; offer confirmation still required." : "Research only: paid-use evidence has not been confirmed for this exact line."}</p>
      <dl>${fields.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value ?? "Unavailable")}</dd></div>`).join("")}</dl>`;
    root.prepend(header);
    const performance = document.createElement("details");
    performance.className = "consumer-research-section";
    const versions = data.model_performance?.versions || [];
    performance.innerHTML = `<summary>Model Performance</summary>
      ${versions.map((row) => `<section class="player-model-record"><h4>${escape(row.model_version)} · ${escape(row.platform)} · ${escape(row.direction)}</h4>
        <p>${Number(row.settled_predictions)} independent settled predictions${row.small_sample ? " · Small sample: not proof of a reliable edge" : ""}</p>
        <dl><div><dt>Win rate</dt><dd>${pct(row.actual_hit_rate)}</dd></div>
        <div><dt>Average predicted probability</dt><dd>${pct(row.predicted_hit_rate)}</dd></div>
        <div><dt>Calibration gap</dt><dd>${number(row.calibration_gap)} percentage points</dd></div>
        <div><dt>Brier score</dt><dd>${escape(row.brier_score)}</dd></div></dl></section>`).join("") || "<p>No qualifying independently settled pregame predictions are available for this player and stat.</p>"}
      <p class="subtle">Player hit history is not model accuracy. ROI and stored-score bucket performance are unavailable. This record does not authorize paid use.</p>`;
    root.append(performance);
    const labels = ["Overview", "Recent Form", "Projection", "Matchup", "Game Logs", "Best Lines", "Evidence", "Model Performance"];
    const nav = document.createElement("nav");
    nav.className = "player-workspace-nav";
    nav.setAttribute("aria-label", "Player research sections");
    [header, ...root.querySelectorAll(":scope > details.consumer-research-section")].forEach((target, i) => {
      target.id = `player-workspace-section-${i}`;
      const link = document.createElement("a");
      link.href = `#${target.id}`;
      link.textContent = labels[i];
      link.addEventListener("click", (event) => {
        event.preventDefault();
        if (target.tagName === "DETAILS") target.open = true;
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        const focus = target.querySelector("summary") || target;
        focus.tabIndex = -1;
        focus.focus({ preventScroll: true });
      });
      nav.append(link);
    });
    root.prepend(nav);
  }
  window.EdgeIQPlayerWorkspace = { mount };
})();
