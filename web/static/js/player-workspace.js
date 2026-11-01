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

  function mount(root, data, { escapeHtml: escape, pct, formatDateTime, api }) {
    const exact = data.recommendation && data.recommendation.line === data.line;
    const prop = exact ? data.recommendation : {};
    const number = (v) => v != null && Number.isFinite(Number(v)) ? Number(v).toFixed(1) : "Unavailable";
    const fresh = data.edgeiq_score_freshness?.status === "fresh";
    const paid = exact && fresh && prop.forecast_paid_eligible === true && prop.recommendation_eligibility?.paid_ready === true;
    const teamContext = data.team_context || {};
    const teamFromFinal = !prop.team && teamContext.source === "latest_verified_final";
    const teamLabel = teamFromFinal ? "Last recorded team" : "Team";
    const teamValue = prop.team || (teamFromFinal
      ? `${teamContext.team} · verified final ${teamContext.as_of}` : teamContext.team);
    const fields = [[teamLabel, teamValue], ["Opponent", data.opponent || "No current matching offer"],
      ["Game time", prop.game_time ? formatDateTime(prop.game_time) : "No current matching offer"],
      ["Platform", exact ? prop.platform : data.platform], ["Stat", data.stat],
      ["Line", number(data.line)], ["Direction", prop.direction || "No exact-line recommendation"],
      ["Hit probability", prop.confidence == null ? "Unavailable" : pct(prop.confidence)],
      ["Projection", number(prop.projection)], ["Model edge", number(prop.edge)],
      ["Evidence", fresh ? "Current" : !exact && data.nba_points_intelligence?.sample_size
        ? "Verified historical finals; no current offer" : "Stale or unverified"]];
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
            <strong>${row.points}+ points</strong><span>${row.hits}/${row.games} · ${row.hit_rate == null ? "Unavailable" : pct(row.hit_rate)}</span>
            <span class="nba-points-meter"><i style="width:${Math.max(0, Math.min(100, Number(row.hit_rate) || 0))}%"></i></span>
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
              ? `${number(intelligence.matchup.team_points_allowed.last_10)} points allowed over ${Math.min(10, intelligence.matchup.team_points_allowed.sample_size)} recent games · league sample ${number(intelligence.matchup.team_points_allowed.league_average)} · ${escape(intelligence.matchup.team_points_allowed.status)}`
              : "Verified pregame team finals unavailable."}</p>
            ${intelligence.matchup?.defensive_rank != null
              ? `<p><strong>Team defense comparison:</strong> Rank ${number(intelligence.matchup.defensive_rank)} of ${number(intelligence.matchup.team_points_allowed.ranked_teams)} (1 allows the fewest points) · matchup indicator ${number(intelligence.matchup.advantage_score)}/100. Based on each team's last 10 official regular-season games, with at least ${number(intelligence.matchup.team_points_allowed.minimum_team_games)} per team. This is a descriptive percentile, not a player hit probability or betting edge.</p>`
              : `<p class="subtle">Team defense ranking unavailable: ${number(intelligence.matchup?.team_points_allowed?.ranked_teams || 0)} teams have at least ${number(intelligence.matchup?.team_points_allowed?.minimum_team_games || 5)} verified games; 10 are required.</p>`}
            <p><strong>Opponent game pace:</strong> ${intelligence.matchup?.team_points_allowed?.pace_sample_size
              ? `${number(intelligence.matchup.team_points_allowed.pace_last_5)} estimated possessions per regulation game across ${Math.min(5, intelligence.matchup.team_points_allowed.pace_sample_size)} recent official box scores. Descriptive only; not a player projection adjustment.`
              : "Verified box-score possessions unavailable."}</p>
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
              item.textContent = `${row.model_version}: ${row.metrics.samples} independent settled · forecast MAE ${number(row.metrics.mae)} · exact-line MAE ${number(row.paired_baselines?.exact_line?.mae)} · Brier ${row.metrics.brier ?? "unavailable"}`;
              versions.append(item);
              const provenance = row.history_import_provenance || {};
              if (Object.keys(provenance).length) {
                const provenanceItem = document.createElement("li");
                provenanceItem.textContent = `History timing: ${provenance.verified || 0} import-verified · ${provenance.timestamp_unverified || 0} missing timestamps · ${provenance.legacy_unrecorded || 0} older forecasts without a recorded provenance check. Missing or older timestamps do not prove pregame availability.`;
                versions.append(provenanceItem);
              }
              Object.entries(row.by_evidence_origin || {}).forEach(([origin, segment]) => {
                const originItem = document.createElement("li");
                originItem.textContent = `${origin === "prospective_board" ? "Board cohort" : "Placed entries"}: ${segment.metrics.samples} settled · forecast MAE ${number(segment.metrics.mae)} · exact-line MAE ${number(segment.paired_baselines?.exact_line?.mae)} · Brier ${segment.metrics.brier ?? "unavailable"}`;
                versions.append(originItem);
              });
              if (row.by_evidence_origin?.prospective_board) {
                const holdout = row.chronological_board_holdout || {};
                const holdoutItem = document.createElement("li");
                holdoutItem.textContent = holdout.status === "exploratory_holdout"
                  ? `Later-game board check from ${holdout.cutoff_game_date}: ${holdout.later_samples} offers · forecast MAE ${number(holdout.forecast?.mae)} · recent-five MAE ${number(holdout.locked_recent_5_mean?.mae)} · line MAE ${number(holdout.exact_line?.mae)} · Brier ${holdout.forecast?.brier ?? "unavailable"}.${holdout.paired_minutes?.samples ? ` On ${holdout.paired_minutes.samples} paired offers: forecast MAE ${number(holdout.paired_minutes.champion?.mae)}, minutes MAE ${number(holdout.paired_minutes.minutes_shadow?.mae)}.` : " No paired minutes forecast yet."} Exploratory only; no model promotion.`
                  : `Later-game board check unavailable: ${holdout.reason || "More settled board games are needed."}`;
                if (holdout.status === "exploratory_holdout" && holdout.paired_shot_volume?.samples) {
                  holdoutItem.textContent += ` On ${holdout.paired_shot_volume.samples} same-offer shot-volume forecasts: current forecast MAE ${number(holdout.paired_shot_volume.champion?.mae)}, shot-volume MAE ${number(holdout.paired_shot_volume.shot_volume_shadow?.mae)}. Research only.`;
                }
                versions.append(holdoutItem);
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
                  ? `${row.model_version}: ${row.samples} same-offer minutes forecasts · current forecast MAE ${number(row.champion?.mae)} · minutes MAE ${number(row.minutes_shadow?.mae)} · line MAE ${number(row.exact_line?.mae)}`
                  : `${row.model_version}: no paired minutes forecasts yet`;
                comparisons.append(item);
                if (row.shot_volume?.samples) {
                  const volumeItem = document.createElement("li");
                  volumeItem.textContent = `${row.model_version}: ${row.shot_volume.samples} same-offer shot-volume forecasts · current forecast MAE ${number(row.shot_volume.champion?.mae)} · shot-volume MAE ${number(row.shot_volume.shot_volume_shadow?.mae)} · line MAE ${number(row.shot_volume.exact_line?.mae)}. Research only.`;
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
  window.EdgeIQPlayerWorkspace = { mount, lockedModelSummary };
})();
