from datetime import date, datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gmail_triage_agent.digest import DailyDigestBuilder
from gmail_triage_agent.models import StoredEmail


class DailyDigestTests(unittest.TestCase):
    def test_digest_contains_totals_and_action_queue(self) -> None:
        builder = DailyDigestBuilder()
        target_date = date(2026, 4, 8)
        emails = [
            StoredEmail(
                gmail_id="1",
                subject="Need approval for invoice",
                sender="client@example.com",
                received_at=datetime.now(timezone.utc),
                category="invoice_billing",
                source="client",
                priority="high",
                needs_reply=True,
                summary="Client is waiting for invoice approval.",
                suggested_action="Review invoice and respond today.",
            ),
            StoredEmail(
                gmail_id="2",
                subject="SHIP-55 updated",
                sender="jira@example.com",
                received_at=datetime.now(timezone.utc),
                category="jira_notification",
                source="jira",
                priority="normal",
                needs_reply=False,
                summary="Jira status changed to Cleared.",
                suggested_action="No action required.",
            ),
        ]

        subject, body = builder.build(target_date, emails)

        self.assertIn("2026-04-08", subject)
        self.assertIn("Emails processed: 2", body)
        self.assertIn("Reply needed: 1", body)
        self.assertIn("Need approval for invoice", body)


if __name__ == "__main__":
    unittest.main()
