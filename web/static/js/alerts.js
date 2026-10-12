(() => {
  const alertKinds = ["upgrades", "downgrades", "line_changes", "invalidated", "injury_context_changes"];

  function create({ $, api, escapeHtml, friendlyStatus, pct, sortNotifications }) {
    async function loadNotifications() {
      const data = await api("/api/notifications");
      const notifications = sortNotifications(data.notifications);
      $("notification-list").innerHTML = notifications.map((note) => {
        const severity = ["neutral", "positive", "warning", "danger"].includes(note.severity) ? note.severity : "neutral";
        return `<div class="suggestion compact-suggestion notification-${severity}">
          <div class="suggestion-top">
            <strong>${escapeHtml(note.title)}</strong>
            <span class="status-pill status-${severity}">${escapeHtml(friendlyStatus(note.type))}</span>
          </div>
          <p>${escapeHtml(note.message)}</p>
        </div>`;
      }).join("") || `
        <div class="suggestion compact-suggestion">
          <div class="suggestion-top">
            <strong>All clear</strong>
            <span class="status-pill status-connected">No alerts</span>
          </div>
          <p>No smart notifications right now.</p>
        </div>`;
      if ($("notification-center-list")) $("notification-center-list").innerHTML = $("notification-list").innerHTML;
      if ($("notification-center-count")) {
        $("notification-center-count").textContent = String(notifications.length);
        $("notification-center-count").hidden = notifications.length === 0;
      }
    }

    function renderAlertDeliveryStatus(data) {
      const settings = data.settings || {};
      const hooks = data.delivery_hooks || {};
      $("alert-delivery-status").classList.remove("muted-card");
      $("alert-delivery-status").innerHTML = `
        <div class="suggestion-top">
          <strong>${escapeHtml((settings.channels || []).join(", ") || "No channels")}</strong>
          <span class="subtle">Min ${pct(settings.min_priority || 0)}</span>
        </div>
        <p>Browser ${escapeHtml(hooks.browser || "-")} · Email ${escapeHtml(hooks.email || "-")} · SMS ${escapeHtml(hooks.sms || "-")} · Webhook ${escapeHtml(hooks.webhook || "-")}</p>
        <p class="subtle">Briefing change alerts appear in-app only. External delivery requires configured channels.</p>`;
    }

    async function loadAlertDeliverySettings() {
      const data = await api("/api/settings/alert-delivery");
      const settings = data.settings || {};
      $("alert-browser-enabled").checked = Boolean(settings.browser_enabled);
      $("alert-email-enabled").checked = Boolean(settings.email_enabled);
      $("alert-email-address").value = settings.email_address || "";
      $("alert-sms-enabled").checked = Boolean(settings.sms_enabled);
      $("alert-sms-number").value = settings.sms_number || "";
      $("alert-webhook-enabled").checked = Boolean(settings.webhook_enabled);
      $("alert-webhook-url").value = settings.webhook_url || "";
      $("alert-min-priority").value = settings.min_priority ?? 65;
      $("smart-alerts-enabled").checked = Boolean(settings.smart_alerts_enabled);
      for (const kind of alertKinds) {
        $(`smart-${kind.replaceAll("_", "-")}`).checked = (settings.smart_alert_types || []).includes(kind);
      }
      $("smart-alert-line-move").value = settings.smart_alert_line_move ?? 1;
      renderAlertDeliveryStatus(data);
    }

    async function saveAlertDeliverySettings(event) {
      event.preventDefault();
      const payload = {
        browser_enabled: $("alert-browser-enabled").checked,
        email_enabled: $("alert-email-enabled").checked,
        email_address: $("alert-email-address").value.trim(),
        sms_enabled: $("alert-sms-enabled").checked,
        sms_number: $("alert-sms-number").value.trim(),
        webhook_enabled: $("alert-webhook-enabled").checked,
        webhook_url: $("alert-webhook-url").value.trim(),
        min_priority: Number($("alert-min-priority").value || 65),
        smart_alerts_enabled: $("smart-alerts-enabled").checked,
        smart_alert_types: alertKinds.filter((kind) => $(`smart-${kind.replaceAll("_", "-")}`).checked),
        smart_alert_line_move: Number($("smart-alert-line-move").value || 1),
      };
      const data = await api("/api/settings/alert-delivery", { method: "POST", body: JSON.stringify(payload) });
      renderAlertDeliveryStatus(data);
    }

    async function testAlertDelivery() {
      $("alert-delivery-status").classList.remove("muted-card");
      $("alert-delivery-status").textContent = "Sending test alert...";
      const data = await api("/api/alerts/test-delivery", {
        method: "POST",
        body: JSON.stringify({
          title: "EdgeIQ alert test",
          message: "Alert delivery is connected.",
          priority: Number($("alert-min-priority").value || 65),
          severity: "positive",
        }),
      });
      $("alert-delivery-status").innerHTML = `
        <h2>${data.delivered ? "Delivery Ready" : "Skipped"}</h2>
        ${(data.channels || []).map((row) => `<p>${escapeHtml(row.channel)} · ${escapeHtml(row.status)} · ${escapeHtml(row.detail)}</p>`).join("") || `<p>${escapeHtml(data.reason || "No channels configured.")}</p>`}`;
    }

    return { loadNotifications, loadAlertDeliverySettings, saveAlertDeliverySettings, testAlertDelivery };
  }

  window.EdgeIQAlerts = { create };
})();
