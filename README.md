# EdgeIQ

## v2.3 Local Research Copilot

EdgeIQ 2.3 turns Ask EdgeIQ into a local, evidence-grounded research workspace. It can research a player and stat from verified EdgeIQ records, narrate the daily briefing, compare settled wins and losses, inspect portfolio exposure, and explain why one recommendation was selected over alternatives. Responses use structured citations tied to the underlying snapshot, and unsupported citations or numeric claims are rejected in favor of a deterministic fallback.

Player research now writes immutable facts to a persistent evidence ledger. Each fact records its player, sport, stat, game, platform, source, source URL, capture time, expiration time, and structured payload. Current provider markets, line movement, injuries/news/weather availability, historical finals, and EdgeIQ forecast distributions are cached independently. Settled outcomes update evidence-level win/loss counters so future validation can measure which evidence sources were useful instead of treating generated language as memory.

Historical starter/bench splits, expected minutes or opportunities, and teammate context are stored as role evidence. Live lineup status is explicitly left unconfirmed unless a connected provider supplies it. Evidence-source reliability is exposed to the model only after settlement and is not eligible for weighting until it has at least 20 independent decisions.

Entry payout analysis uses exact-line forecast probabilities when available, builds a conservative pairwise correlation matrix, and runs deterministic Gaussian-copula Monte Carlo simulation. Results include provider-specific payout evidence, complete-card probability, independent versus correlation-adjusted probability, expected value, shared-outcome pairs, and exposure by player, game, team, stat, and direction.

Ollama is the default local language provider. Set `OLLAMA_MODEL` for text (default `llama3.1:8b`) and optionally install/set `OLLAMA_VISION_MODEL` (default `llama3.2-vision:11b`) for screenshot extraction. The lighter `llama3.2:3b` model remains available in the UI for faster reviews. Screenshot picks are still deduplicated and matched against live provider markets before they can enter the builder. The **Qualify Model** control checks structured output and citation compliance before a model is trusted for recommendation explanations.

EdgeIQ is a Python desktop, browser, and CLI application for player prop research, entry
building, bet tracking, and bankroll/performance review.

The current desktop app is a PyQt6 alpha with live prop feeds, line shopping,
single-prop analysis, multi-prop entry checks, injury context, and bet history
analytics.

## Features

- Desktop dashboard for bankroll, record, ROI, streaks, drawdown, and top props
- PrizePicks and Underdog projection fetching with short-lived local caching
- Single-prop EV, edge, confidence, Kelly, and line-shopping tools
- Multi-prop entry builder with correlation warnings
- Portfolio-aware entry ranking with active paid-entry line monitoring
- Verified-history projection distributions with exact-line probabilities, ranges, and uncertainty drivers
- Visual player research with recent, location, role, opponent, market-line, and sensitivity context
- Bet tracker with sport, platform, stat type, result, and profit tracking
- CLI workflows for quick calculations and prop/entry building
- Local SQLite persistence

## Requirements

- Python 3.11+
- A virtual environment is recommended

Install dependencies:

```bash
pip install -r requirements.txt
```

For development with validation tooling:

```bash
pip install -e ".[dev]"
```

## Configuration

Create a `.env` file in the project root when you need local overrides:

```bash
STARTING_BANKROLL=500
ODDS_API_KEY=your_odds_api_key
EDGEIQ_ODDS_CACHE_SECONDS=180
# Optional: up to 10 sportsbook/DFS keys keeps each player-market request in one quota region.
EDGEIQ_ODDS_BOOKMAKERS=draftkings,fanduel,betmgm,williamhill_us,fanatics,prizepicks,underdog,pick6
OPENAI_API_KEY=your_openai_api_key
BALLDONTLIE_API_KEY=your_balldontlie_api_key
NEWSAPI_KEY=your_newsapi_key
OPENWEATHER_API_KEY=your_openweather_api_key
SPORTSDATAIO_API_KEY=your_sportsdataio_api_key
PANDASCORE_API_KEY=your_pandascore_api_key
PANDASCORE_HISTORICAL_STATS_ENABLED=true  # only after the player-stat endpoint succeeds
# Optional alert delivery. Email uses SMTP; SMS uses Twilio.
EDGEIQ_SMTP_HOST=smtp.example.com
EDGEIQ_SMTP_PORT=587
EDGEIQ_SMTP_FROM=edgeiq@example.com
EDGEIQ_SMTP_USERNAME=your_smtp_username
EDGEIQ_SMTP_PASSWORD=your_smtp_password
EDGEIQ_SMTP_TLS=true
TWILIO_ACCOUNT_SID=your_twilio_account_sid
TWILIO_AUTH_TOKEN=your_twilio_auth_token
TWILIO_FROM_NUMBER=+15555555555
DATABASE_URL=sqlite:///edgeiq.db
```

`DATABASE_URL` defaults to `sqlite:///edgeiq.db`. Runtime files such as the
SQLite database, provider cache, and logs are intentionally ignored by git.

## Run

Permanent macOS Desktop launcher:

```bash
scripts/install_desktop_app.sh
```

This rebuilds `~/Desktop/EdgeIQ.app` with the branded icon and a launcher that
finds a Python runtime with `uvicorn`, skips stale local servers, and opens the
browser app on the first available EdgeIQ port. Keep the Terminal window open
while using the app.

Installation also registers the `com.edgeiq.runtime-reliability` macOS
LaunchAgent. It checks scheduled provider refresh, settlement, line snapshot,
and calibration jobs every 15 minutes, even when the browser is closed. Logs
are stored in `~/Library/Logs/EdgeIQ/`.

Python desktop app:

```bash
python desktop.py
```

Browser app:

```bash
uvicorn web.app:app --reload
```

Then open `http://127.0.0.1:8000`.

CLI app:

```bash
python app.py
```

## Test

```bash
ruff check .
mypy analytics/release_validation.py services/data_management.py services/odds.py utils/entity_normalization.py web/application web/routers web/schemas
pytest
```

Tests use an isolated temporary SQLite database. Provider contracts use saved
fixtures, and migration tests exercise upgrades from legacy schemas. Live
provider calls are avoided.

## v2.2 Validation

Results contains an evidence-gated release scorecard for settled paper entries,
verified individual props, segmented accuracy, chronological validation,
closing-line value, calibration error, and forecast-distribution coverage. The model remains in
`collecting_evidence` until every release gate passes.

The primary workflow now begins in Advantage Center: check provider freshness,
rank opportunities, inspect supporting evidence, add a paper entry, settle it
from final stats, and review calibration.

See [docs/RELEASE_2_2.md](docs/RELEASE_2_2.md) for the release standard.

## Backup And Export

Use **Create Backup** or **Export Data** under Today > System Status > Data
Health. SQLite backups are written to `.edgeiq_backups/`; portable versioned
JSON exports are written to `.edgeiq_exports/`. Both directories and the live
database are excluded from Git.

## Database Migrations

Fresh databases should be created through the versioned migration history:

```bash
alembic upgrade head
```

An existing EdgeIQ database already managed by the earlier lightweight migrator
should be backed up, verified on the current app version, and adopted once with
`alembic stamp head`. New schema changes should be added with
`alembic revision --autogenerate -m "description"` and reviewed before use.

## EdgeIQ Local Model

Ask EdgeIQ does not require OpenAI to return recommendations. The app ranks
parlays with `edgeiq-local-v1.0`, a local scoring layer that combines projected
edge, confidence, data quality, source signals, market trend, correlation
penalties, and settled-entry feedback. OpenAI remains optional for richer
language explanations and screenshot extraction.

### Free Local AI With Ollama

Ask EdgeIQ uses Ollama before OpenAI when a local model is available. EdgeIQ
continues to calculate rankings, projections, confidence, and validation itself;
Ollama explains only the evidence supplied by the app.

1. Install and open Ollama from <https://ollama.com/download>.
2. Download the default lightweight model:

```bash
ollama pull llama3.1:8b
```

3. Restart EdgeIQ. No API key or usage credits are required.

Optional configuration:

```bash
OLLAMA_ENABLED=true
OLLAMA_MODEL=llama3.1:8b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

If Ollama is unavailable, Ask EdgeIQ tries OpenAI when configured and otherwise
uses the deterministic EdgeIQ Local review.

## Data Providers

EdgeIQ currently normalizes player prop data from:

- PrizePicks
- Underdog
- Sleeper when configured with a prop feed URL or file
- The Odds API for game odds, exact-line multi-book player-prop consensus,
  no-vig probabilities, and indicative PrizePicks/Underdog DFS offer
  multipliers when `ODDS_API_KEY` is configured
- Ollama for free local Ask EdgeIQ explanations and entry reviews
- OpenAI as an optional fallback for AI explanations and screenshot extraction
- Ball Don't Lie for optional stats/props context when `BALLDONTLIE_API_KEY` or `BALLDONTLIE_PROPS_URL` is configured
- NewsAPI for recent player/team context when `NEWSAPI_KEY` is configured
- OpenWeather for outdoor NFL/MLB weather context when `OPENWEATHER_API_KEY` is configured
- ESPN public box-score endpoints for automatic NBA/WNBA final-stat grading;
  these endpoints are contract-tested but are not an officially documented API
- SportsDataIO as supplemental context only

Provider calls use `.edgeiq_cache/providers` for a short cache and stale fallback
so the desktop app can continue showing recent data if a feed is temporarily
unavailable.

Sleeper's documented public API is read-only and provides fantasy league,
player, and trending add/drop data without an API token. EdgeIQ uses those
Sleeper trends as an NFL source-fusion signal and caches the large player list
for one day, matching Sleeper's usage guidance. Sleeper prop lines still need a
configured CSV/JSON source.

Connect those prop feeds with CSV/JSON sources using:

```bash
EDGEIQ_SLEEPER_PROPS_URL=https://example.com/sleeper-props.json
```

Sleeper's public API does not require a key. Feed rows should include at least
player, sport/league, stat, and line fields; common aliases like `player_name`,
`stat_type`, `line_score`, `matchup`, and `trending_count` are normalized
automatically.

## Website Integration

The browser app exposes the same EdgeIQ workflows through FastAPI endpoints and
a Rogue Circuit themed web UI. Link to the deployed EdgeIQ URL from your website,
or embed API calls from another frontend.

Useful environment variables:

```bash
DATABASE_URL=sqlite:///edgeiq.db
EDGEIQ_ALLOWED_ORIGINS=https://your-website.example
```

For hosted use, install the production database driver, point `DATABASE_URL` at
PostgreSQL, run migrations, and set `EDGEIQ_ALLOWED_ORIGINS` to your website
origin. SQLite remains the supported single-user desktop default.

```bash
pip install -e ".[production]"
export DATABASE_URL="postgresql+psycopg://edgeiq:password@localhost/edgeiq"
alembic upgrade head
```

The hosted runtime uses connection health checks and a bounded pool. Tune
`EDGEIQ_DB_POOL_SIZE` and `EDGEIQ_DB_MAX_OVERFLOW` only after measuring the
deployed workload.

## Alpha Notes

This is still an alpha. The v2.2 scorecard intentionally separates implemented
validation infrastructure from statistically proven performance; no win-rate or
profitability claim is made until the evidence gates pass.
