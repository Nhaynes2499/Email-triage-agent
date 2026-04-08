from __future__ import annotations

import argparse
from datetime import date

from .config import Settings
from .service import TriageService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gmail triage agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("auth", help="Run Gmail OAuth bootstrap and save a refreshable token")

    backfill = subparsers.add_parser("backfill", help="Backfill historic messages")
    backfill.add_argument("--max-messages", type=int, default=None)

    subparsers.add_parser("sync", help="Sync new messages since the last checkpoint")

    digest = subparsers.add_parser("digest", help="Build the digest for a given day")
    digest.add_argument("--date", dest="target_date", default=date.today().isoformat())

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings.load()

    if args.command == "auth":
        from .gmail_client import GmailClient

        GmailClient.from_settings(settings)
        print(f"OAuth token saved to {settings.gmail_token_file}")
        return

    service = TriageService(settings)

    if args.command == "backfill":
        result = service.backfill(max_messages=args.max_messages)
        print(
            f"Backfill complete. processed={result.processed} "
            f"skipped_existing={result.skipped_existing} "
            f"latest_history_id={result.latest_history_id}"
        )
        return

    if args.command == "sync":
        result = service.sync()
        print(
            f"Sync complete. processed={result.processed} "
            f"skipped_existing={result.skipped_existing} "
            f"latest_history_id={result.latest_history_id}"
        )
        return

    if args.command == "digest":
        target = date.fromisoformat(args.target_date)
        subject, body, sent = service.generate_digest(target)
        print(subject)
        print()
        print(body)
        print()
        print(f"sent={sent}")
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
