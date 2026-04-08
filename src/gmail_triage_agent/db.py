from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .models import (
    ClassificationResult,
    DashboardEmail,
    DashboardOverview,
    EmailMessage,
    StoredEmail,
)


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS emails (
                  gmail_id TEXT PRIMARY KEY,
                  thread_id TEXT NOT NULL,
                  history_id TEXT,
                  subject TEXT NOT NULL,
                  sender TEXT NOT NULL,
                  recipients_json TEXT NOT NULL,
                  cc_json TEXT NOT NULL,
                  received_at TEXT NOT NULL,
                  snippet TEXT NOT NULL,
                  body_text TEXT NOT NULL,
                  label_ids_json TEXT NOT NULL,
                  headers_json TEXT NOT NULL,
                  category TEXT NOT NULL,
                  source TEXT NOT NULL,
                  priority TEXT NOT NULL,
                  needs_reply INTEGER NOT NULL,
                  confidence REAL NOT NULL,
                  summary TEXT NOT NULL,
                  suggested_action TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  ingested_at TEXT NOT NULL,
                  classified_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sync_state (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_digests (
                  digest_date TEXT PRIMARY KEY,
                  subject TEXT NOT NULL,
                  body TEXT NOT NULL,
                  generated_at TEXT NOT NULL
                );
                """
            )

    def has_email(self, gmail_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM emails WHERE gmail_id = ?",
                (gmail_id,),
            ).fetchone()
            return row is not None

    def upsert_email(self, message: EmailMessage, classification: ClassificationResult) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO emails (
                  gmail_id, thread_id, history_id, subject, sender, recipients_json, cc_json,
                  received_at, snippet, body_text, label_ids_json, headers_json, category,
                  source, priority, needs_reply, confidence, summary, suggested_action, reason,
                  ingested_at, classified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gmail_id) DO UPDATE SET
                  thread_id = excluded.thread_id,
                  history_id = excluded.history_id,
                  subject = excluded.subject,
                  sender = excluded.sender,
                  recipients_json = excluded.recipients_json,
                  cc_json = excluded.cc_json,
                  received_at = excluded.received_at,
                  snippet = excluded.snippet,
                  body_text = excluded.body_text,
                  label_ids_json = excluded.label_ids_json,
                  headers_json = excluded.headers_json,
                  category = excluded.category,
                  source = excluded.source,
                  priority = excluded.priority,
                  needs_reply = excluded.needs_reply,
                  confidence = excluded.confidence,
                  summary = excluded.summary,
                  suggested_action = excluded.suggested_action,
                  reason = excluded.reason,
                  ingested_at = excluded.ingested_at,
                  classified_at = excluded.classified_at
                """,
                (
                    message.gmail_id,
                    message.thread_id,
                    message.history_id,
                    message.subject,
                    message.sender,
                    json.dumps(message.recipients),
                    json.dumps(message.cc),
                    message.received_at.isoformat(),
                    message.snippet,
                    message.body_text,
                    json.dumps(message.label_ids),
                    json.dumps(message.headers),
                    classification.category,
                    classification.source,
                    classification.priority,
                    int(classification.needs_reply),
                    classification.confidence,
                    classification.summary,
                    classification.suggested_action,
                    classification.reason,
                    timestamp,
                    timestamp,
                ),
            )

    def set_state(self, key: str, value: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sync_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value = excluded.value,
                  updated_at = excluded.updated_at
                """,
                (key, value, timestamp),
            )

    def get_state(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM sync_state WHERE key = ?",
                (key,),
            ).fetchone()
            return None if row is None else str(row["value"])

    def list_emails_for_day(self, target_date: date) -> list[StoredEmail]:
        prefix = target_date.isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT gmail_id, subject, sender, received_at, category, source,
                       priority, needs_reply, summary, suggested_action
                FROM emails
                WHERE substr(classified_at, 1, 10) = ?
                ORDER BY priority DESC, received_at DESC
                """,
                (prefix,),
            ).fetchall()

        return [
            StoredEmail(
                gmail_id=str(row["gmail_id"]),
                subject=str(row["subject"]),
                sender=str(row["sender"]),
                received_at=datetime.fromisoformat(str(row["received_at"])),
                category=str(row["category"]),
                source=str(row["source"]),
                priority=str(row["priority"]),
                needs_reply=bool(row["needs_reply"]),
                summary=str(row["summary"]),
                suggested_action=str(row["suggested_action"]),
            )
            for row in rows
        ]

    def save_digest(self, target_date: date, subject: str, body: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_digests (digest_date, subject, body, generated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(digest_date) DO UPDATE SET
                  subject = excluded.subject,
                  body = excluded.body,
                  generated_at = excluded.generated_at
                """,
                (target_date.isoformat(), subject, body, timestamp),
            )

    def get_dashboard_overview(self, days: int = 7) -> DashboardOverview:
        since = (datetime.now(timezone.utc) - timedelta(days=max(days, 1))).isoformat()
        with self._connect() as connection:
            total_tracked = int(connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0])
            window_counts = connection.execute(
                """
                SELECT
                  COUNT(*) AS total_in_window,
                  SUM(CASE WHEN needs_reply = 1 THEN 1 ELSE 0 END) AS reply_needed_in_window,
                  SUM(CASE WHEN priority = 'urgent' THEN 1 ELSE 0 END) AS urgent_in_window,
                  SUM(CASE WHEN priority IN ('urgent', 'high') THEN 1 ELSE 0 END) AS high_priority_in_window,
                  SUM(CASE WHEN source = 'client' THEN 1 ELSE 0 END) AS client_in_window,
                  SUM(CASE WHEN source = 'jira' THEN 1 ELSE 0 END) AS jira_in_window
                FROM emails
                WHERE received_at >= ?
                """,
                (since,),
            ).fetchone()
            last_sync = connection.execute(
                "SELECT value, updated_at FROM sync_state WHERE key = 'last_history_id'"
            ).fetchone()

        return DashboardOverview(
            total_tracked=total_tracked,
            total_in_window=int(window_counts["total_in_window"] or 0),
            reply_needed_in_window=int(window_counts["reply_needed_in_window"] or 0),
            urgent_in_window=int(window_counts["urgent_in_window"] or 0),
            high_priority_in_window=int(window_counts["high_priority_in_window"] or 0),
            client_in_window=int(window_counts["client_in_window"] or 0),
            jira_in_window=int(window_counts["jira_in_window"] or 0),
            last_sync_at=None if last_sync is None else str(last_sync["updated_at"]),
            last_history_id=None if last_sync is None else str(last_sync["value"]),
        )

    def list_recent_emails(
        self,
        *,
        days: int = 7,
        limit: int = 100,
        category: str | None = None,
        source: str | None = None,
        priority: str | None = None,
        needs_reply: bool | None = None,
        search: str | None = None,
    ) -> list[DashboardEmail]:
        since = (datetime.now(timezone.utc) - timedelta(days=max(days, 1))).isoformat()
        clauses = ["received_at >= ?"]
        params: list[object] = [since]

        if category:
            clauses.append("category = ?")
            params.append(category)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if needs_reply is not None:
            clauses.append("needs_reply = ?")
            params.append(1 if needs_reply else 0)
        if search:
            clauses.append("(subject LIKE ? OR sender LIKE ? OR summary LIKE ? OR snippet LIKE ?)")
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term, search_term])

        params.append(max(1, min(limit, 500)))
        query = f"""
            SELECT gmail_id, subject, sender, received_at, category, source, priority,
                   needs_reply, summary, suggested_action, snippet, confidence
            FROM emails
            WHERE {' AND '.join(clauses)}
            ORDER BY
              CASE priority
                WHEN 'urgent' THEN 0
                WHEN 'high' THEN 1
                WHEN 'normal' THEN 2
                ELSE 3
              END,
              needs_reply DESC,
              received_at DESC
            LIMIT ?
        """

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [
            DashboardEmail(
                gmail_id=str(row["gmail_id"]),
                subject=str(row["subject"]),
                sender=str(row["sender"]),
                received_at=datetime.fromisoformat(str(row["received_at"])),
                category=str(row["category"]),
                source=str(row["source"]),
                priority=str(row["priority"]),
                needs_reply=bool(row["needs_reply"]),
                summary=str(row["summary"]),
                suggested_action=str(row["suggested_action"]),
                snippet=str(row["snippet"]),
                confidence=float(row["confidence"]),
            )
            for row in rows
        ]
