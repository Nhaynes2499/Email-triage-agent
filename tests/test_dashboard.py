from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gmail_triage_agent.dashboard import DashboardFilters, render_dashboard
from gmail_triage_agent.db import Database
from gmail_triage_agent.models import ClassificationResult, DashboardOverview, EmailMessage


class DashboardDataTests(unittest.TestCase):
    def test_recent_email_filters_and_overview(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            db = Database(Path(tmp_dir) / "triage.db")
            now = datetime.now(timezone.utc)

            db.upsert_email(
                EmailMessage(
                    gmail_id="1",
                    thread_id="t1",
                    history_id="101",
                    subject="Urgent customs issue",
                    sender="client@example.com",
                    recipients=["ops@example.com"],
                    cc=[],
                    received_at=now,
                    snippet="Need help today",
                    body_text="Please respond urgently.",
                    label_ids=["INBOX"],
                    headers={},
                ),
                ClassificationResult(
                    category="client_request",
                    source="client",
                    priority="urgent",
                    needs_reply=True,
                    confidence=0.9,
                    summary="Client needs urgent customs help.",
                    suggested_action="Reply immediately and assign an owner.",
                    reason="Test fixture",
                ),
            )

            db.upsert_email(
                EmailMessage(
                    gmail_id="2",
                    thread_id="t2",
                    history_id="102",
                    subject="Jira update",
                    sender="jira@example.com",
                    recipients=["ops@example.com"],
                    cc=[],
                    received_at=now - timedelta(days=1),
                    snippet="Issue moved to done",
                    body_text="No action required.",
                    label_ids=["INBOX"],
                    headers={},
                ),
                ClassificationResult(
                    category="jira_notification",
                    source="jira",
                    priority="normal",
                    needs_reply=False,
                    confidence=0.8,
                    summary="Jira issue changed state.",
                    suggested_action="Review if this affects active work.",
                    reason="Test fixture",
                ),
            )
            db.set_state("last_history_id", "102")

            overview = db.get_dashboard_overview(days=7)
            emails = db.list_recent_emails(days=7, limit=50, needs_reply=True)

            self.assertEqual(overview.total_tracked, 2)
            self.assertEqual(overview.reply_needed_in_window, 1)
            self.assertEqual(overview.client_in_window, 1)
            self.assertEqual(overview.jira_in_window, 1)
            self.assertEqual(len(emails), 1)
            self.assertEqual(emails[0].gmail_id, "1")


class DashboardRenderTests(unittest.TestCase):
    def test_render_dashboard_shows_cards_and_subject(self) -> None:
        html = render_dashboard(
            DashboardOverview(
                total_tracked=12,
                total_in_window=5,
                reply_needed_in_window=2,
                urgent_in_window=1,
                high_priority_in_window=3,
                client_in_window=4,
                jira_in_window=1,
                last_sync_at="2026-04-08T12:00:00+00:00",
                last_history_id="500",
            ),
            [],
            DashboardFilters(
                days=7,
                limit=100,
                category=None,
                source=None,
                priority=None,
                needs_reply=None,
                search=None,
            ),
        )

        self.assertIn("Email Triage Dashboard", html)
        self.assertIn("Tracked total", html)
        self.assertIn("No emails matched the current filters.", html)


if __name__ == "__main__":
    unittest.main()
