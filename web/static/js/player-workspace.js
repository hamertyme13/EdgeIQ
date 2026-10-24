(() => {
  function mount(root, data, { escapeHtml: escape, pct, formatDateTime, api }) {
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
    if (data.nba_points_intelligence) {
      const intelligence = data.nba_points_intelligence;
      const points = document.createElement("details");
      points.className = "consumer-research-section nba-points-intelligence";
      points.open = true;
      const windows = [["last_5", "Last 5"], ["last_10", "Last 10"], ["last_20", "Last 20"], ["verified_season", "Verified season"], ["season", "Tracked window"]];
      const renderWindow = (key) => {
        const windowData = intelligence.thresholds?.[key] || {};
        const custom = windowData.custom_line;
        const provenance = key === "verified_season"
          ? "confirmed regular-season games only"
          : `${intelligence.season_provenance?.unverified_games || 0} with season type unverified`;
        return `<p class="subtle">${windowData.games || 0} final-score games · ${provenance} · historical results, not next-game probability</p>
          <div class="nba-points-thresholds">${(windowData.thresholds || []).map((row) => `<div class="nba-points-threshold">
            <strong>${row.points}+ points</strong><span>${row.hits}/${row.games} · ${row.hit_rate == null ? "Unavailable" : pct(row.hit_rate)}</span>
            <span class="nba-points-meter"><i style="width:${Math.max(0, Math.min(100, Number(row.hit_rate) || 0))}%"></i></span>
          </div>`).join("")}</div>
          ${custom ? `<p class="nba-points-custom">Over ${number(data.line)}: ${custom.hits}/${custom.decisions} decisions${custom.pushes ? ` · ${custom.pushes} pushes` : ""} · ${custom.hit_rate == null ? "Unavailable" : pct(custom.hit_rate)} historical hit rate${custom.interval_95 ? ` · 95% range ${custom.interval_95[0]}–${custom.interval_95[1]}%` : ""}</p>
          <p class="subtle">Average ${custom.average ?? "-"} · Median ${custom.median ?? "-"} · Standard deviation ${custom.standard_deviation ?? "-"}</p>` : ""}`;
      };
      points.innerHTML = `<summary>NBA Points Intelligence <span class="status-pill ${intelligence.data_quality === "Developing" ? "status-positive" : "status-warning"}">${escape(intelligence.data_quality || "Unavailable")}</span></summary>
        <div class="nba-points-content">
          <p>${escape(intelligence.explanation || "")}</p>
          ${Object.entries(intelligence.data_reliability?.excluded || {}).some(([key, count]) => key !== "matching_duplicate" && count > 0)
            ? `<p class="subtle">Data review: ${Object.entries(intelligence.data_reliability.excluded).filter(([key, count]) => key !== "matching_duplicate" && count > 0).map(([key, count]) => `${count} ${escape(key.replaceAll("_", " "))}`).join(" · ")} withheld from scoring history.</p>`
            : ""}
          <div class="nba-points-window" role="group" aria-label="Scoring history window">${windows.map(([key, label], index) => `<button type="button" data-window="${key}" aria-pressed="${index === 0}">${label}</button>`).join("")}</div>
          <div class="nba-points-window-results" aria-live="polite">${renderWindow("last_5")}</div>
          <div class="nba-points-evidence">
            <p><strong>Forecast:</strong> ${intelligence.projection?.expected_points == null ? "Not validated" : `${number(intelligence.projection.expected_points)} points`} · Over ${intelligence.projection?.over_probability == null ? "unavailable" : pct(intelligence.projection.over_probability)} · Under ${intelligence.projection?.under_probability == null ? "unavailable" : pct(intelligence.projection.under_probability)}</p>
            ${intelligence.projection?.note?.includes("stored finals disagree") ? `<p class="subtle">${escape(intelligence.projection.note)}</p>` : ""}
            <p><strong>Minutes-based challenger (research only):</strong> ${intelligence.minutes_challenger?.expected_points == null
              ? `Unavailable · ${intelligence.minutes_challenger?.sample_size || 0}/5 verified regular-season games with minutes`
              : `${number(intelligence.minutes_challenger.expected_points)} points from ${number(intelligence.minutes_challenger.expected_minutes)} expected minutes and ${number(intelligence.minutes_challenger.points_per_minute)} points per minute`}. No probability or EV is inferred.</p>
            ${intelligence.minutes_challenger?.validation?.evaluated_games
              ? `<p class="subtle">Minutes challenger: ${intelligence.minutes_challenger.validation.evaluated_games} chronological tests · MAE ${number(intelligence.minutes_challenger.validation.challenger?.mae)} points vs recent-points average ${number(intelligence.minutes_challenger.validation.recent_points_average?.mae)}. This does not replace the current forecast.</p>`
              : ""}
            <p><strong>Matchup:</strong> ${escape(intelligence.matchup?.status || "Unverified")} ${intelligence.matchup?.head_to_head_games || 0} verified games vs ${escape(intelligence.matchup?.opponent || "selected opponent")}.</p>
            <p><strong>Opponent team defense:</strong> ${intelligence.matchup?.team_points_allowed?.sample_size
              ? `${number(intelligence.matchup.team_points_allowed.last_10)} points allowed over ${Math.min(10, intelligence.matchup.team_points_allowed.sample_size)} recent games · league sample ${number(intelligence.matchup.team_points_allowed.league_average)} · ${escape(intelligence.matchup.team_points_allowed.status)}`
              : "Verified pregame team finals unavailable."}</p>
            ${intelligence.matchup?.team_points_allowed?.source_games?.length
              ? `<p class="subtle">Official game evidence: ${intelligence.matchup.team_points_allowed.source_games.slice(0, 5).map((row, index) => `<a href="${escape(row.url)}" target="_blank" rel="noopener noreferrer">Game ${index + 1}</a>`).join(" · ")}</p>`
              : ""}
            <p><strong>Market value:</strong> ${escape(intelligence.market?.status || "Unverified")} · ${escape(intelligence.market?.reason || "")}</p>
            ${data.line != null ? `<button type="button" class="secondary" data-points-market-check>Check exact market</button>
              <p class="subtle" data-points-market-result aria-live="polite">Market odds are checked only when requested.</p>` : ""}
            ${data.line != null ? `<div class="nba-points-explanation-controls"><button type="button" class="secondary" data-points-explain="concise">Explain briefly</button>
              <button type="button" class="secondary" data-points-explain="detailed">Explain in detail</button></div>
              <div class="subtle" data-points-explanation aria-live="polite"></div>` : ""}
            <p class="subtle">Scoring variability (last 20): ${intelligence.consistency?.coefficient_of_variation ?? "Unavailable"}. ${escape(intelligence.consistency?.description || "")}</p>
            <p class="subtle">Chronological check: ${intelligence.validation?.evaluated_games ? `${intelligence.validation.evaluated_games} held-out games · last-five average MAE ${number(intelligence.validation.baselines?.prior_5_average?.mae)} points · prior-season average MAE ${number(intelligence.validation.baselines?.prior_season_average?.mae)} points` : escape(intelligence.validation?.status || "Unavailable")} · This is a baseline check, not model validation.</p>
            <button type="button" class="secondary" data-points-validation>View locked model record</button>
            <div class="subtle" data-points-validation-result aria-live="polite"></div>
          </div>
        </div>`;
      points.querySelectorAll("[data-window]").forEach((button) => button.addEventListener("click", () => {
        points.querySelectorAll("[data-window]").forEach((choice) => choice.setAttribute("aria-pressed", String(choice === button)));
        points.querySelector(".nba-points-window-results").innerHTML = renderWindow(button.dataset.window);
      }));
      points.querySelector("[data-points-market-check]")?.addEventListener("click", async (event) => {
        const button = event.currentTarget;
        const output = points.querySelector("[data-points-market-result]");
        button.disabled = true;
        output.textContent = "Checking paired Over and Under prices for this exact line...";
        try {
          const params = new URLSearchParams({ line: String(data.line), platform: data.platform || "Both" });
          const market = await api(`/api/players/${encodeURIComponent(data.player)}/points-market?${params}`);
          output.textContent = market.status === "research_comparison"
            ? `External books: Over ${number(market.market_over_probability)}%, Under ${number(market.market_under_probability)}% no-vig across ${market.book_count} book(s). ${market.model_over_probability == null ? "A comparable model probability is unavailable." : `EdgeIQ forecast: ${number(market.model_over_probability)}% Over; difference ${number(market.model_market_gap)} percentage points.`} No validated EV or DFS payout is claimed.`
            : market.reason || "Exact-line market data is unavailable.";
        } catch (_error) {
          output.textContent = "The exact-line market could not be checked right now. Try again later.";
        } finally {
          button.disabled = false;
        }
      });
      points.querySelectorAll("[data-points-explain]").forEach((button) => button.addEventListener("click", async () => {
        const output = points.querySelector("[data-points-explanation]");
        const detail = button.dataset.pointsExplain;
        button.disabled = true;
        output.textContent = "Preparing an evidence-based explanation...";
        try {
          const params = new URLSearchParams({ line: String(data.line), platform: data.platform || "Both", detail });
          const result = await api(`/api/players/${encodeURIComponent(data.player)}/points-explanation?${params}`, { method: "POST", timeoutMs: 15000 });
          if (result.status !== "research_only") {
            output.textContent = result.reason || "An explanation is unavailable for this line.";
          } else {
            const list = document.createElement("ul");
            result.bullets.forEach((fact) => { const item = document.createElement("li"); item.textContent = fact; list.append(item); });
            output.replaceChildren(list);
            const note = document.createElement("p");
            note.textContent = result.source === "ollama_prioritized" ? "Ollama ordered verified facts; EdgeIQ supplied the calculations." : "EdgeIQ used verified facts without Ollama.";
            output.append(note);
          }
        } catch (_error) {
          output.textContent = "The explanation could not be prepared right now. Try again later.";
        } finally {
          button.disabled = false;
        }
      }));
      points.querySelector("[data-points-validation]")?.addEventListener("click", async (event) => {
        const button = event.currentTarget;
        const output = points.querySelector("[data-points-validation-result]");
        button.disabled = true;
        output.textContent = "Checking independently settled, pregame NBA points forecasts...";
        try {
          const report = await api("/api/research/nba-points-validation", { timeoutMs: 20000 });
          if (!report.eligible_independent) {
            output.textContent = "No independently settled NBA points forecasts pass the pregame evidence checks yet. This does not validate the current model.";
          } else {
            const summary = document.createElement("p");
            summary.textContent = `${report.eligible_independent} independent NBA points outcomes. ${report.evidence_maturity === "exploratory" ? "Small sample; these metrics do not validate accuracy." : "Initial evaluation only."}`;
            const versions = document.createElement("ul");
            (report.versions || []).forEach((row) => {
              const item = document.createElement("li");
              item.textContent = `${row.model_version}: ${row.metrics.samples} settled · forecast MAE ${number(row.metrics.mae)} · exact-line MAE ${number(row.paired_baselines?.exact_line?.mae)} · Brier ${row.metrics.brier ?? "unavailable"}`;
              versions.append(item);
            });
            const caution = document.createElement("p");
            caution.textContent = report.challenger_comparison?.reason || "Challenger comparison unavailable.";
            output.replaceChildren(summary, versions, caution);
          }
        } catch (_error) {
          output.textContent = "The locked model record could not be loaded right now. Try again later.";
        } finally {
          button.disabled = false;
        }
      });
      header.after(points);
    }
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
    const labels = ["Overview", ...(data.nba_points_intelligence ? ["Points Intelligence"] : []), "Recent Form", "Projection", "Matchup", "Game Logs", "Best Lines", "Evidence", "Model Performance"];
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
