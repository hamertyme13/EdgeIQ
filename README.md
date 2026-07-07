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
DATABASE_URL=sqlite:///edgeiq.db
```

`DATABASE_URL` defaults to `sqlite:///edgeiq.db`. Runtime files such as the
SQLite database, provider cache, and logs are intentionally ignored by git.

## Run

Desktop app:

```bash
python desktop.py
```

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
- The Odds API for sportsbook game odds when `ODDS_API_KEY` is configured

Provider calls use `.edgeiq_cache/providers` for a short cache and stale fallback
so the desktop app can continue showing recent data if a feed is temporarily
unavailable.

## Alpha Notes

This is still an alpha. The app is useful locally, but the next production-grade
steps are broader UI verification, provider contract tests, a formal migration
tool if the schema keeps growing, and packaged desktop distribution.
- Python
- Rich
