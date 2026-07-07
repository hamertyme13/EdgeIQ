from __future__ import annotations

from models.bet import Bet
from repository.database import SessionLocal
from repository.entities import BetEntity


class BetRepository:

    def save(self, bet: Bet) -> None:
        with SessionLocal() as session:
            entity = BetEntity(
                sport           = bet.sport,
                game            = bet.game,
                description     = bet.description,
                odds            = bet.odds,
                wager           = bet.wager,
                result          = bet.result,
                profit          = bet.profit,
                platform        = bet.platform,
                stat_type       = bet.stat_type,
                win_probability = bet.win_probability,
            )
            session.add(entity)
            session.commit()

    def get_all(self) -> list[Bet]:
        with SessionLocal() as session:
            entities = session.query(BetEntity).all()
            return [self._to_model(e) for e in entities]

    def count(self) -> int:
        with SessionLocal() as session:
            return session.query(BetEntity).count()

    def total_profit(self) -> float:
        bets = self.get_all()
        return sum(bet.profit for bet in bets)

    def dashboard_stats(self) -> dict:
        bets = self.get_all()

        if not bets:
            return self._empty_stats()

        wins = losses = pushes = 0
        total_profit = total_wagered = 0.0
        wagers = []
        profits = []

        for bet in bets:
            wagers.append(bet.wager)
            profits.append(bet.profit)
            total_profit  += bet.profit
            total_wagered += bet.wager

            if bet.result == "Win":
                wins += 1
            elif bet.result == "Loss":
                losses += 1
            else:
                pushes += 1

        roi     = (total_profit / total_wagered * 100) if total_wagered else 0
        average = sum(wagers) / len(wagers)

        # ── Streaks ───────────────────────────────────────────────────────────
        current_streak, best_streak, worst_streak = self._compute_streaks(bets)

        # ── Max drawdown ──────────────────────────────────────────────────────
        max_drawdown = self._compute_max_drawdown(profits)

        # ── By sport ─────────────────────────────────────────────────────────
        by_sport = self._group_by(bets, key=lambda b: b.sport or "Unknown")

        # ── By stat type ──────────────────────────────────────────────────────
        by_stat = self._group_by(bets, key=lambda b: b.stat_type or "Unknown")

        # ── By platform ──────────────────────────────────────────────────────
        by_platform = self._group_by(bets, key=lambda b: b.platform or "Unknown")

        # ── Bankroll curve (cumulative profit at each bet) ────────────────────
        bankroll_curve = []
        running = 0.0
        for p in profits:
            running += p
            bankroll_curve.append(round(running, 2))

        return {
            "wins":           wins,
            "losses":         losses,
            "pushes":         pushes,
            "record":         f"{wins}-{losses}",
            "profit":         round(total_profit, 2),
            "wagered":        round(total_wagered, 2),
            "roi":            round(roi, 2),
            "average":        round(average, 2),
            "largest_win":    max(profits),
            "largest_loss":   min(profits),
            "current_streak": current_streak,
            "best_streak":    best_streak,
            "worst_streak":   worst_streak,
            "max_drawdown":   round(max_drawdown, 2),
            "by_sport":       by_sport,
            "by_stat":        by_stat,
            "by_platform":    by_platform,
            "bankroll_curve": bankroll_curve,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_model(e: BetEntity) -> Bet:
        return Bet(
            sport           = e.sport,
            game            = e.game,
            description     = e.description,
            odds            = e.odds,
            wager           = e.wager,
            result          = e.result,
            profit          = e.profit,
            platform        = e.platform or "",
            stat_type       = e.stat_type or "",
            win_probability = e.win_probability or 0.0,
        )

    @staticmethod
    def _empty_stats() -> dict:
        return {
            "wins": 0, "losses": 0, "pushes": 0, "record": "0-0",
            "profit": 0, "wagered": 0, "roi": 0, "average": 0,
            "largest_win": 0, "largest_loss": 0,
            "current_streak": 0, "best_streak": 0, "worst_streak": 0,
            "max_drawdown": 0,
            "by_sport": {}, "by_stat": {}, "by_platform": {},
            "bankroll_curve": [],
        }

    @staticmethod
    def _compute_streaks(bets: list[Bet]) -> tuple[int, int, int]:
        """
        Returns (current_streak, best_win_streak, worst_loss_streak).
        Positive = win streak, negative = loss streak.
        """
        current = best = worst = 0

        for bet in bets:
            if bet.result == "Push":
                current = 0
                continue
            if bet.result == "Win":
                current = current + 1 if current >= 0 else 1
            else:
                current = current - 1 if current <= 0 else -1

            best  = max(best, current)
            worst = min(worst, current)

        return current, best, worst

    @staticmethod
    def _compute_max_drawdown(profits: list[float]) -> float:
        """Maximum peak-to-trough decline in cumulative profit."""
        peak = drawdown = 0.0
        cumulative = 0.0
        for p in profits:
            cumulative += p
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > drawdown:
                drawdown = dd
        return drawdown

    @staticmethod
    def _group_by(bets: list[Bet], key) -> dict[str, dict]:
        """
        Group bets by a key function and compute per-group stats.
        Returns dict of {group_name: {wins, losses, profit, roi, bets}}.
        """
        groups: dict[str, dict] = {}

        for bet in bets:
            k = key(bet)
            if k not in groups:
                groups[k] = {"wins": 0, "losses": 0, "bets": 0,
                              "profit": 0.0, "wagered": 0.0}
            g = groups[k]
            g["bets"]   += 1
            g["profit"] += bet.profit
            g["wagered"] += bet.wager
            if bet.result == "Win":
                g["wins"] += 1
            elif bet.result == "Loss":
                g["losses"] += 1

        for g in groups.values():
            g["profit"]  = round(g["profit"], 2)
            g["wagered"] = round(g["wagered"], 2)
            g["roi"]     = round((g["profit"] / g["wagered"] * 100) if g["wagered"] else 0, 2)
            g["win_pct"] = round((g["wins"] / g["bets"] * 100) if g["bets"] else 0, 1)

        return groups
