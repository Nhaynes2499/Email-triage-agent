from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .models import ClassificationResult, EmailMessage, StoredEmail


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
