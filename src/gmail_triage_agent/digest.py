from __future__ import annotations

from collections import Counter
from datetime import date

from .models import StoredEmail


PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}


class DailyDigestBuilder:
    def build(self, target_date: date, emails: list[StoredEmail]) -> tuple[str, str]:
        subject = f"Daily Inbox Digest - {target_date.isoformat()}"
        if not emails:
            return subject, f"# Daily Inbox Digest\n\nDate: {target_date.isoformat()}\n\nNo emails were classified today."

        category_counts = Counter(email.category for email in emails)
        source_counts = Counter(email.source for email in emails)
        reply_items = [email for email in emails if email.needs_reply]
        reply_items.sort(key=lambda item: (PRIORITY_ORDER.get(item.priority, 99), item.received_at), reverse=False)

        lines = [
            "# Daily Inbox Digest",
            "",
            f"Date: {target_date.isoformat()}",
            "",
            "## Totals",
            f"- Emails processed: {len(emails)}",
            f"- Reply needed: {len(reply_items)}",
            "",
            "## By Category",
        ]

        for category, count in sorted(category_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {category}: {count}")

        lines.extend(["", "## By Source"])
        for source, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- {source}: {count}")

        lines.extend(["", "## Action Queue"])
        if reply_items:
            for email in reply_items[:15]:
                lines.append(
                    f"- [{email.priority}] {email.subject} | {email.sender} | {email.summary} | Next: {email.suggested_action}"
                )
        else:
            lines.append("- No reply-required emails were identified.")

        lines.extend(["", "## Notable Messages"])
        notable = sorted(
            emails,
            key=lambda item: (PRIORITY_ORDER.get(item.priority, 99), item.received_at),
        )[:10]
        for email in notable:
            lines.append(f"- [{email.category}] {email.subject} | {email.summary}")

        return subject, "\n".join(lines)
