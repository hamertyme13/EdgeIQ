(() => {
  const easternDay = (date) => {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  };
  const playerKey = (value) => String(value || "").normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const ageMinutes = (value, now) => {
    const timestamp = new Date(value || "").getTime();
    return Number.isNaN(timestamp) ? null : (now.getTime() - timestamp) / 60000;
  };

  function lane(prop, now = new Date()) {
    const start = new Date(prop.game_time || "");
    const today = !Number.isNaN(start.getTime())
      && easternDay(start) === easternDay(now) && start > now;
    const fresh = prop.recommendation_freshness?.status === "fresh"
      && (!prop.edgeiq_score_freshness || prop.edgeiq_score_freshness.status === "fresh");
    const offerAge = ageMinutes(prop.provider_offer_verified_at, now);
    const sourceAge = ageMinutes(prop.provider_offer_verified_at || prop.provider_offer_observed_at, now);
    const featureAge = ageMinutes(prop.feature_as_of, now);
    const validUntil = new Date(prop.decision_receipt?.valid_until || "").getTime();
    const stillValid = Number.isNaN(validUntil) || now.getTime() < validUntil;
    const verified = prop.end_to_end_confirmed === true && prop.provider_backed === true
      && prop.market_supported !== false && Boolean(prop.platform)
      && Boolean(prop.game) && Boolean(prop.provider_offer_id);
    if (!today || !fresh || !verified || prop.actionable === false || !stillValid
        || sourceAge === null || sourceAge < 0 || sourceAge > 30
        || featureAge === null || featureAge < 0 || featureAge > 30) return "review";
    return prop.recommendation_eligibility?.paid_ready === true
      && offerAge !== null && offerAge >= 0 && offerAge <= 5 ? "ready" : "paper";
  }

  function prepare(opportunities, now = new Date()) {
    const bestReady = new Map();
    const ranked = opportunities.map((prop) => ({...prop, _readyLane: lane(prop, now)}));
    for (const prop of ranked.filter((row) => row._readyLane === "ready")) {
      const key = playerKey(prop.player);
      const previous = bestReady.get(key);
      if (!previous || Number(prop.edgeiq_score?.score || 0) > Number(previous.edgeiq_score?.score || 0)
          || (Number(prop.edgeiq_score?.score || 0) === Number(previous.edgeiq_score?.score || 0)
            && Number(prop.confidence || 0) > Number(previous.confidence || 0))) {
        bestReady.set(key, prop);
      }
    }
    return ranked.filter((prop) => prop._readyLane !== "ready" || bestReady.get(playerKey(prop.player)) === prop);
  }

  function planTransfer(existing, selected, maximumLegs) {
    if (!selected.length) return {error: "Select at least one prop first."};
    const platform = String(selected[0].platform || "").trim();
    if (!platform || selected.some((prop) => prop.platform !== platform)
        || existing.some((prop) => prop.platform && prop.platform !== platform)) {
      return {error: "One entry must use one sportsbook. Keep the current slip or start a separate entry."};
    }
    if (existing.length + selected.length > maximumLegs) {
      return {error: `${platform} allows up to ${maximumLegs} legs. Remove a leg before sending these props.`};
    }
    const players = new Set(existing.map((prop) => playerKey(prop.player)));
    for (const prop of selected) {
      if (Array.isArray(prop.allowed_directions) && !prop.allowed_directions.includes(prop.direction)) {
        return {error: `${prop.player} does not offer ${prop.direction} on this line. Review the available direction.`};
      }
      const key = playerKey(prop.player);
      if (!key || players.has(key)) {
        return {error: `${prop.player || "This player"} is already on the slip. Choose one stat and line per player.`};
      }
      players.add(key);
    }
    return {props: [...existing, ...selected], added: selected.length};
  }

  window.EdgeIQReadyNow = {lane, prepare, planTransfer};
})();
