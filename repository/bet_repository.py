from __future__ import annotations

from models.bet import Bet
from repository.database import SessionLocal, initialize_database
from repository.entities import BetEntity
from sqlalchemy import or_


class BetRepository:
    _schema_ready = False

    @staticmethod
    def _ensure_schema() -> None:
        if BetRepository._schema_ready:
            return
        initialize_database()
        BetRepository._schema_ready = True

    def save(self, bet: Bet) -> None:
        self._ensure_schema()
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
                source          = bet.source,
                source_entry_id = bet.source_entry_id,
                entry_mode      = bet.entry_mode,
            )
            session.add(entity)
            session.commit()

    def save_entry_result(self, entry: dict) -> None:
        self._ensure_schema()
        source_entry_id = int(entry["id"])
        bet = self._entry_to_bet(entry)
        with SessionLocal() as session:
            entity = (
                session.query(BetEntity)
                .filter(BetEntity.source == "edgeiq_entry")
                .filter(BetEntity.source_entry_id == source_entry_id)
                .first()
            )
            if entity is None:
                entity = BetEntity(source="edgeiq_entry", source_entry_id=source_entry_id)
                session.add(entity)

            entity.sport = bet.sport
            entity.game = bet.game
            entity.description = bet.description
            entity.odds = bet.odds
            entity.wager = bet.wager
            entity.result = bet.result
            entity.profit = bet.profit
            entity.platform = bet.platform
            entity.stat_type = bet.stat_type
            entity.win_probability = bet.win_probability
            entity.entry_mode = bet.entry_mode
            session.commit()

    def get_all(self, include_synced_entries: bool = False) -> list[Bet]:
        self._ensure_schema()
        with SessionLocal() as session:
            query = session.query(BetEntity)
            if not include_synced_entries:
                query = query.filter(or_(BetEntity.source.is_(None), BetEntity.source != "edgeiq_entry"))
            entities = query.all()
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
            source          = e.source or "manual",
            source_entry_id = e.source_entry_id,
            entry_mode      = e.entry_mode or "real",
            created_at      = getattr(e, "created_at", None),
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
    def _entry_to_bet(entry: dict) -> Bet:
        props = entry.get("props") or []
        sport = _dominant_value([prop.get("sport", "") for prop in props]) or "Entry"
        game = _dominant_value([prop.get("game", "") for prop in props]) or ""
        stat_type = _dominant_value([prop.get("stat", "") for prop in props]) or "Entry"
        description = _entry_description(entry, props)
        return Bet(
            sport=sport,
            game=game,
            description=description,
            odds=-110,
            wager=round(float(entry.get("wager") or 0.0), 2),
            result=entry.get("result", "") or "Push",
            profit=round(float(entry.get("profit") or 0.0), 2),
            platform=entry.get("platform", "") or "",
            stat_type=stat_type,
            win_probability=round(float(entry.get("average_confidence") or 0.0), 2),
            source="edgeiq_entry",
            source_entry_id=entry.get("id"),
            entry_mode=entry.get("entry_mode", "real") or "real",
        )

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


def _dominant_value(values: list[object]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _entry_description(entry: dict, props: list[dict]) -> str:
    if not props:
        return f"EdgeIQ entry #{entry.get('id', '')}".strip()
    leg_text = " + ".join(
        " ".join(
            part
            for part in (
                str(prop.get("player", "")).strip(),
                str(prop.get("direction", "Over") or "Over").strip(),
                str(prop.get("stat", "")).strip(),
                _format_line(prop.get("line")),
            )
            if part
        )
        for prop in props
    )
    return f"EdgeIQ entry #{entry.get('id')}: {leg_text}"


def _format_line(value: object) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value or "").strip()
