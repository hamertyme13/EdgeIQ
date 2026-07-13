# EdgeIQ

EdgeIQ is a Python desktop and CLI application for player prop research, entry
building, bet tracking, and bankroll/performance review.

The current desktop app is a PyQt6 alpha with live prop feeds, line shopping,
single-prop analysis, multi-prop entry checks, injury context, and bet history
analytics.

## Features

- Desktop dashboard for bankroll, record, ROI, streaks, drawdown, and top props
- PrizePicks and Underdog projection fetching with short-lived local caching
- Single-prop EV, edge, confidence, Kelly, and line-shopping tools
- Multi-prop entry builder with correlation warnings
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

For development with pytest:

```bash
pip install -e ".[dev]"
```

## Configuration

Create a `.env` file in the project root when you need local overrides:

```bash
STARTING_BANKROLL=500
ODDS_API_KEY=your_odds_api_key
OPENAI_API_KEY=your_openai_api_key
BALLDONTLIE_API_KEY=your_balldontlie_api_key
NEWSAPI_KEY=your_newsapi_key
OPENWEATHER_API_KEY=your_openweather_api_key
SPORTSDATAIO_API_KEY=your_sportsdataio_api_key
DATABASE_URL=sqlite:///edgeiq.db
```

`DATABASE_URL` defaults to `sqlite:///edgeiq.db`. Runtime files such as the
SQLite database, provider cache, and logs are intentionally ignored by git.

## Run

Desktop app:

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
pytest
```

The tests are focused on calculation, recommendation, correlation, display, and
repository smoke coverage. Live provider calls are avoided in tests.

## Data Providers

EdgeIQ currently normalizes player prop data from:

- PrizePicks
- Underdog
- Sleeper, Chalkboard, Betr, and Ball Don't Lie when configured with a feed URL or file
- The Odds API for sportsbook game odds when `ODDS_API_KEY` is configured
- OpenAI for AI parlay explanations, entry review, and screenshot extraction
- Ball Don't Lie for optional stats/props context when `BALLDONTLIE_API_KEY` or `BALLDONTLIE_PROPS_URL` is configured
- NewsAPI for recent player/team context when `NEWSAPI_KEY` is configured
- OpenWeather for outdoor NFL/MLB weather context when `OPENWEATHER_API_KEY` is configured
- ESPN public box scores for NBA/WNBA final-stat settlement
- SportsDataIO final stats when `SPORTSDATAIO_API_KEY` is configured

Provider calls use `.edgeiq_cache/providers` for a short cache and stale fallback
so the desktop app can continue showing recent data if a feed is temporarily
unavailable.

Sleeper's documented public API is read-only and provides fantasy league,
player, and trending add/drop data without an API token. EdgeIQ uses those
Sleeper trends as an NFL source-fusion signal, but Sleeper prop lines still need
a configured CSV/JSON source. Chalkboard and Betr also need configured prop
sources unless you have a private/exported feed.

Connect those prop feeds with CSV/JSON sources using:

```bash
EDGEIQ_SLEEPER_PROPS_URL=https://example.com/sleeper-props.json
EDGEIQ_CHALKBOARD_PROPS_FILE=/absolute/path/chalkboard-props.csv
EDGEIQ_BETR_PROPS_URL=https://example.com/betr-props.csv
```

Optional API-key headers are supported with `EDGEIQ_SLEEPER_API_KEY`,
`EDGEIQ_CHALKBOARD_API_KEY`, and `EDGEIQ_BETR_API_KEY`. Feed rows should include
at least player, sport/league, stat, and line fields; common aliases like
`player_name`, `stat_type`, `line_score`, `matchup`, and `trending_count` are
normalized automatically.

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

This is still an alpha. The app is useful locally, but the next production-grade
steps are broader UI verification, provider contract tests, a formal migration
tool if the schema keeps growing, and packaged desktop distribution.
