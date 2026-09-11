#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repository.repositories.beta_user_repository import BetaUserRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage EdgeIQ Founding Beta accounts.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, role in (("create-admin", "ADMIN"), ("create-tester", "BETA_TESTER")):
        create = subparsers.add_parser(command)
        create.add_argument("--email", required=True)
        create.add_argument("--username", required=True)
        create.add_argument("--cohort", default="FOUNDING_25")
        create.set_defaults(role=role)
    subparsers.add_parser("list")
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps(BetaUserRepository.list_beta_users(), indent=2))
        return
    password = getpass.getpass("Password (10+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match.")
    user = BetaUserRepository.create(
        args.email,
        args.username,
        password,
        role=args.role,
        beta_cohort=args.cohort,
        is_beta_tester=True,
    )
    print(f"Created {user['role']} account for {user['email']} in {user['beta_cohort']}.")


if __name__ == "__main__":
    main()
