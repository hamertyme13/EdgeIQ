(function () {
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const dateLabel = (value) => {
    const date = new Date(value || "");
    return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString(undefined, {dateStyle: "medium", timeStyle: "short"});
  };
  function transferable(row, direction) {
    const allowed = Array.isArray(row.allowed_directions) ? row.allowed_directions : ["Over", "Under"];
    const premium = row.platform === "PrizePicks" && (row.line_offer_type === "demon" || row.is_premium_line);
    return Boolean(row.platform && row.game_time && row.game && Number.isFinite(Date.parse(row.game_time))
      && Number.isFinite(Number(row.line)) && row.line != null && String(row.line).trim() !== ""
      && allowed.includes(direction) && !(premium && direction === "Under"));
  }
  function availabilityLabel(row, now = Date.now()) {
    if (row.stale) return 'Stale provider snapshot. Refresh provider data and confirm the offer before use.';
    const start = Date.parse(row.game_time || '');
    if (!Number.isFinite(start)) return 'Game time unavailable. Live availability unverified.';
    if (start <= now) return 'Scheduled start has passed. This may no longer be a pregame offer; verify in the sportsbook.';
    return 'Saved provider offer. Live availability and offer freshness are unverified.';
  }
  function render(data) {
    if (!data.lines?.length) return '<p role="status">No matching provider offers. Check the sport, player, and stat, or refresh provider data.</p>';
    return `<p>${escape(data.message)}</p>${data.manual_no_vig ? `<p>User-entered odds: Over ${escape(data.manual_no_vig.over_probability)}%, Under ${escape(data.manual_no_vig.under_probability)}% no-vig. These inputs are not verified provider prices and are not assigned to the offers below.</p>` : ""}<div class="best-lines-list">${data.lines.map((row, index) => `<article class="best-line-row">
      <div><strong>${escape(row.player || data.player)} · ${escape(row.platform || "Provider unavailable")}</strong><p>${escape(row.game || "Game unavailable")} · ${escape(dateLabel(row.game_time))}</p></div>
      <div><strong>${escape(data.direction)} ${escape(row.line)}</strong><p>${escape(row.line_offer_type || "Offer type unavailable")}</p></div>
      <div>${row.best_threshold ? '<strong class="positive">Best threshold</strong>' : ""}<p>${escape(row.comparison_note)}</p></div>
      <p class="subtle">${escape(availabilityLabel(row))}</p>
      ${row.provider_offer_observed_at ? `<p class="subtle">Collector retrieved: ${escape(dateLabel(row.provider_offer_observed_at))}. This is not direct sportsbook verification.</p>` : ''}
      <details><summary>Evidence</summary><p>Projection: ${escape(row.projection ?? "Unavailable")}</p><p>Model inputs as of: ${escape(dateLabel(row.feature_as_of))}</p><p>Offer refresh time: ${row.provider_offer_verified_at ? escape(dateLabel(row.provider_offer_verified_at)) : 'unavailable'}. Model input time does not confirm line freshness.</p><p>EV unverified. Confirm the offer and complete entry payout in the provider app.</p></details>
      <button type="button" class="secondary" data-add-best-line="${index}" ${transferable(row, data.direction) ? "" : 'disabled title="Game details are missing or this direction is unavailable"'}>Add to Entry</button>
    </article>`).join("")}</div>`;
  }
  async function search(event, retry = null) {
    event.preventDefault();
    const form = document.getElementById("line-shop-form");
    if (!retry && !form.reportValidity()) return;
    const button = form.querySelector('button[type="submit"]');
    if (button.disabled) return;
    const result = document.getElementById("line-shop-result");
    document.getElementById('best-lines-progress')?.remove();
    result.classList.remove("muted-card", "analysis-card");
    const params = new URLSearchParams(retry?.params || '');
    if (!retry) for (const field of ["player", "stat", "sport", "platform", "direction"]) params.set(field, document.getElementById(`shop-${field}`).value.trim());
    const players = retry?.players || [...new Map(params.get('player').split(/[\n,]/).map(name => name.trim()).filter(Boolean).map(name => [name.toLocaleLowerCase(), name])).values()];
    if (!players.length || players.length > 5) {
      result.textContent = "Choose between one and five players.";
      return;
    }
    if (!retry && players.length > 1 && ['over', 'under'].some(field => document.getElementById(`shop-${field}-odds`).value)) {
      result.textContent = "Manual odds apply to one player only. Clear them before comparing multiple players.";
      return;
    }
    if (!retry) for (const field of ["over", "under"]) {
      const value = document.getElementById(`shop-${field}-odds`).value;
      if (value) params.set(`${field}_odds`, value);
    }
    button.disabled = true; button.textContent = "Comparing...";
    const controller = new AbortController();
    const cancel = document.createElement('button');
    cancel.type = 'button'; cancel.className = 'secondary'; cancel.textContent = 'Stop comparison';
    cancel.addEventListener('click', () => { controller.abort(); cancel.disabled = true; });
    button.after(cancel);
    const progress = document.createElement('p');
    progress.id = 'best-lines-progress';
    progress.setAttribute('role', 'status');
    result.before(progress);
    result.setAttribute("aria-busy", "true");
    if (!retry) result.textContent = "Comparing provider snapshots...";
    result.querySelectorAll('button').forEach(control => { control.disabled = true; });
    try {
      const data = retry ? {...retry.data, lines: [...retry.data.lines]} : {lines: [], direction: params.get('direction'), sport: params.get('sport'), stat: params.get('stat')};
      const missing = [];
      const completed = new Set();
      for (const player of players) {
        if (controller.signal.aborted) break;
        params.set('player', player);
        progress.textContent = `Comparing ${player} (${players.indexOf(player) + 1} of ${players.length})...`;
        try {
          const response = await window.EdgeIQApi.api(`/api/market/best-lines?${params}`, {timeoutMs: 10000, signal: controller.signal});
          if (controller.signal.aborted) break;
          data.message = response.message;
          data.manual_no_vig = response.manual_no_vig;
          data.lines.push(...(response.lines || []).map(row => ({...row, player: row.player || response.player || player, stat: row.stat || response.stat || data.stat, sport: row.sport || row.league || response.sport || data.sport})));
          completed.add(player);
          if (!response.lines?.length) missing.push(player);
          result.innerHTML = render(data);
          result.querySelectorAll('[data-add-best-line]').forEach(control => { control.disabled = true; });
        } catch (_) { if (!controller.signal.aborted) { missing.push(player); completed.add(player); } }
      }
      for (const player of players) if (!completed.has(player)) missing.push(player);
      progress.textContent = controller.signal.aborted ? 'Comparison stopped. Completed results are shown below; remaining players were not checked.' : 'Comparison complete.';
      result.innerHTML = render(data);
      if (missing.length) {
        const notice = document.createElement('p');
        notice.setAttribute('role', 'status');
        notice.textContent = `No comparison available for: ${missing.join(', ')}. Provider data may be missing or the lookup could not finish.`;
        result.prepend(notice);
        const retryButton = document.createElement('button');
        retryButton.type = 'button'; retryButton.className = 'secondary';
        retryButton.dataset.retryBestLines = '';
        retryButton.textContent = `Retry ${missing.length} missing ${missing.length === 1 ? 'player' : 'players'}`;
        const request = {params: params.toString(), players: [...missing], data};
        retryButton.addEventListener('click', event => search(event, request));
        notice.after(retryButton);
      }
      if (data.lines?.length) {
        const filters = document.createElement("div");
        filters.className = "form-grid compact-controls";
        const options = (values) => [...new Set(values)].filter(Boolean).sort().map(value => `<option value="${escape(value)}">${escape(value)}</option>`).join("");
        filters.innerHTML = `<label>Sportsbook<select data-best-provider><option value="">All sportsbooks</option>${options(data.lines.map(row => row.platform))}</select></label><label>Offer type<select data-best-type><option value="">All offer types</option>${options(data.lines.map(row => row.line_offer_type || "Unknown"))}</select></label><p data-best-count role="status"></p>`;
        result.prepend(filters);
        const update = () => {
          const provider = filters.querySelector('[data-best-provider]').value;
          const type = filters.querySelector('[data-best-type]').value;
          let visible = 0;
          result.querySelectorAll('.best-line-row').forEach((element, index) => {
            const row = data.lines[index];
            element.hidden = Boolean((provider && row.platform !== provider) || (type && (row.line_offer_type || "Unknown") !== type));
            if (!element.hidden) visible += 1;
          });
          filters.querySelector('[data-best-count]').textContent = visible ? `${visible} of ${data.lines.length} offers` : "No offers match these filters. Choose another sportsbook or offer type.";
        };
        filters.addEventListener('change', update);
        update();
      }
      result.querySelectorAll('[data-add-best-line]').forEach((control) => control.addEventListener('click', () => {
        const row = data.lines[Number(control.dataset.addBestLine)];
        if (!transferable(row, data.direction)) return;
        const added = window.addFeedProp({ ...row, player: row.player || data.player,
          sport: row.sport || row.league || data.sport, stat: row.stat || data.stat, direction: data.direction });
        if (added) { control.disabled = true; control.textContent = "Added"; }
      }));
    } catch (error) {
      result.textContent = "The comparison could not finish. Provider data may be unavailable or still loading. Refresh providers and try again.";
    } finally {
      cancel.remove();
      if (!controller.signal.aborted) progress.remove();
      result.setAttribute("aria-busy", "false"); button.disabled = false; button.textContent = "Compare Lines";
    }
  }
  document.addEventListener("DOMContentLoaded", () => {
    const tool = document.getElementById("best-lines-tool");
    if (!tool) return;
    document.getElementById("best-lines-host").append(tool);
    for (const field of ["player", "stat", "sport", "platform", "direction"]) {
      const input = document.getElementById(`shop-${field}`);
      input.setAttribute("aria-label", field);
      input.required = true;
      const label = document.createElement("label");
      label.textContent = field === 'player' ? 'Players (up to 5, comma-separated)' : field.charAt(0).toUpperCase() + field.slice(1);
      input.before(label); label.append(input);
    }
    const manual = document.createElement("details");
    manual.className = "best-lines-manual";
    manual.innerHTML = "<summary>Optional manual odds</summary>";
    for (const field of ["over", "under"]) {
      const label = document.createElement("label");
      label.textContent = `${field === "over" ? "Over" : "Under"} American odds`;
      label.append(document.getElementById(`shop-${field}-odds`)); manual.append(label);
    }
    document.getElementById("line-shop-form").append(manual);
  });
  window.EdgeIQBestLines = { search, render, transferable, availabilityLabel };
}());
