"""Save planner and analyst benchmark evidence without activating any model."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timezone
from pathlib import Path

from services.ollama_qualification import BENCHMARK_VERSION, current_hardware_profile
from web.application.copilot_benchmark import run_preview


def build_report(model: str, *, repetitions: int = 3) -> dict:
    profile = current_hardware_profile()
    roles = {
        role: run_preview(role, model, repetitions=repetitions)
        for role in ("planner", "analyst")
    }
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "model": model,
        "hardware_profile": profile,
        "created_at": datetime.now(UTC).isoformat(),
        "roles": roles,
        "qualified": False,
        "note": "Evidence report only; no role is activated or manually approved.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--output", type=Path, help="Save the JSON evidence report at this path")
    args = parser.parse_args()
    report = build_report(args.model, repetitions=args.repetitions)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"Saved non-promoting benchmark evidence to {args.output.resolve()}")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
