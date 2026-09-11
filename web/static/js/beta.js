(function initializeEdgeIQBeta(global) {
  const TOKEN_KEY = "edgeiq.beta.token";
  const { api, $, humanizeErrorText, withButtonBusy } = global.EdgeIQApi;
  const state = { session: null, context: {}, onboardingViewed: false };

  function setStatus(message, error = false) {
    const target = $("beta-center-status");
    if (!target) return;
    target.textContent = message;
    target.classList.toggle("danger-text", error);
  }

  function contextFromResearch() {
    const current = {
      player: $("research-context-player")?.value.trim() || "",
      stat: $("research-context-stat")?.value.trim() || "",
      sport: $("research-context-sport")?.value || "",
      platform: $("research-context-platform")?.value || "",
      line: $("research-context-line")?.value === "" ? null : Number($("research-context-line")?.value),
    };
    const sameAnalysis = (!state.context.player || state.context.player === current.player)
      && (!state.context.stat || state.context.stat === current.stat)
      && (!state.context.platform || state.context.platform === current.platform)
      && (state.context.line == null || current.line == null || Number(state.context.line) === Number(current.line));
    return { ...(sameAnalysis ? state.context : {}), ...current };
  }

  function setAnalysisContext(context = {}) {
    state.context = { ...context };
    const label = $("beta-feedback-context");
    const player = context.player || $("research-context-player")?.value || "Current analysis";
    const stat = context.stat || $("research-context-stat")?.value || "";
    if (label) label.textContent = `${player}${stat ? ` · ${stat}` : ""}`;
  }

  function renderSession() {
    const user = state.session?.user;
    const authenticated = Boolean(user);
    $("beta-login-form").hidden = authenticated;
    $("beta-account-panel").hidden = !authenticated;
    $("beta-analysis-feedback").hidden = !authenticated;
    if (!authenticated) {
      $("beta-center-title").textContent = "Beta Account";
      return;
    }
    $("beta-center-title").textContent = user.is_admin ? "Beta Administration" : "Beta Account";
    $("beta-account-name").textContent = user.username;
    $("beta-account-meta").textContent = `${user.beta_cohort} · ${user.role.replaceAll("_", " ")}`;
    $("beta-onboarding-panel").hidden = user.onboarding_complete;
    $("beta-admin-panel").hidden = !user.is_admin;
    setStatus(user.onboarding_complete ? "Signed in. Beta activity is attributed to this session." : "Complete the short beta acknowledgment to continue.");
    if (!user.onboarding_complete && !state.onboardingViewed) {
      state.onboardingViewed = true;
      api("/api/experience/events", {
        method: "POST",
        body: JSON.stringify({ event_name: "beta_onboarding_viewed", entity_type: "user", entity_id: String(user.id), metadata: {} }),
      }).catch(() => {});
    }
    if (user.is_admin) loadAdmin();
  }

  async function loadStatus() {
    try {
      const data = await api("/api/beta/status");
      state.session = data.session;
      if (!data.authenticated && global.localStorage.getItem(TOKEN_KEY)) global.localStorage.removeItem(TOKEN_KEY);
      renderSession();
      if (!data.configured) setStatus("Founding Beta identity is not initialized yet. Use the documented admin bootstrap command.");
    } catch (error) {
      setStatus(humanizeErrorText(error.message), true);
    }
  }

  async function login(event) {
    event.preventDefault();
    const data = await api("/api/beta/login", {
      method: "POST",
      body: JSON.stringify({ identifier: $("beta-login-identifier").value, password: $("beta-login-password").value }),
    });
    global.localStorage.setItem(TOKEN_KEY, data.token);
    state.session = { session_id: data.session_id, user: data.user };
    $("beta-login-form").reset();
    renderSession();
  }

  async function logout() {
    try {
      await api("/api/beta/logout", { method: "POST" });
    } finally {
      global.localStorage.removeItem(TOKEN_KEY);
      state.session = null;
      renderSession();
      setStatus("Signed out. EdgeIQ remains available, but activity is anonymous.");
    }
  }

  async function completeOnboarding() {
    const data = await api("/api/beta/onboarding", { method: "POST" });
    state.session.user = data.user;
    renderSession();
  }

  async function captureInitialDecision() {
    if (!state.session || !$("research-context-player")?.value.trim() || !$("research-context-stat")?.value.trim()) return;
    const context = contextFromResearch();
    api("/api/experience/events", {
      method: "POST",
      body: JSON.stringify({ event_name: "analysis_started", entity_type: "prop", entity_id: context.player || "manual", metadata: context }),
    }).catch(() => {});
    await api("/api/beta/decisions/initial", {
      method: "POST",
      body: JSON.stringify({ initial_pick: $("beta-initial-pick").value, context }),
    }).catch(() => {});
    $("beta-feedback-status").textContent = "Initial opinion recorded before the recommendation was revealed.";
  }

  async function submitFeedback(event) {
    event.preventDefault();
    if (!state.session) return;
    const context = contextFromResearch();
    const usefulValue = $("beta-useful").value;
    const data = await api("/api/beta/feedback", {
      method: "POST",
      body: JSON.stringify({
        prediction_record_id: context.prediction_record_id || null,
        entry_id: context.entry_id || null,
        entry_prop_id: context.entry_prop_id || null,
        useful: usefulValue === "" ? null : usefulValue === "true",
        initial_pick: $("beta-initial-pick").value,
        final_pick: $("beta-final-pick").value,
        would_pick: $("beta-would-pick").value,
        would_pay: $("beta-would-pay").value,
        feedback_text: $("beta-feedback-text").value,
        context,
      }),
    });
    $("beta-feedback-status").textContent = data.feedback.changed_decision
      ? "Feedback saved. EdgeIQ changed your recorded decision."
      : "Feedback saved. Thank you for helping validate EdgeIQ.";
    $("beta-feedback-text").value = "";
  }

  async function submitIssue(event, issueType) {
    event.preventDefault();
    const isBug = issueType === "BUG";
    const description = $(isBug ? "beta-bug-description" : "beta-feature-description").value;
    const context = contextFromResearch();
    await api("/api/beta/issues", {
      method: "POST",
      body: JSON.stringify({
        issue_type: issueType,
        category: isBug ? $("beta-bug-category").value : "Feature request",
        description,
        prediction_record_id: context.prediction_record_id || null,
        entry_id: context.entry_id || null,
        entry_prop_id: context.entry_prop_id || null,
      }),
    });
    $(isBug ? "beta-bug-description" : "beta-feature-description").value = "";
    setStatus(isBug ? "Problem report submitted." : "Feature request submitted.");
    if (state.session?.user?.is_admin) loadAdmin();
  }

  function metric(label, value) {
    return `<div><strong>${value ?? 0}</strong><span>${label}</span></div>`;
  }

  async function loadAdmin() {
    if (!state.session?.user?.is_admin) return;
    const data = await api("/api/beta/admin/summary");
    $("beta-admin-kpis").innerHTML = [
      metric("Testers", data.testers), metric("Active", data.active_testers),
      metric("Active this week", data.active_this_week), metric("New this week", data.new_testers),
      metric("Inactive", data.inactive_testers), metric("Sessions", data.sessions),
      metric("Recommendation views", data.recommendation_views), metric("Analyses", data.analyses),
      metric("Added to entries", data.recommendations_added), metric("Entries saved", data.entries_saved),
      metric("Entries settled", data.entries_settled), metric("Feedback", data.feedback_responses),
      metric("Useful rate", `${data.useful_rate}%`), metric("Decision changes", `${data.decision_change_rate}%`),
      metric("Bugs", data.bugs_reported), metric("Requests", data.feature_requests),
    ].join("");
    $("beta-admin-users").innerHTML = (data.testers_activity || []).map((user) => `
      <div class="beta-admin-row"><div><strong>${escapeText(user.username)}</strong><span>${escapeText(user.cohort)} · ${user.sessions} sessions · ${user.analyses} analyses · ${user.feedback} feedback · ${user.entries_saved} saved · ${user.entries_settled} settled</span><span>Joined ${shortDate(user.created_at)} · Last active ${shortDate(user.last_active_at)}</span></div><div class="beta-admin-actions"><input aria-label="${escapeText(user.username)} cohort" value="${escapeText(user.cohort)}" data-beta-cohort-id="${user.id}" maxlength="40" /><button class="secondary" type="button" data-beta-save-cohort="${user.id}">Save Cohort</button><button class="secondary" type="button" data-beta-user-id="${user.id}" data-beta-active="${user.is_active}">${user.is_active ? "Deactivate" : "Activate"}</button></div></div>
    `).join("") || "<p class='subtle'>No beta testers yet.</p>";
    $("beta-admin-feedback").innerHTML = [
      ...(data.recent_feedback || []).map((row) => `<div class="beta-admin-row"><div><strong>${escapeText(row.tester)} · Feedback</strong><span>${escapeText(row.feedback_text || `${row.initial_pick} to ${row.final_pick}`)}</span></div></div>`),
      ...(data.recent_bugs || []).map((row) => `<div class="beta-admin-row"><div><strong>${escapeText(row.tester)} · ${escapeText(row.category)}</strong><span>${escapeText(row.description)}</span></div></div>`),
      ...(data.recent_feature_requests || []).map((row) => `<div class="beta-admin-row"><div><strong>${escapeText(row.tester)} · Feature</strong><span>${escapeText(row.description)}</span></div></div>`),
    ].join("") || "<p class='subtle'>No feedback or requests yet.</p>";
    const model = data.model_performance || {};
    const segmentRows = Object.entries(data.segments || {}).flatMap(([group, rows]) => (rows || []).slice(0, 8).map((row) => `<div class="beta-admin-row"><div><strong>${escapeText(group)} · ${escapeText(row.label)}</strong><span>${row.settled} settled · ${row.hit_rate}% hit · ${row.useful_rate}% useful · ${escapeText(row.sample_label)}</span></div></div>`));
    $("beta-admin-model").innerHTML = `<div class="beta-kpi-grid">${metric("Versioned predictions", model.versioned_prediction_records)}${metric("Settled markets", model.settled_unique_markets)}${metric("Hit rate", `${model.recommendation_hit_rate || 0}%`)}${metric("Projection MAE", model.projection_mae == null ? "Building" : Number(model.projection_mae).toFixed(2))}</div>${segmentRows.join("") || "<p class='subtle'>Linked segment feedback is still building.</p>"}`;
    document.querySelectorAll("[data-beta-user-id]").forEach((button) => button.addEventListener("click", () => toggleUser(button)));
    document.querySelectorAll("[data-beta-save-cohort]").forEach((button) => button.addEventListener("click", () => saveCohort(button)));
  }

  async function toggleUser(button) {
    await api(`/api/beta/admin/users/${button.dataset.betaUserId}`, { method: "PATCH", body: JSON.stringify({ is_active: button.dataset.betaActive !== "true" }) });
    await loadAdmin();
  }

  async function saveCohort(button) {
    const input = document.querySelector(`[data-beta-cohort-id="${button.dataset.betaSaveCohort}"]`);
    await api(`/api/beta/admin/users/${button.dataset.betaSaveCohort}`, { method: "PATCH", body: JSON.stringify({ beta_cohort: input.value }) });
    setStatus("Beta cohort updated.");
    await loadAdmin();
  }

  async function createUser(event) {
    event.preventDefault();
    await api("/api/beta/admin/users", {
      method: "POST",
      body: JSON.stringify({ email: $("beta-new-email").value, username: $("beta-new-username").value, password: $("beta-new-password").value, role: $("beta-new-role").value, beta_cohort: $("beta-new-cohort").value, is_beta_tester: true }),
    });
    $("beta-create-user-form").reset();
    $("beta-new-cohort").value = "FOUNDING_25";
    setStatus("Beta account created.");
    await loadAdmin();
  }

  function escapeText(value) {
    const element = document.createElement("span");
    element.textContent = String(value ?? "");
    return element.innerHTML;
  }

  function shortDate(value) {
    if (!value) return "Never";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? escapeText(value) : date.toLocaleDateString();
  }

  function toggleDrawer(open) {
    $("beta-center-drawer").hidden = !open;
    $("beta-center-toggle").setAttribute("aria-expanded", open ? "true" : "false");
  }

  function bind() {
    if (!$("beta-center-toggle")) return;
    $("beta-center-toggle").addEventListener("click", () => toggleDrawer($("beta-center-drawer").hidden));
    $("beta-center-close").addEventListener("click", () => toggleDrawer(false));
    $("beta-login-form").addEventListener("submit", (event) => withButtonBusy(event.submitter, "Signing in...", () => login(event)).catch((error) => setStatus(humanizeErrorText(error.message), true)));
    $("beta-logout").addEventListener("click", logout);
    $("beta-onboarding-ack").addEventListener("change", () => { $("beta-complete-onboarding").disabled = !$("beta-onboarding-ack").checked; });
    $("beta-complete-onboarding").addEventListener("click", completeOnboarding);
    $("beta-feedback-form").addEventListener("submit", (event) => withButtonBusy(event.submitter, "Saving...", () => submitFeedback(event)).catch((error) => { $("beta-feedback-status").textContent = humanizeErrorText(error.message); }));
    $("beta-bug-form").addEventListener("submit", (event) => withButtonBusy(event.submitter, "Sending...", () => submitIssue(event, "BUG")).catch((error) => setStatus(humanizeErrorText(error.message), true)));
    $("beta-feature-form").addEventListener("submit", (event) => withButtonBusy(event.submitter, "Sending...", () => submitIssue(event, "FEATURE")).catch((error) => setStatus(humanizeErrorText(error.message), true)));
    $("beta-admin-refresh").addEventListener("click", () => withButtonBusy("beta-admin-refresh", "Refreshing...", loadAdmin));
    $("beta-create-user-form").addEventListener("submit", (event) => withButtonBusy(event.submitter, "Creating...", () => createUser(event)).catch((error) => setStatus(humanizeErrorText(error.message), true)));
    $("research-context-form").addEventListener("submit", captureInitialDecision);
    loadStatus();
  }

  global.EdgeIQBeta = { setAnalysisContext, refresh: loadStatus };
  global.addEventListener("DOMContentLoaded", bind, { once: true });
}(window));
