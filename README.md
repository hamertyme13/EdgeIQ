# EdgeIQ

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

## Data Providers

EdgeIQ currently normalizes player prop data from:

- PrizePicks
- Underdog
- Sleeper when configured with a prop feed URL or file
- The Odds API for game odds, exact-line multi-book player-prop consensus,
  no-vig probabilities, and indicative PrizePicks/Underdog DFS offer
  multipliers when `ODDS_API_KEY` is configured
- OpenAI for AI parlay explanations, entry review, and screenshot extraction
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

For hosted use, point `DATABASE_URL` at Postgres or another SQLAlchemy-supported
database and set `EDGEIQ_ALLOWED_ORIGINS` to your website origin.

## Alpha Notes

This is still an alpha. The v2.2 scorecard intentionally separates implemented
validation infrastructure from statistically proven performance; no win-rate or
profitability claim is made until the evidence gates pass.
