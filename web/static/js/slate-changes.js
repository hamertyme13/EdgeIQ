(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  const labels = {
    new_games: "new games", removed_games: "removed games", new_recommendations: "new ranked props",
    removed_recommendations: "no longer ranked", line_changes: "line moves",
    projection_changes: "projection changes", confidence_changes: "confidence changes",
    injury_context_changes: "injury updates", upgrades: "upgrades", downgrades: "downgrades",
    invalidated: "invalidated",
  };
  function render(data) {
    if (!data?.available) return `<p>${escape(data?.message || "Refresh the briefing again to compare the same day's slate.")}</p>`;
    const counts = data.counts || {};
    const total = Number(data.event_count || 0);
    return `<p>${total ? `${total} observed change${total === 1 ? "" : "s"} in displayed games and ranked props.` : "No observed changes in displayed games or ranked props."}</p>
      <div class="slate-change-counts">${Object.entries(labels).filter(([key]) => Number(counts[key] || 0) > 0).map(([key, label]) => `<span><strong>${Number(counts[key])}</strong> ${escape(label)}</span>`).join("")}</div>
      ${data.events?.length ? `<ul>${data.events.map(event => `<li><strong>${escape(event.label)}</strong> · ${escape(event.detail)}</li>`).join("")}</ul>` : ""}
      <p class="subtle">${escape(data.scope || "Only saved displayed recommendations were compared.")}${Number(data.event_count || 0) > Number(data.events?.length || 0) ? ` Showing the first ${Number(data.events?.length || 0)} changes.` : ""}</p>`;
  }
  window.EdgeIQSlateChanges = {render};
})();
