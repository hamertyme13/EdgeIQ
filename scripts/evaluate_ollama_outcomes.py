"""Evaluate a local Ollama model on settled, pregame-only EdgeIQ forecasts."""

from __future__ import annotations

import argparse
import json

from web.application.copilot_outcome_eval import evaluate_cases, load_settled_cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", type=int, default=12)
    args = parser.parse_args()
    report = evaluate_cases(load_settled_cases(), model=args.model, limit=args.cases)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
