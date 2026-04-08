from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .classifier import EmailClassifier
from .config import Settings
from .db import Database
from .digest import DailyDigestBuilder
from .gmail_client import GmailClient, GmailHistoryExpired
from .models import EmailMessage
from .notifications import DigestNotifier


@dataclass(frozen=True)
class SyncResult:
    processed: int
    skipped_existing: int
    latest_history_id: str | None


class TriageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.gmail = GmailClient.from_settings(settings)
        self.classifier = EmailClassifier(settings)
        self.digest_builder = DailyDigestBuilder()
        self.notifier = DigestNotifier(settings)

    def backfill(self, max_messages: int | None = None) -> SyncResult:
        limit = max_messages or self.settings.backfill_max_messages
        processed = 0
        skipped = 0
        latest_history_id: str | None = None

        for gmail_id in self.gmail.iter_backfill_message_ids(
            query=self.settings.gmail_query,
            max_messages=limit,
            page_size=self.settings.sync_page_size,
        ):
            if self.db.has_email(gmail_id):
                skipped += 1
                continue

            message = self.gmail.get_message(gmail_id)
            self._process_message(message)
            processed += 1
            latest_history_id = _max_history_id(latest_history_id, message.history_id)

        if latest_history_id:
            self.db.set_state("last_history_id", latest_history_id)

        return SyncResult(processed=processed, skipped_existing=skipped, latest_history_id=latest_history_id)

    def sync(self) -> SyncResult:
        checkpoint = self.db.get_state("last_history_id")
        if not checkpoint:
            return self._seed_from_recent_messages()

        try:
            message_ids, latest_history_id = self.gmail.iter_new_message_ids(
                start_history_id=checkpoint,
                page_size=self.settings.sync_page_size,
            )
        except GmailHistoryExpired:
            return self._seed_from_recent_messages()

        processed = 0
        skipped = 0
        for gmail_id in message_ids:
            if self.db.has_email(gmail_id):
                skipped += 1
                continue

            message = self.gmail.get_message(gmail_id)
            self._process_message(message)
            processed += 1
            latest_history_id = _max_history_id(latest_history_id, message.history_id)

        if latest_history_id:
            self.db.set_state("last_history_id", latest_history_id)

        return SyncResult(processed=processed, skipped_existing=skipped, latest_history_id=latest_history_id)

    def generate_digest(self, target_date: date) -> tuple[str, str, bool]:
        emails = self.db.list_emails_for_day(target_date)
        subject, body = self.digest_builder.build(target_date, emails)
        self.db.save_digest(target_date, subject, body)
        sent = self.notifier.send(subject, body)
        return subject, body, sent

    def _seed_from_recent_messages(self) -> SyncResult:
        recent_query = f"{self.settings.gmail_query} newer_than:7d"
        processed = 0
        skipped = 0
        latest_history_id: str | None = None

        for gmail_id in self.gmail.list_recent_message_ids(recent_query, self.settings.sync_page_size):
            message = self.gmail.get_message(gmail_id)
            latest_history_id = _max_history_id(latest_history_id, message.history_id)
            if self.db.has_email(gmail_id):
                skipped += 1
                continue

            self._process_message(message)
            processed += 1

        if latest_history_id:
            self.db.set_state("last_history_id", latest_history_id)

        return SyncResult(processed=processed, skipped_existing=skipped, latest_history_id=latest_history_id)

    def _process_message(self, message: EmailMessage) -> None:
        classification = self.classifier.classify(message)
        self.db.upsert_email(message, classification)


def _max_history_id(current: str | None, candidate: str | None) -> str | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return candidate if int(candidate) > int(current) else current
