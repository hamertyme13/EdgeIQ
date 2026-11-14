(() => {
  function lockedModelSummary(report) {
    const excluded = Number(report.excluded_by_origin?.prospective_board?.market_prior_only || 0);
    const marketPriorNote = excluded > 0
      ? `${excluded} settled board forecast${excluded === 1 ? "" : "s"} used a market prior and ${excluded === 1 ? "is" : "are"} excluded from model accuracy. A history-based forecast needs five verified regular-season games for that player.`
      : "";
    const lateHistory = Number(report.excluded?.history_imported_after_lock || 0);
    const invalidHistory = Number(report.excluded?.invalid_history_import_time || 0);
    const historyNote = lateHistory || invalidHistory
      ? `${lateHistory + invalidHistory} forecast${lateHistory + invalidHistory === 1 ? "" : "s"} excluded because stored history import timing was after the prediction lock or invalid.`
      : "";
    if (!report.eligible_independent) {
      return `No independently settled NBA points forecasts pass the pregame evidence checks yet. This does not validate the current model.${marketPriorNote ? ` ${marketPriorNote}` : ""}${historyNote ? ` ${historyNote}` : ""}`;
    }
    const origins = report.evidence_origins || {};
    return `${report.eligible_independent} distinct NBA points player-game outcomes (${origins.prospective_board || 0} from prospective board cohorts, ${origins.placed_entry || 0} from placed entries; overlap counts once in the total). ${report.pregame_provenance_verified_independent || 0} have verified history-import timing across ${report.pregame_provenance_verified_game_dates || 0} game dates. ${report.evidence_maturity === "exploratory" ? "The evidence is still exploratory; these metrics do not validate accuracy." : "Initial evaluation only."} Board coverage may be incomplete when providers are stale or a scan is truncated.${marketPriorNote ? ` ${marketPriorNote}` : ""}${historyNote ? ` ${historyNote}` : ""}`;
  }

  function verifiedLineComparisonSummary(comparison) {
    if (comparison?.status !== "exploratory_paired_comparison") return "";
    const difference = Number(comparison.mae_advantage_points);
    const direction = difference < 0 ? "trailed" : difference > 0 ? "beat" : "matched";
    const uncertain = comparison.date_block_interval_95?.[0] <= 0
      && comparison.date_block_interval_95?.[1] >= 0;
    return `Same-offer check across ${comparison.samples} verified outcomes: the forecast ${direction} the exact line by ${Math.abs(difference).toFixed(1)} points of MAE. ${uncertain ? "The difference is uncertain across game dates. " : ""}This is not a later-game holdout or a paid-model release decision.`;
  }

  function namedBookPriceSummary(market) {
    if (!market?.named_book_prices?.over || !market?.named_book_prices?.under) return "";
    const price = (side) => {
      const row = market.named_book_prices[side];
      const odds = Number(row.american_odds);
      return `${side === "over" ? "Over" : "Under"} ${odds > 0 ? "+" : ""}${odds} at ${row.bookmaker} (break-even ${Number(row.break_even_probability).toFixed(1)}%)`;
    };
    return `Best named external prices: ${price("over")}; ${price("under")}. These are sportsbook prices, not PrizePicks or Underdog payouts.`;
  }

  function mount(root, data, { escapeHtml: escape, pct, formatDateTime, api }) {
    const exact = data.recommendation && data.recommendation.line === data.line;
    const prop = exact ? data.recommendation : {};
    const number = (v) => v != null && Number.isFinite(Number(v)) ? Number(v).toFixed(1) : "Unavailable";
    const researchProjection = data.nba_points_intelligence?.projection;
    const verifiedResearch = researchProjection?.source === "verified_history_distribution"
      && researchProjection.expected_points != null;
    const fresh = data.edgeiq_score_freshness?.status === "fresh";
    const paid = exact && fresh && prop.forecast_paid_eligible === true && prop.recommendation_eligibility?.paid_ready === true;
    const teamContext = data.team_context || {};
    const teamFromFinal = !prop.team && teamContext.source === "latest_verified_final";
    const teamLabel = teamFromFinal ? "Last recorded team" : "Team";
    const teamValue = prop.team || (teamFromFinal
      ? `${teamContext.team} · verified final ${teamContext.as_of}` : teamContext.team);
    const fields = [["Exact offer", exact ? `${prop.platform} ${prop.direction} ${number(prop.line)}` : "No current exact-line offer"],
      ["EdgeIQ score", data.edgeiq_score?.score == null ? "Unavailable" : number(data.edgeiq_score.score)],
      ["Hit probability", prop.confidence == null ? "No exact-line recommendation" : pct(prop.confidence)],
      ["Projection", number(prop.projection)],
      ["Evidence", exact && fresh ? "Current exact-line offer" : !exact && data.nba_points_intelligence?.sample_size
        ? "Verified historical finals; no current exact-line offer" : "Stale or unverified"]];
    const contextFields = [[teamLabel, teamValue], ["Opponent", data.opponent || "No current matching offer"],
      ["Game time", prop.game_time ? formatDateTime(prop.game_time) : "No current matching offer"],
      ["Stat", data.stat], ["Research line", number(data.line)], ["Model edge", number(prop.edge)],
      ["Direction", prop.direction || "No exact-line recommendation"],
      ...(verifiedResearch ? [["Research projection", `${number(researchProjection.expected_points)} points`],
        ["Research Over chance", researchProjection.over_probability == null ? "Unavailable" : pct(researchProjection.over_probability)],
        ["Research Under chance", researchProjection.under_probability == null ? "Unavailable" : pct(researchProjection.under_probability)]] : [])];
    const header = document.createElement("section");
    header.className = "player-workspace-overview";
    header.innerHTML = `<h3>${escape(data.player)} <small>${escape(data.sport)}</small></h3>
      <p>${paid ? "Paid-use evidence gates passed; confirm the offer before placing." : "Research only: paid-use evidence has not been confirmed for this exact line."}</p>
      <dl>${fields.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value ?? "Unavailable")}</dd></div>`).join("")}</dl>
      <details><summary>Player and model context</summary><dl>${contextFields.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value ?? "Unavailable")}</dd></div>`).join("")}</dl></details>
      ${!exact ? `<p class="subtle">No exact offer matches this selection. Choose a current provider line or refresh provider data; historical hit rates are not forecast probabilities.</p>` : ""}`;
    root.prepend(header);
    if (data.nba_points_intelligence) {
      const intelligence = data.nba_points_intelligence;
      const points = document.createElement("details");
      points.className = "consumer-research-section nba-points-intelligence";
      points.open = true;
      const windows = [["last_5", "Last 5"], ["last_10", "Last 10"], ["last_20", "Last 20"], ["verified_season", "Verified season"], ["season", "Tracked window"], ["home", "Home"], ["away", "Away"], ["opponent", `Vs ${intelligence.matchup?.opponent || "opponent"}`]];
      const renderWindow = (key) => {
        const windowData = intelligence.thresholds?.[key] || {};
        const custom = windowData.custom_line;
        const provenance = key === "verified_season"
          ? "confirmed regular-season games only"
          : `${windowData.unverified_games || 0} with season type unverified`;
        return `<p class="subtle">${windowData.games || 0} final-score games · ${provenance} · historical results, not next-game probability</p>
          ${windowData.games ? `
          <div class="nba-points-thresholds">${(windowData.thresholds || []).map((row) => `<div class="nba-points-threshold">
            <strong>${row.points}+ points</strong><span>${row.hits}/${row.decisions ?? row.games} decided · ${row.hit_rate == null ? "Unavailable" : pct(row.hit_rate)}</span>
            <span class="nba-points-meter" aria-hidden="true"><i style="width:${Math.max(0, Math.min(100, Number(row.hit_rate) || 0))}%"></i></span>
            <details><summary>History detail</summary><p>Average ${number(row.average)} · Median ${number(row.median)} · SD ${number(row.standard_deviation)}</p>
              <p>${row.pushes || 0} pushes · 95% historical hit-rate interval ${row.interval_95 ? `${row.interval_95[0]}–${row.interval_95[1]}%` : "unavailable"}</p></details>
          </div>`).join("")}</div>
          ${custom ? `<p class="nba-points-custom">Over ${number(data.line)}: ${custom.hits}/${custom.decisions} decisions${custom.pushes ? ` · ${custom.pushes} pushes` : ""} · ${custom.hit_rate == null ? "Unavailable" : pct(custom.hit_rate)} historical hit rate${custom.interval_95 ? ` · 95% range ${custom.interval_95[0]}–${custom.interval_95[1]}%` : ""}</p>
          <p class="subtle">Average ${custom.average ?? "-"} · Median ${custom.median ?? "-"} · Standard deviation ${custom.standard_deviation ?? "-"}</p>` : ""}` : `<p class="subtle">No verified final-score games in this view yet.</p>`}`;
      };
      points.innerHTML = `<summary>NBA Points Intelligence <span class="status-pill ${intelligence.data_quality === "Developing" ? "status-positive" : "status-warning"}">${escape(intelligence.data_quality || "Unavailable")}</span></summary>
        <div class="nba-points-content">
          <p>${escape(intelligence.explanation || "")}</p>
          ${Object.entries(intelligence.data_reliability?.excluded || {}).some(([key, count]) => key !== "matching_duplicate" && count > 0)
            ? `<p class="subtle">Data review: ${Object.entries(intelligence.data_reliability.excluded).filter(([key, count]) => key !== "matching_duplicate" && count > 0).map(([key, count]) => `${count} ${escape(key.replaceAll("_", " "))}`).join(" · ")} withheld from scoring history.</p>`
            : ""}
          <label class="nba-points-window">Scoring history
            <select data-points-window aria-label="Scoring history view">${windows.map(([key, label]) => `<option value="${key}">${escape(label)}</option>`).join("")}</select>
          </label>
          <div class="nba-points-window-results" aria-live="polite">${renderWindow("last_5")}</div>
          <div class="nba-points-evidence">
            <p><strong>Forecast:</strong> ${intelligence.projection?.expected_points == null ? "Not validated" : `${number(intelligence.projection.expected_points)} points`} · Over ${intelligence.projection?.over_probability == null ? "unavailable" : pct(intelligence.projection.over_probability)} · Under ${intelligence.projection?.under_probability == null ? "unavailable" : pct(intelligence.projection.under_probability)}</p>
            <details class="nba-points-uncertainty"><summary>Scoring range and uncertainty</summary>
              ${intelligence.projection?.observed_scoring_spread ? `<p>Last ${number(intelligence.projection.observed_scoring_spread.sample_size)} modeled games: middle half ${number(intelligence.projection.observed_scoring_spread.p25)}–${number(intelligence.projection.observed_scoring_spread.p75)} points · wider observed range ${number(intelligence.projection.observed_scoring_spread.p10)}–${number(intelligence.projection.observed_scoring_spread.p90)} points.</p>
                <p class="subtle">${escape(intelligence.projection.observed_scoring_spread.label)}</p>` : `<p class="subtle">A verified recent scoring spread is unavailable.</p>`}
              <p class="subtle">Model uncertainty: ${escape(intelligence.projection?.uncertainty_level || "Not assessed")}. ${escape((intelligence.projection?.uncertainty_drivers || []).join(" · "))}</p>
            </details>
            ${intelligence.projection?.note?.includes("stored finals disagree") ? `<p class="subtle">${escape(intelligence.projection.note)}</p>` : ""}
            <p><strong>Minutes-based challenger (research only):</strong> ${intelligence.minutes_challenger?.expected_points == null
              ? `Unavailable · ${intelligence.minutes_challenger?.sample_size || 0}/5 verified regular-season games with minutes`
              : `${number(intelligence.minutes_challenger.expected_points)} points from ${number(intelligence.minutes_challenger.expected_minutes)} expected minutes and ${number(intelligence.minutes_challenger.points_per_minute)} points per minute`}. No probability or EV is inferred.</p>
            ${intelligence.minutes_challenger?.validation?.evaluated_games
              ? `<p class="subtle">Minutes challenger: ${intelligence.minutes_challenger.validation.evaluated_games} chronological tests · MAE ${number(intelligence.minutes_challenger.validation.challenger?.mae)} points vs recent-points average ${number(intelligence.minutes_challenger.validation.recent_points_average?.mae)}. This does not replace the current forecast.</p>`
              : ""}
            <p><strong>Shot-volume baseline (research only):</strong> ${intelligence.shot_volume_challenger?.expected_points == null
              ? `Unavailable · ${intelligence.shot_volume_challenger?.sample_size || 0}/5 verified regular-season games with field-goal and free-throw attempts`
              : `${number(intelligence.shot_volume_challenger.expected_points)} points from ${number(intelligence.shot_volume_challenger.expected_attempts)} expected recorded attempts`}. Field-goal plus free-throw attempts are a volume proxy, not possessions; no probability or EV is inferred.</p>
            ${intelligence.shot_volume_challenger?.validation?.evaluated_games
              ? `<p class="subtle">Shot-volume baseline: ${intelligence.shot_volume_challenger.validation.evaluated_games} chronological tests · MAE ${number(intelligence.shot_volume_challenger.validation.challenger?.mae)} points vs recent-points average ${number(intelligence.shot_volume_challenger.validation.recent_points_average?.mae)}. It does not replace the current forecast.</p>`
              : ""}
            <p><strong>Matchup:</strong> ${escape(intelligence.matchup?.status || "Unverified")} ${intelligence.matchup?.head_to_head_games || 0} verified games vs ${escape(intelligence.matchup?.opponent || "selected opponent")}.</p>
            <p><strong>Opponent team defense:</strong> ${intelligence.matchup?.team_points_allowed?.sample_size
              ? `Last 5: ${number(intelligence.matchup.team_points_allowed.last_5)} · Last 10: ${number(intelligence.matchup.team_points_allowed.last_10)} · Last 20: ${number(intelligence.matchup.team_points_allowed.last_20)} points allowed per game (up to ${Math.min(20, intelligence.matchup.team_points_allowed.sample_size)} verified games). ${intelligence.matchup.team_points_allowed.league_average == null ? "Comparable league average unavailable." : `Comparable league average: ${number(intelligence.matchup.team_points_allowed.league_average)}.`} ${escape(intelligence.matchup.team_points_allowed.status)}`
              : "Verified pregame team finals unavailable."}</p>
            ${intelligence.matchup?.team_points_allowed?.sample_size
              ? `<p class="subtle"><strong>Opponent location splits:</strong> Home ${intelligence.matchup.team_points_allowed.home_sample_size ? `${number(intelligence.matchup.team_points_allowed.home_points_allowed_last_10)} allowed in ${Math.min(10, intelligence.matchup.team_points_allowed.home_sample_size)} game${Math.min(10, intelligence.matchup.team_points_allowed.home_sample_size) === 1 ? "" : "s"}` : "unavailable"} · Away ${intelligence.matchup.team_points_allowed.away_sample_size ? `${number(intelligence.matchup.team_points_allowed.away_points_allowed_last_10)} allowed in ${Math.min(10, intelligence.matchup.team_points_allowed.away_sample_size)} game${Math.min(10, intelligence.matchup.team_points_allowed.away_sample_size) === 1 ? "" : "s"}` : "unavailable"}. ${intelligence.matchup.team_points_allowed.days_rest == null ? "Rest unavailable." : `${intelligence.matchup.team_points_allowed.days_rest} full rest day${intelligence.matchup.team_points_allowed.days_rest === 1 ? "" : "s"} before this game.`} Descriptive team context only.</p>`
              : ""}
            ${intelligence.matchup?.defensive_rank != null
              ? `<p><strong>Team defense comparison:</strong> Rank ${number(intelligence.matchup.defensive_rank)} of ${number(intelligence.matchup.team_points_allowed.ranked_teams)} qualifying teams (1 allows the fewest points) · matchup indicator ${number(intelligence.matchup.advantage_score)}/100.${intelligence.matchup.team_points_allowed.bottom_ten_defense === true ? " Bottom 10 among all 30 NBA teams." : ""} Based on each team's last 10 official regular-season games, with at least ${number(intelligence.matchup.team_points_allowed.minimum_team_games)} per team. This is a descriptive percentile, not a player hit probability or betting edge.</p>`
              : `<p class="subtle">Team defense ranking unavailable: ${intelligence.matchup?.team_points_allowed?.rank_unavailable_reason === "opponent_sample"
                ? `the selected opponent needs at least ${number(intelligence.matchup?.team_points_allowed?.minimum_team_games || 5)} comparable verified games and an unambiguous team identity.`
                : `${number(intelligence.matchup?.team_points_allowed?.ranked_teams || 0)} teams have at least ${number(intelligence.matchup?.team_points_allowed?.minimum_team_games || 5)} verified games; 10 are required.`}</p>`}
            <p><strong>Opponent game pace:</strong> ${intelligence.matchup?.team_points_allowed?.pace_sample_size
              ? `${number(intelligence.matchup.team_points_allowed.pace_last_5)} estimated possessions per regulation game across ${Math.min(5, intelligence.matchup.team_points_allowed.pace_sample_size)} recent official box scores. Descriptive only; not a player projection adjustment.`
              : "Verified box-score possessions unavailable."}</p>
            <p><strong>Opponent shooting allowed:</strong> ${intelligence.matchup?.team_points_allowed?.shooting_allowed?.status === "descriptive_official_box_scores"
              ? `${number(intelligence.matchup.team_points_allowed.shooting_allowed.three_point_pct)}% on opponent three-point attempts · ${number(intelligence.matchup.team_points_allowed.shooting_allowed.three_pointers_made_per_game)} threes made · ${number(intelligence.matchup.team_points_allowed.shooting_allowed.paint_points_per_game)} paint points per game over ${number(intelligence.matchup.team_points_allowed.shooting_allowed.sample_size)} official box scores. Team context only; not position-specific defense or a player probability.`
              : "At least five complete official team shooting box scores are needed; position-specific defense remains unverified."}</p>
            ${intelligence.matchup?.team_points_allowed?.pace_comparison?.status === "descriptive_comparison"
              ? `<p><strong>League pace comparison:</strong> Opponent ${number(intelligence.matchup.team_points_allowed.pace_comparison.opponent_pace_last_5)} vs ${number(intelligence.matchup.team_points_allowed.pace_comparison.league_pace_average)} possessions for qualifying teams · rank ${Number(intelligence.matchup.team_points_allowed.pace_comparison.pace_rank_fastest_first)} of ${Number(intelligence.matchup.team_points_allowed.pace_comparison.ranked_teams)} (1 fastest). Five complete pregame box scores per team required. Descriptive only; no player probability or projection adjustment.</p>`
              : ""}
            ${intelligence.matchup?.opponent_injuries?.status === "reported"
              ? `<details><summary>${intelligence.matchup.opponent_injuries.reports.length} opponent injury report${intelligence.matchup.opponent_injuries.reports.length === 1 ? "" : "s"} · ESPN feed</summary><ul>${intelligence.matchup.opponent_injuries.reports.map((row) => `<li>${escape(row.player)}: ${escape(row.status)}</li>`).join("")}</ul><p class="subtle">Retrieved ${formatDateTime(intelligence.matchup.opponent_injuries.retrieved_at)}. Reported availability only; lineup and scoring impact are not confirmed.</p></details>`
              : `<p class="subtle">Current opponent injury reports unavailable; this does not confirm a healthy lineup.</p>`}
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
            <p class="subtle">Chronological check: ${intelligence.validation?.evaluated_games ? `${intelligence.validation.evaluated_games} later verified regular-season games · prior-five average MAE ${number(intelligence.validation.baselines?.prior_5_average?.mae)} points · prior-to-game season average MAE ${number(intelligence.validation.baselines?.prior_season_average?.mae)} points` : escape(intelligence.validation?.status || "Unavailable")} · This is a baseline check, not model validation.</p>
            <button type="button" class="secondary" data-points-validation>View locked model record</button>
            <div class="subtle" data-points-validation-result aria-live="polite"></div>
            <button type="button" class="secondary" data-points-quote-validation>Audit saved market quotes</button>
            <div class="subtle" data-points-quote-validation-result aria-live="polite"></div>
          </div>
        </div>`;
      points.querySelector("[data-points-window]").addEventListener("change", (event) => {
        points.querySelector(".nba-points-window-results").innerHTML = renderWindow(event.currentTarget.value);
      });
      points.querySelector("[data-points-market-check]")?.addEventListener("click", async (event) => {
        const button = event.currentTarget;
        const output = points.querySelector("[data-points-market-result]");
        button.disabled = true;
        output.textContent = "Checking paired Over and Under prices for this exact line...";
        try {
          const params = new URLSearchParams({ line: String(data.line), platform: data.platform || "Both" });
          const market = await api(`/api/players/${encodeURIComponent(data.player)}/points-market?${params}`);
          output.textContent = market.status === "research_comparison"
            ? `External books: Over ${number(market.market_over_probability)}%, Under ${number(market.market_under_probability)}% no-vig across ${market.book_count} book(s), oldest quote ${formatDateTime(market.oldest_update)}. ${market.model_over_probability == null ? "A comparable model probability is unavailable." : `EdgeIQ forecast: ${number(market.model_over_probability)}% Over; difference ${number(market.model_market_gap)} percentage points.`} ${market.capture_status === "captured" ? "Quote saved for later research." : market.capture_status === "failed" ? "Quote could not be saved for later research." : "Quote was not saved."} No validated EV or DFS payout is claimed.`
            : market.reason || "Exact-line market data is unavailable.";
          const namedPrices = market.status === "research_comparison" ? namedBookPriceSummary(market) : "";
          if (namedPrices) {
            const price = document.createElement("p");
            price.textContent = namedPrices;
            output.append(price);
          }
          if (market.status === "research_comparison" && market.quote_history_status === "available") {
            const history = document.createElement("p");
            history.textContent = market.market_over_movement_points == null
              ? "One saved quote for this exact player, game, platform, and line; movement is not available yet."
              : `${market.quote_history.length} saved quotes for this exact offer: external no-vig Over probability moved ${number(market.market_over_movement_points)} percentage points between the first and latest snapshots. This is not closing-line value or an EdgeIQ edge.`;
            output.append(history);
          }
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
            const facts = result.fact_details || result.bullets.map((text) => ({ text }));
            facts.forEach((fact) => {
              const item = document.createElement("li");
              item.textContent = fact.text;
              if (fact.evidence) {
                const source = document.createElement("small");
                source.textContent = `Evidence: ${fact.evidence}`;
                item.append(document.createElement("br"), source);
              }
              (fact.source_links || []).forEach((link) => {
                try {
                  const url = new URL(link.url);
                  if (url.protocol !== "https:" || url.host !== "www.espn.com" ||
                      !/^\/game\/_\/gameId\/[A-Za-z0-9-]+$/.test(url.pathname) || url.search || url.hash) return;
                  const anchor = document.createElement("a");
                  anchor.href = url.href;
                  anchor.target = "_blank";
                  anchor.rel = "noopener noreferrer";
                  anchor.textContent = link.label || "Official game";
                  item.append(document.createTextNode(" · "), anchor);
                } catch (_error) {
                  // Invalid evidence URLs remain plain source labels.
                }
              });
              if (Array.isArray(fact.source_records) && fact.source_records.length) {
                const records = document.createElement("details");
                const label = document.createElement("summary");
                label.textContent = `${fact.source_records.length} verified final records`;
                const recordList = document.createElement("ul");
                fact.source_records.slice(0, 5).forEach((record) => {
                  const recordItem = document.createElement("li");
                  recordItem.textContent = `${record.game_date || "Date unavailable"} · ${record.game || "Matchup unavailable"} · ${number(record.points)} points · ${record.source || "Source unavailable"}`;
                  recordList.append(recordItem);
                });
                records.append(label, recordList);
                item.append(records);
              }
              list.append(item);
            });
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
            output.textContent = lockedModelSummary(report);
          } else {
            const summary = document.createElement("p");
            summary.textContent = lockedModelSummary(report);
            const versions = document.createElement("ul");
            (report.versions || []).forEach((row) => {
              const item = document.createElement("li");
              const verified = row.verified_pregame_metrics || {};
              item.textContent = verified.samples
                ? `${row.model_version}: ${verified.samples} pregame-verified outcomes · forecast MAE ${number(verified.mae)} · exact-line MAE ${number(row.verified_pregame_paired_baselines?.exact_line?.mae)} · Brier ${verified.brier ?? "unavailable"}. Descriptive only until later-game holdout passes.`
                : `${row.model_version}: no outcomes with verified pregame history timing yet; accuracy is unavailable.`;
              versions.append(item);
              const lineComparison = row.verified_pregame_paired_comparison?.exact_line || {};
              if (lineComparison.status === "exploratory_paired_comparison") {
                const comparison = document.createElement("li");
                comparison.textContent = verifiedLineComparisonSummary(lineComparison);
                versions.append(comparison);
              }
              if (row.metrics?.samples > (verified.samples || 0)) {
                const older = document.createElement("li");
                older.textContent = `${row.metrics.samples - (verified.samples || 0)} additional settled outcomes have unverified history timing and are excluded from the headline accuracy metrics.`;
                versions.append(older);
              }
              const range = row.observed_range_audit || {};
              if (range.samples) {
                const rangeItem = document.createElement("li");
                rangeItem.textContent = `Locked scoring-range audit: ${range.middle_half_hits}/${range.samples} finals inside the stored middle half; ${range.wider_range_hits}/${range.samples} inside the wider observed range. Historical-range coverage only, not a calibrated prediction interval.`;
                versions.append(rangeItem);
              }
              const provenance = row.history_import_provenance || {};
              if (Object.keys(provenance).length) {
                const provenanceItem = document.createElement("li");
                provenanceItem.textContent = `History timing: ${provenance.verified || 0} import-verified · ${provenance.timestamp_unverified || 0} missing timestamps · ${provenance.legacy_unrecorded || 0} older forecasts without a recorded provenance check. Missing or older timestamps do not prove pregame availability.`;
                versions.append(provenanceItem);
              }
              Object.entries(row.by_evidence_origin || {}).forEach(([origin, segment]) => {
                const originItem = document.createElement("li");
                const metrics = segment.verified_pregame_metrics || {};
                originItem.textContent = `${origin === "prospective_board" ? "Board cohort" : "Placed entries"}: ${metrics.samples || 0} of ${segment.metrics.samples} settled have verified pregame history timing${metrics.samples ? ` · forecast MAE ${number(metrics.mae)} · Brier ${metrics.brier ?? "unavailable"}` : " · accuracy unavailable"}.`;
                versions.append(originItem);
              });
              ["prospective_board", "placed_entry"].forEach((origin) => {
                const calibration = row.calibration_by_origin?.[origin];
                if (!calibration) return;
                const item = document.createElement("li");
                const details = document.createElement("details");
                const summary = document.createElement("summary");
                summary.textContent = `${origin === "prospective_board" ? "Board" : "Placed-entry"} confidence buckets · ${calibration.samples} import-verified settled`;
                const list = document.createElement("ul");
                if (!calibration.buckets?.length) {
                  const empty = document.createElement("li");
                  empty.textContent = "No import-verified outcomes to evaluate yet.";
                  list.append(empty);
                }
                (calibration.buckets || []).forEach((bucket) => {
                  const bucketItem = document.createElement("li");
                  const observedRange = bucket.actual_hit_interval_95;
                  bucketItem.textContent = `${bucket.label}: ${bucket.wins}/${bucket.samples} hit · predicted ${number(bucket.predicted_hit_rate)}% · observed ${number(bucket.actual_hit_rate)}%${observedRange ? ` (95% observed-rate range ${observedRange[0]}–${observedRange[1]}%)` : ""}. Historical calibration, not next-game certainty.`;
                  list.append(bucketItem);
                });
                if (calibration.excluded_unverified_history_timing) {
                  const excluded = document.createElement("li");
                  excluded.textContent = `${calibration.excluded_unverified_history_timing} outcome(s) excluded because history-import timing was not verified.`;
                  list.append(excluded);
                }
                details.append(summary, list);
                item.append(details);
                versions.append(item);
              });
              if (row.by_evidence_origin?.prospective_board) {
                const interval = row.chronological_interval || {};
                const intervalItem = document.createElement("li");
                intervalItem.textContent = interval.status === "exploratory_chronological"
                  ? `Research-only ${interval.target_coverage_pct}% interval check: ${interval.inside}/${interval.evaluated} later board finals inside intervals built from earlier dated errors; observed coverage ${interval.coverage_pct}%, average width ${number(interval.average_width)} points. Not a next-game guarantee or model promotion.`
                  : interval.status === "insufficient_later_games"
                    ? `Interval coverage is not shown yet: ${interval.evaluated || 0}/${interval.minimum_evaluation || 10} later board finals across ${interval.evaluated_game_dates || 0}/${interval.minimum_test_dates || 2} later game dates. Earlier dated errors are available, but this test sample is too small.`
                  : `Research-only interval check unavailable: ${interval.eligible_samples || 0} import-verified board finals across ${interval.game_dates || 0} dates; at least ${interval.minimum_calibration || 30} earlier finals across ${interval.minimum_dates || 5} dates are needed before evaluation.`;
                versions.append(intervalItem);
                const holdout = row.chronological_board_holdout || {};
                const holdoutItem = document.createElement("li");
                holdoutItem.textContent = holdout.status === "exploratory_holdout"
                  ? `Later-game board check from ${holdout.cutoff_game_date}: ${holdout.later_samples} offers · forecast MAE ${number(holdout.forecast?.mae)} · recent-five MAE ${number(holdout.locked_recent_5_mean?.mae)} · line MAE ${number(holdout.exact_line?.mae)} · Brier ${holdout.forecast?.brier ?? "unavailable"}.${holdout.paired_minutes?.samples ? ` On ${holdout.paired_minutes.samples} paired offers: forecast MAE ${number(holdout.paired_minutes.champion?.mae)}, minutes MAE ${number(holdout.paired_minutes.minutes_shadow?.mae)}.` : " No paired minutes forecast yet."} Exploratory only; no model promotion.`
                  : `Later-game board check unavailable: ${holdout.reason || "More settled board games are needed."}`;
                if (holdout.forecast_vs_exact_line?.status === "line_lower_error") {
                  holdoutItem.textContent += ` The exact line had ${number(holdout.forecast_vs_exact_line.mae_difference_points)} fewer points of MAE on these same offers; this challenger has not beaten the line baseline.`;
                }
                if (holdout.excluded_unverified_history_timing) {
                  holdoutItem.textContent += ` ${holdout.excluded_unverified_history_timing} board forecasts were withheld because pregame history timing was not verified.`;
                }
                if (holdout.status === "exploratory_holdout" && holdout.paired_shot_volume?.samples) {
                  holdoutItem.textContent += ` On ${holdout.paired_shot_volume.samples} same-offer shot-volume forecasts: current forecast MAE ${number(holdout.paired_shot_volume.champion?.mae)}, shot-volume MAE ${number(holdout.paired_shot_volume.shot_volume_shadow?.mae)}. Research only.`;
                }
                if (holdout.observed_range_audit?.samples) {
                  const range = holdout.observed_range_audit;
                  holdoutItem.textContent += ` Later-game observed-range coverage: ${range.wider_range_hits}/${range.samples}. Not a calibrated prediction interval.`;
                }
                versions.append(holdoutItem);
                Object.entries(holdout.shadow_uncertainty || {}).forEach(([name, baselines]) => {
                  const comparison = baselines?.projection;
                  if (!comparison?.samples) return;
                  const evidenceItem = document.createElement("li");
                  evidenceItem.textContent = comparison.status === "exploratory_paired_comparison"
                    ? `${name === "shot_volume" ? "Shot-volume" : "Minutes"} challenger vs current forecast on the same later board offers: ${comparison.samples} outcomes across ${comparison.game_dates} dates; MAE advantage ${number(comparison.mae_advantage_points)} points (date-block 95% range ${number(comparison.date_block_interval_95?.[0])} to ${number(comparison.date_block_interval_95?.[1])}). ${baselines.recent_5_mean?.status === "exploratory_paired_comparison" ? `Vs recent-five average: ${number(baselines.recent_5_mean.mae_advantage_points)} points. ` : ""}${baselines.line?.status === "exploratory_paired_comparison" ? `Vs exact line: ${number(baselines.line.mae_advantage_points)} points. ` : ""}Projection error only; no probability validation or promotion.`
                    : `${name === "shot_volume" ? "Shot-volume" : "Minutes"} challenger comparison needs ${comparison.minimum_samples} import-verified paired board outcomes across ${comparison.minimum_dates} later game dates; currently ${comparison.samples} across ${comparison.game_dates}.`;
                  versions.append(evidenceItem);
                });
              }
              if (row.matchup_difficulty?.samples) {
                const matchupItem = document.createElement("li");
                matchupItem.textContent = `Pregame team-defense comparison: ${row.matchup_difficulty.samples} settled offers with locked evidence. ${row.matchup_difficulty.segments.map((segment) => `${segment.label}: ${segment.samples} · forecast MAE ${number(segment.mae)} · Brier ${segment.brier ?? "unavailable"}`).join("; ")}. Descriptive segments only; no validated matchup effect.`;
                versions.append(matchupItem);
              }
            });
            const caution = document.createElement("p");
            caution.textContent = report.challenger_comparison?.reason || "Challenger comparison unavailable.";
            output.replaceChildren(summary, versions, caution);
            const paired = report.challenger_comparison?.versions || [];
            if (paired.length) {
              const comparisons = document.createElement("ul");
              paired.forEach((row) => {
                const item = document.createElement("li");
                item.textContent = row.samples
                  ? `${row.model_version}: ${row.samples} verified pregame board offers · current forecast MAE ${number(row.champion?.mae)} · minutes MAE ${number(row.minutes_shadow?.mae)} · line MAE ${number(row.exact_line?.mae)}. ${row.minutes_vs_champion?.date_block_interval_95?.[0] <= 0 && row.minutes_vs_champion?.date_block_interval_95?.[1] >= 0 ? "The minutes difference is uncertain across game dates. " : ""}Research only; later-game holdout required.`
                  : `${row.model_version}: no paired minutes forecasts yet`;
                comparisons.append(item);
                if (row.shot_volume?.samples) {
                  const volumeItem = document.createElement("li");
                  volumeItem.textContent = `${row.model_version}: ${row.shot_volume.samples} verified pregame board offers · current forecast MAE ${number(row.shot_volume.champion?.mae)} · shot-volume MAE ${number(row.shot_volume.shot_volume_shadow?.mae)} · line MAE ${number(row.shot_volume.exact_line?.mae)}. ${row.shot_volume.vs_champion?.date_block_interval_95?.[0] <= 0 && row.shot_volume.vs_champion?.date_block_interval_95?.[1] >= 0 ? "The shot-volume difference is uncertain across game dates. " : ""}Research only; later-game holdout required.`;
                  comparisons.append(volumeItem);
                }
              });
              output.append(comparisons);
            }
          }
        } catch (_error) {
          output.textContent = "The locked model record could not be loaded right now. Try again later.";
        } finally {
          button.disabled = false;
        }
      });
      points.querySelector("[data-points-quote-validation]")?.addEventListener("click", async (event) => {
        const button = event.currentTarget;
        const output = points.querySelector("[data-points-quote-validation-result]");
        button.disabled = true;
        output.textContent = "Checking saved pregame quotes against verified NBA Points finals...";
        try {
          const report = await api("/api/research/nba-points-quote-validation", { timeoutMs: 20000 });
          if (report.status === "unavailable") {
            output.textContent = report.reason || "The quote audit could not safely score its finals.";
          } else if (!report.eligible_independent) {
            output.textContent = `No saved quotes have an unambiguous, verified regular-season NBA Points final yet. ${report.examined || 0} recent quotes checked; this does not validate market or model accuracy.`;
          } else {
            const exclusions = Object.entries(report.excluded || {}).map(([reason, count]) => `${count} ${reason.replaceAll("_", " ")}`).join(" · ");
            output.replaceChildren();
            const summary = document.createElement("p");
            summary.textContent = `${report.eligible_independent} independent player-games from ${report.examined} saved quotes. External no-vig Brier ${report.market.brier}; predicted Over ${number(report.market.predicted_over_rate)}%, actual Over ${number(report.market.actual_over_rate)}%.`;
            output.append(summary);
            const list = document.createElement("ul");
            (report.versions || []).forEach((row) => {
              const item = document.createElement("li");
              item.textContent = `${row.model_version}: ${row.samples} paired games across ${row.game_dates} dates. EdgeIQ Brier ${row.model_brier} vs market ${row.market_brier}.${row.later_games ? ` Later games from ${row.later_games.from_game_date}: ${row.later_games.samples} games, EdgeIQ ${row.later_games.model_brier} vs market ${row.later_games.market_brier}.` : " Too few games for a later-games check."}`;
              list.append(item);
            });
            if (list.childElementCount) output.append(list);
            if ((report.paired_versions || []).length) {
              const heading = document.createElement("p");
              heading.textContent = "Same-game, same-line model comparisons";
              output.append(heading);
              const comparisons = document.createElement("ul");
              report.paired_versions.forEach((row) => {
                const item = document.createElement("li");
                item.textContent = `${row.first_version} vs ${row.second_version}: ${row.samples} shared player-games across ${row.game_dates} dates.${row.samples ? ` Brier ${row.first_brier} vs ${row.second_brier}.` : " No time-aligned comparisons yet."}${row.quote_time_mismatches ? ` ${row.quote_time_mismatches} line matches excluded because quotes were over 30 minutes apart.` : ""}${row.later_games ? ` Later games from ${row.later_games.from_game_date}: ${row.later_games.samples} games, Brier ${row.later_games.first_brier} vs ${row.later_games.second_brier}.` : row.samples ? " Too few shared games for a later-games check." : ""}`;
                comparisons.append(item);
              });
              output.append(comparisons);
            }
            const note = document.createElement("p");
            note.textContent = `${report.paired.samples ? `${report.paired.samples} paired games overall: EdgeIQ Brier ${report.paired.model_brier}, market Brier ${report.paired.market_brier}. ` : "No paired EdgeIQ probabilities yet. "}${report.quote_limit_reached ? "Only the latest bounded quote sample was checked. " : ""}Version summaries may cover different games; only the same-line comparison uses shared games. Selected research checks are not full-board validation or proof of a betting edge.${exclusions ? ` Excluded: ${exclusions}.` : ""}`;
            output.append(note);
          }
        } catch (_error) {
          output.textContent = "The saved quote audit could not be loaded right now. Try again later.";
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
    if (typeof root.querySelector !== "function") return;
    const groups = {
      Overview: [header, root.querySelector(".season-assessment"), root.querySelector(".research-distribution")?.closest("details")],
      Form: [root.querySelector(".nba-points-intelligence"), ...[...root.querySelectorAll(":scope > details.consumer-research-section")].filter((node) => /Recent Form|Game Logs/.test(node.querySelector(":scope > summary")?.textContent || ""))],
      Matchup: [...root.querySelectorAll(":scope > details.consumer-research-section")].filter((node) => /Matchup and Game Context/.test(node.querySelector(":scope > summary")?.textContent || "")),
      Market: [...root.querySelectorAll(":scope > details.consumer-research-section")].filter((node) => /Market and Recorded Lines/.test(node.querySelector(":scope > summary")?.textContent || "")),
      Evidence: [...root.querySelectorAll(":scope > details.consumer-research-section")].filter((node) => /Evidence and Limitations|Model Performance/.test(node.querySelector(":scope > summary")?.textContent || "")),
    };
    const nav = document.createElement("div");
    nav.className = "player-workspace-nav";
    nav.setAttribute("role", "tablist");
    nav.setAttribute("aria-label", "Player research views");
    Object.entries(groups).forEach(([label, nodes], index) => {
      const panel = document.createElement("section");
      panel.id = `research-panel-${label.toLowerCase()}`;
      panel.className = "player-workspace-panel";
      panel.setAttribute("role", "tabpanel");
      panel.hidden = index !== 0;
      nodes.filter(Boolean).forEach((node) => panel.append(node));
      const button = document.createElement("button");
      button.type = "button";
      button.className = "secondary";
      button.textContent = label;
      button.id = `research-tab-${label.toLowerCase()}`;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-controls", panel.id);
      button.setAttribute("aria-selected", String(index === 0));
      panel.setAttribute("aria-labelledby", button.id);
      button.addEventListener("click", () => {
        nav.querySelectorAll('[role="tab"]').forEach((tab) => tab.setAttribute("aria-selected", String(tab === button)));
        root.querySelectorAll(":scope > .player-workspace-panel").forEach((view) => { view.hidden = view !== panel; });
      });
      nav.append(button);
      root.append(panel);
    });
    root.prepend(nav);
  }
  window.EdgeIQPlayerWorkspace = { mount, lockedModelSummary, verifiedLineComparisonSummary, namedBookPriceSummary };
})();
