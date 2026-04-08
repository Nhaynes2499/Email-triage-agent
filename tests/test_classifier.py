from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gmail_triage_agent.classifier import heuristic_classify
from gmail_triage_agent.models import EmailMessage


class HeuristicClassifierTests(unittest.TestCase):
    def test_jira_email_is_classified_as_jira_notification(self) -> None:
        email = EmailMessage(
            gmail_id="1",
            thread_id="t1",
            history_id="10",
            subject="[Jira] SHIP-102 updated by Alex",
            sender="jira@rdleagletrade.atlassian.net",
            recipients=["ops@example.com"],
            cc=[],
            received_at=datetime.now(timezone.utc),
            snippet="Jira issue updated",
            body_text="The issue status changed to In Progress.",
            label_ids=["INBOX"],
            headers={},
        )

        result = heuristic_classify(email)
        self.assertEqual(result.category, "jira_notification")
        self.assertEqual(result.source, "jira")
        self.assertFalse(result.needs_reply)

    def test_client_request_detects_reply_needed(self) -> None:
        email = EmailMessage(
            gmail_id="2",
            thread_id="t2",
            history_id="11",
            subject="Need update on customs clearance",
            sender="client@example.com",
            recipients=["ops@example.com"],
            cc=[],
            received_at=datetime.now(timezone.utc),
            snippet="Can you confirm if this is cleared today?",
            body_text="Please confirm whether the shipment is cleared today. Thanks.",
            label_ids=["INBOX"],
            headers={},
        )

        result = heuristic_classify(email)
        self.assertEqual(result.category, "client_request")
        self.assertTrue(result.needs_reply)


if __name__ == "__main__":
    unittest.main()
