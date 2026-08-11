from __future__ import annotations

from collections.abc import Callable

from repository.repositories.entry_repository import EntryRepository
from repository.repositories.research_evidence_repository import ResearchEvidenceRepository
from repository.repositories.settings_repository import SettingsRepository


def pending_entries_payload(serialize_pending: Callable[[dict], dict]) -> dict:
    return {
        "entries": [
            serialize_pending(entry)
            for entry in EntryRepository.pending()
        ]
    }


def entry_progress_payload(
    *,
    auto_check: bool,
    refresh_providers: bool,
    market_detail: bool,
    auto_check_pending: Callable[..., dict],
    refresh_live_stats: Callable[[list[dict]], dict],
    backfill_game_times: Callable[[list[dict]], dict],
    serialize_progress: Callable[..., dict],
    entry_has_stat_data: Callable[[dict], bool],
    settlement_status_key: str,
    safe_json_loads: Callable[[str], dict],
) -> dict:
    auto_check_result = None
    if auto_check:
        auto_check_result = auto_check_pending(
            allow_estimates=False,
            refresh_providers=refresh_providers,
        )
    pending = EntryRepository.pending()
    live_stats_sync = (
        refresh_live_stats(pending)
        if pending and refresh_providers
        else {
            "provider": "espn_live",
            "skipped": True,
            "imported": 0,
            "fetched_rows": 0,
            "errors": [],
        }
    )
    game_time_sync = (
        backfill_game_times(pending)
        if pending and refresh_providers
        else {
            "provider": "espn",
            "skipped": True,
            "updated": 0,
            "fetched_rows": 0,
            "errors": [],
        }
    )
    if game_time_sync.get("updated") or live_stats_sync.get("imported"):
        pending = EntryRepository.pending()
    entries = [
        serialize_progress(entry, include_market_detail=market_detail)
        for entry in pending
    ]
    overdue_legs = [
        {
            "entry_id": entry["id"],
            "player": leg.get("player", ""),
            "sport": leg.get("sport", ""),
            "stat": leg.get("stat", ""),
            **(leg.get("settlement_sla") or {}),
        }
        for entry in entries
        for leg in entry.get("legs", [])
        if (leg.get("settlement_sla") or {}).get("overdue")
    ]
    return {
        "entries": entries,
        "active": len(entries),
        "with_live_stats": sum(1 for entry in entries if entry_has_stat_data(entry)),
        "settlement_sla": {
            "status": "escalated" if overdue_legs else "clear",
            "overdue_legs": len(overdue_legs),
            "overdue_entries": len({row["entry_id"] for row in overdue_legs}),
            "legs": overdue_legs,
            "message": (
                f"{len(overdue_legs)} leg{'s are' if len(overdue_legs) != 1 else ' is'} beyond the final-stat SLA. "
                "Provider refresh and Recheck Final Stats should be escalated."
                if overdue_legs
                else "No pending legs are beyond the final-stat SLA."
            ),
        },
        "auto_check": auto_check_result,
        "game_time_sync": game_time_sync,
        "live_stats_sync": live_stats_sync,
        "settlement_refresh": safe_json_loads(
            SettingsRepository.get(settlement_status_key, "")
        ),
    }


def settle_entry_payload(
    entry_id: int,
    result: str,
    dnp_legs: int,
    dnp_mode: str,
    dashboard: Callable[[], dict],
) -> dict:
    EntryRepository.settle(entry_id, result, dnp_legs, dnp_mode)
    settled_entry = next((entry for entry in EntryRepository.all() if entry.get("id") == entry_id), None)
    evidence_updated = ResearchEvidenceRepository.record_outcome(settled_entry or {})
    return {
        "id": entry_id,
        "result": result,
        "status": "Settled",
        "research_evidence_updated": evidence_updated,
        "dashboard": dashboard(),
    }


def backfill_final_stats_payload(
    allow_estimates: bool,
    entry_leg_final_snapshots: Callable[..., list[dict]],
) -> dict:
    entries = [
        entry
        for entry in EntryRepository.all()
        if entry.get("status") == "Settled"
        and entry.get("result") in {"Win", "Loss", "Push", "DNP"}
    ]
    backfilled = 0
    leg_rows = 0
    estimated = 0
    for entry in entries:
        legs = entry_leg_final_snapshots(entry, allow_estimates=allow_estimates)
        if not legs:
            continue
        EntryRepository.store_settled_leg_results(entry["id"], legs)
        backfilled += 1
        leg_rows += len(legs)
        estimated += sum(
            1 for leg in legs
            if leg.get("source") == "projection_estimate"
        )
    return {
        "entries": len(entries),
        "backfilled": backfilled,
        "leg_rows": leg_rows,
        "estimated_leg_rows": estimated,
    }


def recheck_final_stats_payload(
    *,
    allow_estimates: bool,
    unknown_leg_count: Callable[[list[dict]], int],
    entries_needing_refresh: Callable[[list[dict]], list[dict]],
    refresh_final_stats: Callable[[list[dict]], dict],
    backfill_settled_results: Callable[[list[dict]], dict],
    auto_check_pending: Callable[..., dict],
    recheck_results: Callable[..., dict],
    quarantine_mismatched_evidence: Callable[[], dict],
) -> dict:
    before_entries = EntryRepository.all()
    unknown_before = unknown_leg_count(before_entries)
    refresh_entries = entries_needing_refresh(before_entries)
    provider_refresh = refresh_final_stats(refresh_entries)
    refreshed_entries = EntryRepository.all()
    backfill = backfill_settled_results(refreshed_entries)
    auto_check = auto_check_pending(
        allow_estimates=allow_estimates,
        refresh_providers=False,
    )
    after_entries = EntryRepository.all()
    result_review = recheck_results(
        after_entries,
        allow_estimates=allow_estimates,
    )
    evidence_quarantine = quarantine_mismatched_evidence()
    after_entries = EntryRepository.all()
    unknown_after = unknown_leg_count(after_entries)
    return {
        "entries": len(before_entries),
        "entries_refreshed": len(refresh_entries),
        "unknown_before": unknown_before,
        "unknown_after": unknown_after,
        "cleared_unknowns": max(0, unknown_before - unknown_after),
        "provider_refresh": provider_refresh,
        "backfill": backfill,
        "auto_check": auto_check,
        "result_review": result_review,
        "evidence_quarantine": evidence_quarantine,
    }


def recheck_final_stats_preview_payload(
    *,
    entries_needing_refresh: Callable[[list[dict]], list[dict]],
    preview_leg: Callable[[dict, dict], dict],
) -> dict:
    """Describe a recheck without fetching providers or changing stored records."""
    entries = EntryRepository.all()
    targets = entries_needing_refresh(entries)
    items: list[dict] = []
    affected_entries: set[int] = set()
    for entry in targets:
        entry_id = int(entry.get("id") or 0)
        for prop in entry.get("props", []):
            item = preview_leg(entry, prop)
            if item.get("will_change"):
                affected_entries.add(entry_id)
            items.append({"entry_id": entry_id, **item})

    changes = sum(1 for item in items if item.get("will_change"))
    waiting = sum(1 for item in items if item.get("action") in {"refresh_provider", "wait_for_final"})
    return {
        "read_only": True,
        "entries_reviewed": len(targets),
        "legs_reviewed": len(items),
        "entries_with_local_changes": len(affected_entries),
        "local_changes": changes,
        "provider_refresh_needed": waiting,
        "items": items[:200],
        "message": (
            f"Preview found {changes} locally verifiable leg update{'s' if changes != 1 else ''}. "
            f"{waiting} leg{'s still need' if waiting != 1 else ' still needs'} a provider refresh or final box score."
        ),
    }


def classify_default_wagers_payload(dashboard: Callable[[], dict]) -> dict:
    result = EntryRepository.classify_missing_economics()
    return {**result, "dashboard": dashboard()}
