# Game model evidence sprint

The new `edgeiq-game-context-v2` challenger remains shadow-only. No game model is
promoted or made eligible for paid recommendations by this release.

## Historical baseline

- Official ESPN completed games are collected independently of recommendations
  and stored as `verified_team_game` records in the existing research evidence
  ledger. The provider game ID, oriented team names and aliases, final scores,
  start time, source URL, capture time, and available possession pace are retained.
- NBA/WNBA game scans refresh the previous two dates and backfill five additional
  dates per successful daily run, bounded to 180 days. Coverage builds gradually;
  an empty or failed provider response is not manufactured into history.
- Features exclude future games and deduplicate outcomes. Evidence must have been
  captured before the forecast cutoff. The sample size is the smaller of the two
  teams' available game counts.
- The historical baseline uses recent and home/away win rates shrunk toward 50%,
  and score expectations from team offense and opponent defense. It does not use
  market prices for its win probability or expected scores.
- All three game forecasts share a generation timestamp and are saved in the
  existing game prediction ledger. Settlement matches both teams and start time
  across ESPN and odds-provider identities; ambiguous matches stay unresolved.

## Challenger features

Recent win rate, scoring differential, points scored/allowed, venue win splits,
rest, and possession-based pace are recorded. Pace requires complete team box
scores and is normalized for overtime; absent possession data stays unavailable.
Current sourced injury reports are retained with timestamps. Injury effects are
not assigned invented numerical weights.

The market champion's calculations remain unchanged. The challenger uses a
bounded historical residual. Prop forecasts retain their production estimates
and log `game_context_influenced_prop` only when the shadow opportunity factor
differs from 1.0.

## Promotion

Promotion uses one shared three-model cohort per sport/game, with all forecasts
recorded before the start and a verified final outcome recorded afterward. Rows
without historical samples, incomplete cohorts, contradictory outcomes, and
post-start forecasts are excluded. The latest 25% of independent eligible games
form the holdout. Both baseline comparisons and all displayed promotion metrics
use that same holdout.

The gate requires at least 200 holdout games, Brier score at most 0.20,
calibration gap at most 7.5 percentage points, and strictly better Brier scores
than both baselines. With a 25% holdout, this ordinarily requires 800 eligible
independent games. A numerical zero is accepted as a valid metric.

## Verification and operations

The CI type-check scope now includes the game modules. Lint/type errors and a
clipped entry action were repaired. The visual test follows the current Model
Lab navigation and clears obsolete reports before starting.

GitHub run 34644050399 stopped before any job steps: its annotation says the
account is locked due to a billing issue. Local checks cannot remove that account
restriction or establish a green hosted run.

A live isolated-database probe for WNBA 2025-09-09 retrieved five official finals,
stored ten team evidence records, retrieved five independent games, and found
possession pace for all five. It did not modify the user's production ledger.
