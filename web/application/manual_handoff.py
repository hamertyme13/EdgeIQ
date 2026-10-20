"""Conservative stake review for user-approved sportsbook handoff."""

from __future__ import annotations


def review_stake(
    *, wager: float, bankroll: float, open_exposure: float,
    strategy: dict, provider_balance: float | None,
    require_provider_balance: bool,
) -> dict:
    bankroll = max(0.0, float(bankroll))
    open_exposure = max(0.0, float(open_exposure))
    wager = max(0.0, float(wager))
    single_cap = bankroll * float(strategy["max_wager_pct"]) / 100
    exposure_room = max(0.0, bankroll * float(strategy["max_open_exposure_pct"]) / 100 - open_exposure)
    limits = [bankroll, single_cap, exposure_room]
    blocks = []
    if require_provider_balance:
        if provider_balance is None:
            blocks.append("Enter your current PrizePicks available balance before handoff; EdgeIQ cannot read it automatically.")
            limits.append(0.0)
        else:
            limits.append(max(0.0, provider_balance))
    if strategy.get("mode") == "paper":
        blocks.append("Bankroll strategy is set to paper-only; change it before preparing a paid handoff.")
        limits.append(0.0)
    if not bankroll:
        blocks.append("Set an EdgeIQ bankroll before sizing a paid entry.")
    if not wager:
        blocks.append("Enter a wager greater than zero.")
    maximum = round(max(0.0, min(limits)), 2)
    suggested = round(min(maximum, max(0.0, float(strategy["unit_size"]))), 2)
    if wager > maximum:
        blocks.append("The wager exceeds the available bankroll, sportsbook balance, or exposure limit.")
    return {
        "bankroll": round(bankroll, 2),
        "provider_balance": provider_balance,
        "open_exposure": round(open_exposure, 2),
        "maximum": maximum,
        "suggested": suggested,
        "requested": round(wager, 2),
        "blocks": blocks,
        "source": "Manually entered sportsbook balance; not synced with PrizePicks",
    }
