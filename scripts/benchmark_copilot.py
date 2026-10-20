"""Run the non-promoting Ask EdgeIQ model benchmark preview locally."""

from __future__ import annotations

import argparse
import json

from web.application.copilot_benchmark import run_preview


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("planner", "analyst"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--repetitions", type=int, default=3, choices=range(1, 6))
    args = parser.parse_args()
    print(json.dumps(run_preview(args.role, args.model, repetitions=args.repetitions), indent=2))


if __name__ == "__main__":
    main()
