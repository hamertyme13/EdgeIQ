(() => {
  function create({ $, api, state, document, escapeHtml, friendlyStatus, formatDateTime, humanizeText, sortProviderHealth }) {
    async function loadRuntimeStatus() {
      if (!$('runtime-status-list')) return;
      const data = await api('/api/runtime/status');
      $('runtime-status-list').innerHTML = (data.items || []).map((item) => `
        <div class="runtime-status-item runtime-${escapeHtml(item.status || 'attention')}" title="${escapeHtml(humanizeText(item.detail || ''))}">
          <span class="runtime-status-dot" aria-hidden="true"></span>
          <div><strong>${escapeHtml(item.label || 'System')}</strong><small>${escapeHtml(humanizeText(item.value || 'Unknown'))}</small></div>
        </div>
      `).join('') || '<div class="runtime-status-loading">Runtime status is not available yet.</div>';
      const modelItem = (data.items || []).find((item) => /model|release/i.test(String(item.label || '')));
      const settlementItem = (data.items || []).find((item) => /settlement|worker/i.test(String(item.label || '')));
      if ($('global-model-status')) $('global-model-status').textContent = modelItem
        ? `${modelItem.label}: ${humanizeText(modelItem.value || 'Unknown')}`
        : 'Model release unavailable';
      if ($('global-settlement-status') && settlementItem) {
        $('global-settlement-status').textContent = `${settlementItem.label}: ${humanizeText(settlementItem.value || 'Unknown')}`;
      }
    }

    function renderGlobalHealthStrip(providers = [], summary = {}, operations = {}) {
      const strip = $('global-health-strip');
      if (!strip) return;
      const activeView = document.querySelector('.view.active')?.id || 'dashboard';
      const selectedPlatform = activeView === 'entries'
        ? $('entry-platform')?.value
        : activeView === 'analysis'
          ? $('research-context-platform')?.value
          : activeView === 'dashboard'
            ? $('props-platform')?.value
            : '';
      const platformToken = String(selectedPlatform || '').toLowerCase().split(' ')[0];
      const contextual = platformToken && !['all', 'both'].includes(platformToken)
        ? providers.filter((provider) => String(provider.name || '').toLowerCase().includes(platformToken))
        : [];
      const healthyProviders = providers.filter((provider) => !['empty', 'unavailable', 'disabled'].includes(String(provider.status || '').toLowerCase()));
      const selected = (contextual.length ? contextual : healthyProviders).slice(0, activeView === 'performance' ? 0 : 2);
      const providerRows = selected.map((provider) => {
        const status = String(provider.status || 'unavailable').toLowerCase();
        const tone = ['fresh', 'connected', 'healthy', 'available'].includes(status)
          ? 'ready'
          : ['empty', 'stale', 'degraded'].includes(status)
            ? 'warning'
            : 'danger';
        return `<span title="${escapeHtml(provider.message || provider.purpose || '')}"><i class="global-health-dot status-${tone}"></i>${escapeHtml(provider.name)} ${escapeHtml(friendlyStatus(status))}</span>`;
      }).join('');
      const settlement = operations.shadow_settlement || {};
      const settlementLabel = settlement.ran_at ? `Settlement ${settlement.failures?.length ? 'needs attention' : 'healthy'}` : 'Settlement waiting';
      const systemCount = selected.length + 2;
      strip.innerHTML = `${providerRows || `<span><i class="global-health-dot status-ready"></i>${Number(summary.connected || 0)} data sources available</span>`}<span id="global-settlement-status">${escapeHtml(settlementLabel)}</span><span id="global-model-status">${escapeHtml($('global-model-status')?.textContent || 'Model checking')}</span><button id="global-health-toggle" class="global-health-toggle secondary" type="button" aria-expanded="false" aria-label="Show ${systemCount} system statuses">Status</button>`;
      $('global-health-toggle')?.addEventListener('click', () => {
        const expanded = strip.classList.toggle('expanded');
        $('global-health-toggle').setAttribute('aria-expanded', expanded ? 'true' : 'false');
        $('global-health-toggle').textContent = expanded ? 'Close' : 'Status';
        $('global-health-toggle').setAttribute('aria-label', expanded ? 'Hide system statuses' : `Show ${systemCount} system statuses`);
      });
    }

    function renderTodayProviderStatus(providers = [], summary = {}) {
      const status = $('today-provider-status');
      if (!status) return;
      const relevant = providers.filter((provider) => provider.configured !== false);
      const stale = relevant.filter((provider) => ['stale', 'degraded', 'error', 'unavailable'].includes(String(provider.status || '').toLowerCase()));
      status.classList.toggle('needs-refresh', stale.length > 0);
      status.classList.toggle('is-fresh', stale.length === 0 && relevant.length > 0);
      if (stale.length) {
        status.textContent = `${stale.length} provider${stale.length === 1 ? '' : 's'} need${stale.length === 1 ? 's' : ''} a refresh`;
      } else if (relevant.length) {
        status.textContent = 'Providers are fresh';
      } else if (summary.last_daily_refresh) {
        status.textContent = `Last refreshed ${formatDateTime(summary.last_daily_refresh)}`;
      } else {
        status.textContent = 'Provider status unavailable';
      }
    }

    async function loadProviderStatus() {
      const data = await api('/api/data-health?compact=true');
      const providers = sortProviderHealth(data.providers || []);
      state.providerHealth = { providers, summary: data.summary || {}, operations: data.operations || {} };
      renderTodayProviderStatus(providers, data.summary || {});
      renderGlobalHealthStrip(providers, data.summary || {}, data.operations || {});
    }

    async function loadDataHealth() {
      const data = await api('/api/data-health');
      const providers = sortProviderHealth(data.providers || []);
      const summary = data.summary || {};
      renderTodayProviderStatus(providers, summary);
      const usage = data.api_usage || {};
      const totals = usage.totals || {};
      const endpointPerformance = data.endpoint_performance || {};
      const feedPerformance = data.recommendation_feed_performance || {};
      const endpointRoutes = endpointPerformance.routes || [];
      const operations = data.operations || {};
      const scheduler = operations.scheduler || {};
      const shadow = operations.shadow_evaluation || {};
      const shadowSettlement = operations.shadow_settlement || {};
      const researchMemory = operations.research_memory || {};
      const completeBoard = operations.complete_board || {};
      const boardRetry = completeBoard.settlement_retry || {};
      state.providerHealth = { providers, summary, operations };
      renderGlobalHealthStrip(providers, summary, operations);
      $('data-health-list').innerHTML = `
        <div class="suggestion compact-suggestion">
          <div class="suggestion-top">
            <strong>${Number(summary.connected || 0)}/${Number(summary.total || 0)} sources available</strong>
            <span class="status-pill ${summary.warnings ? 'status-warning' : 'status-connected'}">${Number(summary.warnings || 0)} warnings</span>
          </div>
          <p>${summary.last_daily_refresh ? `Last scheduled provider refresh ${formatDateTime(summary.last_daily_refresh)}` : 'No scheduled provider refresh recorded yet.'}</p>
          <p>${Number(usage.requests_avoided || 0)} provider calls avoided · ${Number(totals.network_requests || 0)} network requests · ${Number(usage.avoidance_pct || 0).toFixed(1)}% cache efficiency · ${Number(totals.stale_fallbacks || 0)} stale fallbacks</p>
          <p>${Number(feedPerformance.captures || 0)} recommendation-board snapshots saved · ${Number(feedPerformance.reuses || 0)} duplicate writes avoided · ${feedPerformance.p95_fetch_ms == null ? 'No board timing yet' : `${Number(feedPerformance.p95_fetch_ms).toFixed(0)} ms p95 board retrieval`} · ${feedPerformance.p95_capture_ms == null ? 'No snapshot timing yet' : `${Number(feedPerformance.p95_capture_ms).toFixed(0)} ms p95 snapshot save`}</p>
        </div>
        <div class="suggestion compact-suggestion health-${operations.status === 'degraded' ? 'degraded' : 'fresh'}">
          <div class="suggestion-top">
            <strong>Evidence collection</strong>
            <span class="status-pill ${operations.status === 'degraded' ? 'status-warning' : 'status-connected'}">${operations.status === 'degraded' ? 'Needs attention' : 'Operational'}</span>
          </div>
          <p>${Number(shadow.settled || 0)}/${Number(shadow.queued || 0)} shadow predictions settled across ${Number(shadow.cohorts || 0)} daily cohorts.</p>
          <p>${Number(researchMemory.active || 0)} active research facts · ${Number(researchMemory.outcome_linked || 0)} linked to settled outcomes · ${Number(researchMemory.expired || 0)} expired facts retained for audit.</p>
          <p>${Number(completeBoard.settled || 0).toLocaleString()} provider-board observations settled · ${Number(boardRetry.due || 0).toLocaleString()} retries due · ${Number(boardRetry.deferred || 0).toLocaleString()} waiting.</p>
          ${(boardRetry.items || []).length ? `
            <details class="compact-details">
              <summary>Review blocked provider-board results</summary>
              ${(boardRetry.items || []).map((item) => `
                <div class="settlement-diagnostic">
                  <strong>${escapeHtml(item.player || 'Unknown player')} · ${escapeHtml(item.stat || 'Unknown stat')}</strong>
                  <p class="subtle">${escapeHtml(item.sport || 'Unknown sport')} · ${escapeHtml(item.provider || 'Provider unavailable')} · ${escapeHtml(item.game || 'Game unavailable')}</p>
                  <p>${escapeHtml(item.blocking_reason || 'Waiting for a verified final box score.')}</p>
                  <p class="subtle">Checked ${Number(item.attempts || 0)} time${Number(item.attempts || 0) === 1 ? '' : 's'} · Next retry ${item.next_retry_at ? formatDateTime(item.next_retry_at) : 'not scheduled'}</p>
                </div>
              `).join('')}
            </details>
          ` : ''}
          <p class="subtle">Last scheduler check ${scheduler.ran_at ? formatDateTime(scheduler.ran_at) : 'not recorded'} · Queued ${escapeHtml(humanizeText((scheduler.jobs_queued || scheduler.jobs_run || []).join(', ') || 'none'))} · Last settlement attempt ${shadowSettlement.ran_at ? formatDateTime(shadowSettlement.ran_at) : 'not recorded'}</p>
          ${(operations.warnings || []).map((warning) => `<p class="human-error">${escapeHtml(warning)}</p>`).join('')}
          ${(scheduler.failures || []).map((failure) => `<p class="human-error">${escapeHtml(failure.job || 'Scheduled job')}: ${escapeHtml(failure.message || 'The job did not complete.')}</p>`).join('')}
        </div>
        ${providers.map((provider) => {
          const status = String(provider.status || 'unavailable');
          const statusClass = /^[a-z_]+$/i.test(status) ? status : 'unavailable';
          return `<div class="suggestion compact-suggestion health-${statusClass}">
            <div class="suggestion-top">
              <strong>${escapeHtml(provider.name)}</strong>
              <span class="status-pill status-${statusClass}">${escapeHtml(friendlyStatus(status))}</span>
            </div>
            <p>${escapeHtml(provider.purpose)} · ${escapeHtml(provider.message)}</p>
            <p class="subtle">
              ${escapeHtml(humanizeText(provider.data_role || 'Unclassified'))} ·
              ${escapeHtml(humanizeText(provider.settlement_suitability || 'Not for settlement'))} ·
              ${provider.officially_documented ? 'Officially documented' : 'Undocumented endpoint'} ·
              Contract ${escapeHtml(provider.contract_version || 'unversioned')}
            </p>
            <p class="subtle">Sports: ${(provider.supported_sports || []).length
              ? (provider.supported_sports || []).map((sport) => escapeHtml(sport === 'NCAAF' ? 'College Football' : sport)).join(' · ')
              : 'Coverage not declared'}</p>
            <p class="subtle">${provider.api_usage?.used_this_session
              ? `${Number(provider.api_usage.requests_avoided || 0)} calls avoided · ${Number(provider.api_usage.network_requests || 0)} network requests this session`
              : 'Not requested in this session yet'}</p>
          </div>`;
        }).join('')}
        <div class="suggestion compact-suggestion endpoint-performance-card">
          <div class="suggestion-top">
            <strong>App response times</strong>
            <span class="status-pill ${Number(endpointPerformance.slow_requests || 0) ? 'status-warning' : 'status-connected'}">${Number(endpointPerformance.slow_requests || 0)} slow calls</span>
          </div>
          <p>${Number(endpointPerformance.requests || 0)} recent API calls measured · slow threshold ${Number(endpointPerformance.slow_threshold_ms || 1000)} ms</p>
          <div class="endpoint-timing-list">
            ${endpointRoutes.slice(0, 8).map((route) => `
              <div class="endpoint-timing-row ${route.slow ? 'endpoint-slow' : ''}">
                <code>${escapeHtml(route.route)}</code>
                <span>${Number(route.average_ms || 0).toFixed(0)} ms avg</span>
                <span>${Number(route.p95_ms || 0).toFixed(0)} ms p95</span>
                <span>${Number(route.requests || 0)} calls</span>
              </div>
            `).join('') || '<p class="subtle">Response timing appears after the first app requests complete.</p>'}
          </div>
        </div>`;
      return data;
    }

    return { loadRuntimeStatus, loadProviderStatus, loadDataHealth, renderGlobalHealthStrip, renderTodayProviderStatus };
  }

  window.EdgeIQProviderHealth = { create };
})();
