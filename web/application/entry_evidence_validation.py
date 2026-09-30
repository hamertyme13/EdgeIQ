"""Resolve entry claims against immutable server-side market evidence."""
from __future__ import annotations

from collections.abc import Callable

from repository.repositories.leg_recommendation_snapshot_repository import LegRecommendationSnapshotRepository
from repository.repositories.provider_offer_snapshot_repository import ProviderOfferSnapshotRepository
from services.offer_snapshot import canonical_offer, evidence_status
from utils.entity_normalization import canonical_person_key
from utils.platforms import canonical_platform
from utils.stat_normalization import canonical_stat_label
from web.schemas.entries import EntryPayload


def validate_entry_evidence(
    payload: EntryPayload, *,
    get_offer: Callable[[str], dict | None] = ProviderOfferSnapshotRepository.get,
    get_recommendation: Callable[[str], dict | None] = LegRecommendationSnapshotRepository.get,
) -> dict:
    legs = []
    invalidations: list[str] = []
    warnings: list[str] = []
    seen_markets: set[tuple] = set()
    for index, prop in enumerate(payload.props, start=1):
        market = (canonical_person_key(prop.player), prop.sport.upper(),
                  canonical_stat_label(prop.stat), float(prop.line), prop.game_time or prop.game)
        errors = []
        notices = []
        if market in seen_markets:
            errors.append(f"Leg {index} duplicates a player, stat, line, and game already on this entry.")
        seen_markets.add(market)
        snapshot = get_offer(prop.offer_snapshot_id) if prop.offer_snapshot_id else None
        status = "UNKNOWN"
        verified_offer = False
        recommendation = None
        if prop.offer_snapshot_id and snapshot is None:
            errors.append(f"Leg {index} references an offer snapshot that is no longer available.")
        elif snapshot is None:
            notices.append(f"Leg {index} is manual or has no saved offer snapshot; provider terms are unverified.")
        else:
            submitted = canonical_offer(prop.model_dump())
            expected = {
                "provider": snapshot["provider"], "provider_offer_id": snapshot["provider_offer_id"],
                "provider_player_id": snapshot["provider_player_id"],
                "provider_event_id": snapshot["provider_event_id"],
                "player_key": snapshot["player_key"], "sport": snapshot["sport"],
                "game": snapshot["game"], "game_start": snapshot["game_start"],
                "stat": snapshot["stat"], "line": snapshot["line"],
                "offer_type": snapshot["offer_type"], "standard_line": snapshot["standard_line"],
                "baseline_line": snapshot["baseline_line"], "discounted": snapshot["discounted"],
                "premium": snapshot["premium"],
            }
            if submitted is None or any(submitted[key] != value for key, value in expected.items()):
                errors.append(f"Leg {index} no longer matches its saved provider offer. Reload the exact offer.")
            if canonical_platform(prop.platform) != canonical_platform(snapshot["provider"]):
                errors.append(f"Leg {index} belongs to a different sportsbook than its offer snapshot.")
            if prop.direction not in snapshot["allowed_directions"]:
                errors.append(f"Leg {index} direction is not allowed for this provider offer.")
            if canonical_platform(snapshot["provider"]) == "PrizePicks" and (
                snapshot["offer_type"] == "demon" or snapshot["premium"]
            ) and prop.direction == "Under":
                errors.append(f"Leg {index} cannot use Under on a PrizePicks premium offer.")
            status = evidence_status({
                "game_start": snapshot["game_start"],
                "provider_offer_observed_at": snapshot["last_observed_at"],
            })
            if status == "GAME_STARTED":
                errors.append(f"Leg {index} game has started; this is not a pregame offer.")
            elif status not in {"FRESH", "AGING"}:
                notices.append(f"Leg {index} provider evidence is {status.lower()}; refresh before relying on it.")
            verified_offer = not errors and status in {"FRESH", "AGING"} and bool(
                snapshot["provider_offer_id"] and snapshot["game_start"]
                and snapshot["source"] == "direct_verified"
            )
            if not verified_offer and not errors:
                notices.append(f"Leg {index} is a collector snapshot, not confirmed live sportsbook availability.")
        if prop.leg_recommendation_snapshot_id:
            recommendation = get_recommendation(prop.leg_recommendation_snapshot_id)
            if recommendation is None or (
                recommendation.get("offer_snapshot_id") != prop.offer_snapshot_id
                or recommendation.get("feed_snapshot_id") != prop.recommendation_snapshot_id
                or recommendation.get("direction") != prop.direction
                or recommendation.get("line") != float(prop.line)
            ):
                recommendation = None
                notices.append(f"Leg {index} recommendation ID does not match this exact offer and direction.")
        elif prop.recommendation_snapshot_id:
            notices.append(f"Leg {index} has only a legacy feed ID, not immutable per-leg model evidence.")
        recommendation_verified = bool(verified_offer and recommendation)
        invalidations.extend(errors)
        warnings.extend(notices)
        legs.append({
            "index": index, "offer_snapshot_id": prop.offer_snapshot_id,
            "recommendation_snapshot_id": prop.recommendation_snapshot_id,
            "leg_recommendation_snapshot_id": prop.leg_recommendation_snapshot_id,
            "verified_offer": verified_offer,
            "recommendation_verified": recommendation_verified,
            "offer_freshness": status, "warnings": notices, "invalidations": errors,
            "authoritative_recommendation": {
                key: recommendation.get(key)
                for key in ("projection", "confidence", "model_version", "feature_as_of")
            } if recommendation_verified and recommendation else {},
        })
    return {
        "valid": not invalidations, "verified_offer": bool(legs) and all(leg["verified_offer"] for leg in legs),
        "recommendation_verified": bool(legs) and all(leg["recommendation_verified"] for leg in legs),
        "legs": legs, "warnings": warnings, "invalidations": invalidations,
    }
