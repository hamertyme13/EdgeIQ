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
  function render(data) {
    if (!data.lines?.length) return '<p role="status">No matching provider offers. Check the sport, player, and stat, or refresh provider data.</p>';
    return `<p>${escape(data.message)}</p>${data.manual_no_vig ? `<p>User-entered odds: Over ${escape(data.manual_no_vig.over_probability)}%, Under ${escape(data.manual_no_vig.under_probability)}% no-vig. These inputs are not verified provider prices and are not assigned to the offers below.</p>` : ""}<div class="best-lines-list">${data.lines.map((row, index) => `<article class="best-line-row">
      <div><strong>${escape(row.platform || "Provider unavailable")}</strong><p>${escape(row.game || "Game unavailable")} · ${escape(dateLabel(row.game_time))}</p></div>
      <div><strong>${escape(data.direction)} ${escape(row.line)}</strong><p>${escape(row.line_offer_type || "Offer type unavailable")}</p></div>
      <div>${row.best_threshold ? '<strong class="positive">Best threshold</strong>' : ""}<p>${escape(row.comparison_note)}</p></div>
      <details><summary>Evidence</summary><p>Projection: ${escape(row.projection ?? "Unavailable")}</p><p>Updated: ${escape(dateLabel(row.feature_as_of))}</p><p>EV unverified. Confirm the offer and complete entry payout in the provider app.</p></details>
      <button type="button" class="secondary" data-add-best-line="${index}" ${transferable(row, data.direction) ? "" : 'disabled title="Game details are missing or this direction is unavailable"'}>Add to Entry</button>
    </article>`).join("")}</div>`;
  }
  async function search(event) {
    event.preventDefault();
    const form = document.getElementById("line-shop-form");
    if (!form.reportValidity()) return;
    const button = form.querySelector('button[type="submit"]');
    if (button.disabled) return;
    const result = document.getElementById("line-shop-result");
    result.classList.remove("muted-card", "analysis-card");
    const params = new URLSearchParams();
    for (const field of ["player", "stat", "sport", "platform", "direction"]) params.set(field, document.getElementById(`shop-${field}`).value.trim());
    for (const field of ["over", "under"]) {
      const value = document.getElementById(`shop-${field}-odds`).value;
      if (value) params.set(`${field}_odds`, value);
    }
    button.disabled = true; button.textContent = "Comparing...";
    result.setAttribute("aria-busy", "true"); result.textContent = "Comparing provider snapshots...";
    try {
      const data = await window.EdgeIQApi.api(`/api/market/best-lines?${params}`, {timeoutMs: 20000});
      result.innerHTML = render(data);
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
      label.textContent = field.charAt(0).toUpperCase() + field.slice(1);
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
  window.EdgeIQBestLines = { search, render, transferable };
}());
