from __future__ import annotations

import math

from analytics.calibration import calibrate
from models.bet import Bet


def backtest_summary(bets: list[Bet], entries: list[dict]) -> dict:
    settled_entries = [
        entry for entry in entries
        if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss", "Push"}
    ]
    graded = _group_entries_by_grade(settled_entries)
    confidence = _entry_confidence_summary(settled_entries)
    bet_summary = _bet_summary(bets)
    entry_summary = {
        "count": len(settled_entries),
        "wins": sum(1 for entry in settled_entries if entry["result"] == "Win"),
        "losses": sum(1 for entry in settled_entries if entry["result"] == "Loss"),
        "pushes": sum(1 for entry in settled_entries if entry["result"] == "Push"),
        "profit": round(sum(entry.get("profit", 0.0) for entry in settled_entries), 2),
        "wagered": round(sum(entry.get("wager", 0.0) for entry in settled_entries), 2),
        "roi": _entry_roi(settled_entries),
        "by_grade": graded,
        "by_result": _group_entries_by_result(settled_entries),
        "confidence": confidence,
    }
    calibration_rows = _calibration_rows(bets, settled_entries)
    entry_calibration_rows = _entry_calibration_rows(settled_entries)
    calibration_sources = _calibration_source_summary(bets, settled_entries)
    records = _tracked_records(bets, settled_entries)
    calibration_summary = _calibration_summary(calibration_rows)
    segment_rankings = _segment_rankings(records)
    holdout = _time_holdout_validation(settled_entries)
    walk_forward = _walk_forward_validation(settled_entries)

    return {
        "bets": bet_summary,
        "entries": entry_summary,
        "tracked": _combined_summary(bet_summary, entry_summary),
        "calibration": calibration_rows,
        "entry_calibration": entry_calibration_rows,
        "calibration_sources": calibration_sources,
        "scorecard": _model_scorecard(bet_summary, entry_summary, calibration_summary, holdout, walk_forward),
        "holdout_validation": holdout,
        "walk_forward_validation": walk_forward,
        "what_works": segment_rankings["works"],
        "what_fails": segment_rankings["fails"],
        "calibration_rules": _calibration_rules(calibration_rows, segment_rankings["all"]),
    }


def _bet_summary(bets: list[Bet]) -> dict:
    graded = [bet for bet in bets if bet.result in {"Win", "Loss", "Push"}]
    wins = sum(1 for bet in graded if bet.result == "Win")
    losses = sum(1 for bet in graded if bet.result == "Loss")
    pushes = sum(1 for bet in graded if bet.result == "Push")
    wagered = sum(bet.wager for bet in graded)
    profit = sum(bet.profit for bet in graded)
    return {
        "count": len(graded),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round(wins / (wins + losses) * 100, 1) if wins + losses else 0.0,
        "profit": round(profit, 2),
        "wagered": round(wagered, 2),
        "roi": round(profit / wagered * 100, 2) if wagered else 0.0,
    }


def _combined_summary(bets: dict, entries: dict) -> dict:
    wins = bets.get("wins", 0) + entries.get("wins", 0)
    losses = bets.get("losses", 0) + entries.get("losses", 0)
    pushes = bets.get("pushes", 0) + entries.get("pushes", 0)
    wagered = float(bets.get("wagered", 0.0)) + float(entries.get("wagered", 0.0))
    profit = float(bets.get("profit", 0.0)) + float(entries.get("profit", 0.0))
    decisions = wins + losses
    return {
        "count": int(bets.get("count", 0)) + int(entries.get("count", 0)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round((wins / decisions * 100) if decisions else 0.0, 1),
        "profit": round(profit, 2),
        "wagered": round(wagered, 2),
        "roi": round((profit / wagered * 100) if wagered else 0.0, 2),
    }


def _group_entries_by_grade(entries: list[dict]) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for entry in entries:
        grade = entry.get("grade") or "Ungraded"
        group = groups.setdefault(grade, {"entries": 0, "wins": 0, "losses": 0, "pushes": 0})
        group["entries"] += 1
        if entry["result"] == "Win":
            group["wins"] += 1
        elif entry["result"] == "Loss":
            group["losses"] += 1
        else:
            group["pushes"] += 1

    for group in groups.values():
        decisions = group["wins"] + group["losses"]
        group["win_rate"] = round(group["wins"] / decisions * 100, 1) if decisions else 0.0
    return groups


def _group_entries_by_result(entries: list[dict]) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for entry in entries:
        result = entry.get("result") or "Unknown"
        group = groups.setdefault(result, {"entries": 0, "profit": 0.0, "wagered": 0.0})
        group["entries"] += 1
        group["profit"] += entry.get("profit", 0.0)
        group["wagered"] += entry.get("wager", 0.0)

    for group in groups.values():
        group["profit"] = round(group["profit"], 2)
        group["wagered"] = round(group["wagered"], 2)
        group["roi"] = round((group["profit"] / group["wagered"] * 100) if group["wagered"] else 0.0, 2)
    return groups


def _entry_roi(entries: list[dict]) -> float:
    wagered = sum(entry.get("wager", 0.0) for entry in entries)
    profit = sum(entry.get("profit", 0.0) for entry in entries)
    return round((profit / wagered * 100) if wagered else 0.0, 2)


def _entry_confidence_summary(entries: list[dict]) -> dict:
    decisions = [entry for entry in entries if entry["result"] in {"Win", "Loss"}]
    if not decisions:
        return {"average_confidence": 0.0, "actual_win_rate": 0.0, "edge": 0.0}
    joint_probabilities = [_entry_joint_probability(entry) for entry in decisions]
    avg_conf = sum(joint_probabilities) / len(joint_probabilities)
    avg_leg_conf = sum(float(entry.get("average_confidence") or 0.0) for entry in decisions) / len(decisions)
    actual = sum(1 for entry in decisions if entry["result"] == "Win") / len(decisions) * 100
    return {
        "average_confidence": round(avg_conf, 1),
        "average_card_probability": round(avg_conf, 1),
        "average_leg_confidence": round(avg_leg_conf, 1),
        "actual_win_rate": round(actual, 1),
        "edge": round(actual - avg_conf, 1),
    }


def _calibration_rows(bets: list[Bet], entries: list[dict]) -> list[dict]:
    rows = [
        {"win_probability": bet.win_probability, "result": bet.result}
        for bet in bets
        if bet.win_probability
    ]
    rows.extend(_prop_calibration_rows(entries))
    return _calibrated_buckets(rows)


def _entry_calibration_rows(entries: list[dict]) -> list[dict]:
    rows = [
        {"win_probability": _entry_joint_probability(entry), "result": entry.get("result", "")}
        for entry in entries
        if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss", "Push"}
    ]
    return _calibrated_buckets(rows)


def _calibrated_buckets(rows: list[dict]) -> list[dict]:
    return [
        {
            "label": bucket.label,
            "predicted_low": bucket.predicted_low,
            "predicted_high": bucket.predicted_high,
            "bets": bucket.bets,
            "wins": bucket.wins,
            "actual_pct": round(bucket.actual_pct, 1),
            "predicted_mid": bucket.predicted_mid,
            "error": round(bucket.error, 1),
        }
        for bucket in calibrate(rows)
    ]


def _entry_joint_probability(entry: dict) -> float:
    probabilities = []
    for prop in entry.get("props") or []:
        confidence = prop.get("confidence")
        if confidence in (None, ""):
            continue
        probabilities.append(max(0.01, min(0.99, float(confidence) / 100.0)))
    if probabilities:
        return math.prod(probabilities) * 100.0
    return max(0.0, min(100.0, float(entry.get("average_confidence") or 0.0)))


def _prop_calibration_rows(entries: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for entry in entries:
        if entry.get("status") != "Settled":
            continue
        for prop in entry.get("props") or []:
            result = prop.get("final_result") or ""
            confidence = prop.get("confidence")
            source = str(prop.get("final_source") or "").strip().lower()
            if (
                result not in {"Win", "Loss", "Push"}
                or confidence in (None, "")
                or source in {"", "unknown", "unmatched", "projection_estimate"}
            ):
                continue
            rows.append({"win_probability": float(confidence), "result": result})
    return rows


def _calibration_source_summary(bets: list[Bet], entries: list[dict]) -> dict:
    bet_rows = sum(1 for bet in bets if bet.win_probability and bet.result in {"Win", "Loss", "Push"})
    entry_rows = sum(1 for entry in entries if entry.get("status") == "Settled" and entry.get("result") in {"Win", "Loss", "Push"})
    prop_rows = _prop_calibration_rows(entries)
    source_counts: dict[str, int] = {}
    for entry in entries:
        if entry.get("status") != "Settled":
            continue
        for prop in entry.get("props") or []:
            if prop.get("final_result") not in {"Win", "Loss", "Push"}:
                continue
            source = prop.get("final_source") or "unknown"
            source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "bet_rows": bet_rows,
        "entry_rows": entry_rows,
        "prop_rows": len(prop_rows),
        "total_rows": bet_rows + len(prop_rows),
        "entry_calibration_rows": entry_rows,
        "provider_rows": sum(count for source, count in source_counts.items() if source not in {"", "unknown", "unmatched", "projection_estimate"}),
        "estimated_rows": source_counts.get("projection_estimate", 0),
        "sources": source_counts,
    }


def _model_scorecard(
    bets: dict,
    entries: dict,
    calibration_summary: dict,
    holdout: dict | None = None,
    walk_forward: dict | None = None,
) -> dict:
    tracked = _combined_summary(bets, entries)
    win_rate = float(tracked.get("win_rate") or 0.0)
    roi = float(tracked.get("roi") or 0.0)
    calibration_gap = float(calibration_summary.get("average_abs_error") or 0.0)
    sample_size = int(tracked.get("count") or 0)
    score = 50.0
    score += min(25.0, max(-25.0, roi * 0.18))
    score += min(20.0, max(-20.0, (win_rate - 50.0) * 0.7))
    score -= min(25.0, calibration_gap * 0.6)
    if sample_size < 10:
        score -= 10.0
    if holdout and holdout.get("ready") and not holdout.get("passed"):
        score -= 15.0
    if walk_forward and walk_forward.get("ready") and not walk_forward.get("passed"):
        score -= 15.0
    verdict = "Collect more samples"
    if sample_size >= 10 and score >= 70:
        verdict = "Model is outperforming"
    elif sample_size >= 10 and score >= 55:
        verdict = "Model is usable"
    elif sample_size >= 10:
        verdict = "Model needs calibration"
    return {
        "score": round(max(0.0, min(100.0, score)), 1),
        "verdict": verdict,
        "sample_size": sample_size,
        "win_rate": win_rate,
        "roi": roi,
        "profit": tracked.get("profit", 0.0),
        "calibration_gap": calibration_gap,
        "entry_confidence_gap": entries.get("confidence", {}).get("edge", 0.0),
        "holdout_passed": bool((holdout or {}).get("passed")),
        "walk_forward_passed": bool((walk_forward or {}).get("passed")),
        "recommendation": _scorecard_recommendation(sample_size, score, roi, calibration_gap),
    }


def _time_holdout_validation(entries: list[dict]) -> dict:
    decisions = [entry for entry in entries if entry.get("result") in {"Win", "Loss"}]
    decisions.sort(key=_entry_time_key)
    if len(decisions) < 20:
        return {
            "ready": False,
            "passed": False,
            "train_count": max(0, len(decisions) - 1),
            "holdout_count": min(1, len(decisions)),
            "message": "At least 20 settled decisions are required for chronological holdout validation.",
        }
    holdout_count = max(10, math.ceil(len(decisions) * 0.2))
    train = decisions[:-holdout_count]
    holdout = decisions[-holdout_count:]
    predicted = sum(_entry_joint_probability(entry) for entry in holdout) / len(holdout)
    actual = sum(1 for entry in holdout if entry.get("result") == "Win") / len(holdout) * 100
    gap = actual - predicted
    passed = abs(gap) <= 15 and actual >= max(10.0, predicted - 10.0)
    return {
        "ready": True,
        "passed": passed,
        "train_count": len(train),
        "holdout_count": len(holdout),
        "predicted_win_rate": round(predicted, 1),
        "actual_win_rate": round(actual, 1),
        "calibration_gap": round(gap, 1),
        "start_at": str(_entry_time_key(holdout[0])) if holdout else "",
        "message": (
            "Recent unseen results are within the release tolerance."
            if passed
            else "Recent unseen results are outside the release tolerance; keep paid mode disabled."
        ),
    }


def _walk_forward_validation(entries: list[dict], minimum_train: int = 10) -> dict:
    decisions = [
        entry for entry in entries
        if entry.get("result") in {"Win", "Loss"} and _entry_decision_time(entry) is not None
    ]
    decisions.sort(key=lambda entry: _entry_decision_time(entry) or _minimum_datetime())
    predictions = []
    excluded = 0
    for target in decisions:
        decision_time = _entry_decision_time(target)
        if decision_time is None:
            excluded += 1
            continue
        train = [
            row for row in decisions
            if row is not target
            and (_entry_decision_time(row) or _minimum_datetime()) < decision_time
            and _entry_truth_available_time(row) is not None
            and _entry_truth_available_time(row) <= decision_time
        ]
        if len(train) < minimum_train:
            excluded += 1
            continue
        raw = max(0.01, min(0.99, _entry_joint_probability(target) / 100.0))
        calibrated, segment_count = _walk_forward_probability(raw, target, train)
        actual = 1.0 if target.get("result") == "Win" else 0.0
        predictions.append({
            "entry_id": target.get("id"),
            "predicted_at": decision_time.isoformat(),
            "train_count": len(train),
            "segment_count": segment_count,
            "raw_probability": round(raw * 100.0, 1),
            "calibrated_probability": round(calibrated * 100.0, 1),
            "actual": int(actual),
            "brier": round((calibrated - actual) ** 2, 4),
        })

    if len(predictions) < 10:
        return {
            "ready": False,
            "passed": False,
            "folds": len(predictions),
            "minimum_train": minimum_train,
            "excluded_before_training_window": excluded,
            "leakage_free": True,
            "message": "At least 10 leakage-free walk-forward predictions are required.",
            "predictions": predictions[-20:],
        }

    brier = sum(row["brier"] for row in predictions) / len(predictions)
    raw_brier = sum(
        ((row["raw_probability"] / 100.0) - row["actual"]) ** 2
        for row in predictions
    ) / len(predictions)
    predicted = sum(row["calibrated_probability"] for row in predictions) / len(predictions)
    actual = sum(row["actual"] for row in predictions) / len(predictions) * 100.0
    gap = actual - predicted
    passed = brier <= raw_brier + 0.02 and abs(gap) <= 15.0
    return {
        "ready": True,
        "passed": passed,
        "folds": len(predictions),
        "minimum_train": minimum_train,
        "excluded_before_training_window": excluded,
        "leakage_free": True,
        "brier_score": round(brier, 4),
        "raw_brier_score": round(raw_brier, 4),
        "predicted_win_rate": round(predicted, 1),
        "actual_win_rate": round(actual, 1),
        "calibration_gap": round(gap, 1),
        "message": (
            "Walk-forward calibration is inside release tolerance without using future outcomes."
            if passed
            else "Walk-forward calibration is outside release tolerance; keep paid mode restricted."
        ),
        "predictions": predictions[-20:],
    }


def _walk_forward_probability(raw: float, target: dict, train: list[dict]) -> tuple[float, int]:
    target_sport = _primary_value(target.get("props") or [], "sport")
    peers = [
        row for row in train
        if abs((_entry_joint_probability(row) / 100.0) - raw) <= 0.15
        and _primary_value(row.get("props") or [], "sport") == target_sport
    ]
    if len(peers) < 5:
        peers = [row for row in train if abs((_entry_joint_probability(row) / 100.0) - raw) <= 0.15]
    prior_strength = 8.0
    wins = sum(1 for row in peers if row.get("result") == "Win")
    posterior = ((raw * prior_strength) + wins) / (prior_strength + len(peers))
    return max(0.01, min(0.99, posterior)), len(peers)


def _entry_decision_time(entry: dict):
    return _datetime_value(entry.get("placed_at") or entry.get("created_at"))


def _entry_truth_available_time(entry: dict):
    return _datetime_value(entry.get("settled_at"))


def _datetime_value(value):
    from datetime import datetime, timezone

    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _minimum_datetime():
    from datetime import datetime, timezone

    return datetime.min.replace(tzinfo=timezone.utc)


def _entry_time_key(entry: dict) -> str:
    value = entry.get("settled_at") or entry.get("placed_at") or entry.get("created_at") or ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _scorecard_recommendation(sample_size: int, score: float, roi: float, calibration_gap: float) -> str:
    if sample_size < 10:
        return "Use paper entries to build a larger calibration sample before increasing stake size."
    if roi < 0:
        return "Reduce exposure and route weak segments to paper-only until ROI recovers."
    if calibration_gap > 18:
        return "Keep recommendations, but discount confidence until predicted and actual win rates converge."
    if score >= 70:
        return "Lean into proven segments while continuing to log every result."
    return "Keep stake sizing conservative and let segment rules prune low-trust markets."


def _calibration_summary(rows: list[dict]) -> dict:
    total = sum(int(row.get("bets") or 0) for row in rows)
    if not total:
        return {"average_abs_error": 0.0, "total": 0}
    weighted_error = sum(abs(float(row.get("error") or 0.0)) * int(row.get("bets") or 0) for row in rows)
    return {"average_abs_error": round(weighted_error / total, 1), "total": total}


def _tracked_records(bets: list[Bet], entries: list[dict]) -> list[dict]:
    records: list[dict] = []
    for bet in bets:
        if bet.result not in {"Win", "Loss", "Push"}:
            continue
        records.append({
            "kind": "bet",
            "sport": bet.sport or "Unknown",
            "stat": bet.stat_type or "Unknown",
            "platform": bet.platform or "Unknown",
            "grade": "Imported",
            "confidence_band": _confidence_band(bet.win_probability or 0.0),
            "result": bet.result,
            "profit": float(bet.profit or 0.0),
            "wager": float(bet.wager or 0.0),
        })

    for entry in entries:
        if entry.get("status") != "Settled" or entry.get("result") not in {"Win", "Loss", "Push"}:
            continue
        props = entry.get("props") or []
        records.append({
            "kind": "entry",
            "sport": _primary_value(props, "sport"),
            "stat": _primary_value(props, "stat"),
            "platform": entry.get("platform") or _primary_value(props, "platform"),
            "direction": "Entry",
            "grade": entry.get("grade") or "Ungraded",
            "confidence_band": _confidence_band(float(entry.get("average_confidence") or 0.0)),
            "result": entry.get("result"),
            "profit": float(entry.get("profit") or 0.0),
            "wager": float(entry.get("wager") or 0.0),
        })
        for prop in props:
            result = prop.get("final_result") or prop.get("result") or ""
            confidence = prop.get("confidence")
            source = str(prop.get("final_source") or "").strip().lower()
            if result not in {"Win", "Loss", "Push"} or source in {"", "unknown", "unmatched", "projection_estimate"}:
                continue
            records.append({
                "kind": "prop",
                "sport": prop.get("sport") or "Unknown",
                "stat": prop.get("stat") or "Unknown",
                "platform": prop.get("platform") or entry.get("platform") or "Unknown",
                "direction": prop.get("direction") or "Unknown",
                "grade": entry.get("grade") or "Ungraded",
                "confidence_band": _confidence_band(float(confidence or 0.0)),
                "result": result,
                "profit": 0.0,
                "wager": 0.0,
            })
    return records


def _primary_value(props: list[dict], key: str) -> str:
    for prop in props:
        value = str(prop.get(key) or "").strip()
        if value:
            return value
    return "Unknown"


def _confidence_band(confidence: float) -> str:
    if confidence <= 0:
        return "Unknown"
    floor = int(confidence // 10) * 10
    floor = max(0, min(90, floor))
    return f"{floor}-{floor + 10}%"


def _segment_rankings(records: list[dict]) -> dict:
    segments: list[dict] = []
    for segment_type, key in (
        ("Sport", "sport"),
        ("Stat", "stat"),
        ("Platform", "platform"),
        ("Direction", "direction"),
        ("Grade", "grade"),
        ("Confidence", "confidence_band"),
    ):
        groups: dict[str, list[dict]] = {}
        for record in records:
            if not _record_applies_to_segment(record, segment_type):
                continue
            if str(record.get(key) or "").strip().lower() in {"", "unknown"}:
                continue
            groups.setdefault(record.get(key) or "Unknown", []).append(record)
        for name, rows in groups.items():
            segments.append(_segment_summary(segment_type, name, rows))

    ranked = sorted(segments, key=lambda row: (row["roi"], row["win_rate"], row["tracked"]), reverse=True)
    works = [
        {**row, "action": _segment_action(row, positive=True)}
        for row in ranked
        if row["tracked"] >= 10
        and row["win_rate"] >= 55
        and (row["basis"] == "leg_outcomes" or row["roi"] > 0)
    ][:6]
    fails = [
        {**row, "action": _segment_action(row, positive=False)}
        for row in sorted(segments, key=lambda row: (row["roi"], row["win_rate"], -row["tracked"]))
        if row["tracked"] >= 6
        and (row["win_rate"] < 45 or (row["basis"] == "bankroll" and row["roi"] < 0))
    ][:6]
    return {"works": works, "fails": fails, "all": segments}


def _record_applies_to_segment(record: dict, segment_type: str) -> bool:
    kind = record.get("kind")
    if segment_type in {"Sport", "Stat", "Direction", "Confidence"}:
        return kind == "prop"
    if segment_type == "Grade":
        return kind == "entry"
    if segment_type == "Platform":
        return kind in {"bet", "entry"}
    return False


def _segment_summary(segment_type: str, name: str, rows: list[dict]) -> dict:
    wins = sum(1 for row in rows if row["result"] == "Win")
    losses = sum(1 for row in rows if row["result"] == "Loss")
    pushes = sum(1 for row in rows if row["result"] == "Push")
    decisions = wins + losses
    wagered = sum(float(row.get("wager") or 0.0) for row in rows)
    profit = sum(float(row.get("profit") or 0.0) for row in rows)
    basis = "leg_outcomes" if rows and rows[0].get("kind") == "prop" else "bankroll"
    return {
        "type": segment_type,
        "name": name,
        "tracked": len(rows),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate": round((wins / decisions * 100) if decisions else 0.0, 1),
        "profit": round(profit, 2),
        "wagered": round(wagered, 2),
        "roi": round((profit / wagered * 100) if wagered else 0.0, 2),
        "basis": basis,
    }


def _segment_action(segment: dict, positive: bool) -> str:
    if positive:
        return f"Prioritize {segment['name']} when confidence and line value agree."
    return f"Route {segment['name']} to paper-only or require stronger confirmation."


def _calibration_rules(calibration_rows: list[dict], segments: list[dict]) -> list[dict]:
    rules: list[dict] = []
    for bucket in calibration_rows:
        bets = int(bucket.get("bets") or 0)
        if bets < 8:
            continue
        error = float(bucket.get("error") or 0.0)
        if abs(error) < 8:
            action = "Hold confidence steady"
        elif error > 0:
            action = f"Boost this bucket by {min(8.0, abs(error) * 0.25):.1f} pts"
        else:
            action = f"Discount this bucket by {min(10.0, abs(error) * 0.3):.1f} pts"
        rules.append({
            "segment": f"Confidence {bucket.get('label')}",
            "action": action,
            "sample_size": bets,
            "reason": f"Actual {bucket.get('actual_pct', 0):.1f}% vs predicted {bucket.get('predicted_mid', 0):.1f}%.",
            "severity": "positive" if error > 8 else "warning" if error < -8 else "neutral",
        })

    for segment in segments:
        if segment["tracked"] < 8:
            continue
        bankroll_is_weak = segment["basis"] == "bankroll" and segment["roi"] < -10
        if bankroll_is_weak or segment["win_rate"] < 42:
            rules.append({
                "segment": f"{segment['type']}: {segment['name']}",
                "action": "Require paper-only or higher confidence",
                "sample_size": segment["tracked"],
                "reason": _segment_rule_reason(segment),
                "severity": "warning",
            })
        elif (
            segment["tracked"] >= 12
            and segment["win_rate"] >= 55
            and (segment["basis"] == "leg_outcomes" or segment["roi"] > 20)
        ):
            rules.append({
                "segment": f"{segment['type']}: {segment['name']}",
                "action": "Allow normal stake sizing",
                "sample_size": segment["tracked"],
                "reason": _segment_rule_reason(segment),
                "severity": "positive",
            })
    return rules[:10]


def _segment_rule_reason(segment: dict) -> str:
    if segment.get("basis") == "leg_outcomes":
        return f"{segment['win_rate']:.1f}% verified leg win rate across {segment['tracked']} results."
    return f"{segment['win_rate']:.1f}% win and {segment['roi']:.1f}% ROI."
