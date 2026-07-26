(function mountEdgeIQShell() {
  window.EdgeIQShellLoaded = true;
  const root = document.getElementById("edgeiq-overlay-root");
  if (!root) return;
  root.innerHTML = `
    <aside id="recommendation-drawer" class="recommendation-drawer" hidden>
      <div class="drawer-backdrop" data-close-drawer></div>
      <div class="drawer-panel">
        <div class="panel-header">
          <div>
            <p class="eyebrow">Recommendation Logic</p>
            <h2 id="drawer-title">Why this pick?</h2>
          </div>
          <button class="secondary" data-close-drawer>Close</button>
        </div>
        <div id="drawer-content" class="drawer-content"></div>
      </div>
    </aside>

    <section id="mobile-slip" class="mobile-slip">
      <button id="mobile-slip-toggle" class="mobile-slip-toggle">
        <span>Bet Slip</span>
        <strong id="mobile-slip-count">0</strong>
      </button>
      <div id="mobile-slip-panel" class="mobile-slip-panel" hidden>
        <div class="suggestion-top">
          <strong>Current Entry</strong>
          <span class="subtle" id="mobile-slip-summary">No props loaded</span>
        </div>
        <div id="mobile-slip-legs" class="mobile-slip-legs"></div>
        <div class="form-grid compact-controls">
          <input id="mobile-slip-wager" type="number" min="0" step="0.01" placeholder="Wager" />
          <input id="mobile-slip-multiplier" type="number" min="1" step="0.1" placeholder="Multiplier" />
        </div>
        <div class="button-row">
          <button id="mobile-analyze-entry">Analyze</button>
          <button id="mobile-place-entry" class="secondary">Place</button>
        </div>
      </div>
    </section>

    <section id="onboarding-modal" class="onboarding-modal" hidden>
      <div class="drawer-backdrop"></div>
      <div class="onboarding-panel">
        <p class="eyebrow">Welcome To EdgeIQ</p>
        <h2>Build your betting operating system</h2>
        <p>Pick the sports, platforms, and risk posture EdgeIQ should use when it wakes up and builds your daily briefing.</p>
        <form id="onboarding-form" class="form-grid">
          <input id="onboarding-bankroll" type="number" min="1" step="0.01" placeholder="Starting bankroll" />
          <select id="onboarding-platform">
            <option>PrizePicks</option>
            <option>Underdog</option>
            <option>Sleeper</option>
          </select>
          <select id="onboarding-sport">
            <option>WNBA</option>
            <option>NBA</option>
            <option>NFL</option>
            <option>MLB</option>
            <option>NHL</option>
            <option>All Sports</option>
          </select>
          <select id="onboarding-risk">
            <option value="paper_first">Paper-first</option>
            <option value="conservative">Loss protection</option>
            <option value="balanced">Balanced</option>
            <option value="aggressive">Aggressive</option>
          </select>
          <input id="onboarding-default-wager" type="number" min="0" step="0.01" placeholder="Default wager" />
          <button type="submit">Save Setup</button>
        </form>
        <div class="button-row">
          <button id="onboarding-upload-history" class="secondary">Import Past Results</button>
          <button id="onboarding-skip" class="secondary">Skip</button>
        </div>
      </div>
    </section>
  `;
}());
