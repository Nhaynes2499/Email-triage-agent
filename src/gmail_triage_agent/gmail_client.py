from __future__ import annotations

from base64 import urlsafe_b64decode
from datetime import datetime, timezone
from email.utils import getaddresses
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from .config import Settings
from .models import EmailMessage


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailHistoryExpired(Exception):
    pass


class _HTMLStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def get_text(self) -> str:
        return " ".join(part.strip() for part in self.parts if part.strip())


class GmailClient:
    def __init__(self, service: Any):
        self.service = service

    @classmethod
    def from_settings(cls, settings: Settings) -> "GmailClient":
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if settings.gmail_token_file.exists():
            creds = Credentials.from_authorized_user_file(str(settings.gmail_token_file), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(settings.gmail_credentials_file),
                    SCOPES,
                )
                creds = flow.run_local_server(port=0)

            settings.gmail_token_file.write_text(creds.to_json())

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return cls(service)

    def list_recent_message_ids(self, query: str, page_size: int) -> list[str]:
        response = self.service.users().messages().list(
            userId="me",
            q=query,
            maxResults=page_size,
        ).execute()
        return [item["id"] for item in response.get("messages", [])]

    def iter_backfill_message_ids(self, query: str, max_messages: int, page_size: int) -> Iterable[str]:
        seen = 0
        page_token: str | None = None

        while seen < max_messages:
            response = self.service.users().messages().list(
                userId="me",
                q=query,
                maxResults=min(page_size, max_messages - seen),
                pageToken=page_token,
            ).execute()

            for item in response.get("messages", []):
                yield item["id"]
                seen += 1
                if seen >= max_messages:
                    break

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def iter_new_message_ids(self, start_history_id: str, page_size: int) -> tuple[list[str], str | None]:
        from googleapiclient.errors import HttpError

        message_ids: set[str] = set()
        page_token: str | None = None
        latest_history_id: str | None = None

        while True:
            try:
                response = self.service.users().history().list(
                    userId="me",
                    startHistoryId=start_history_id,
                    historyTypes=["messageAdded"],
                    maxResults=min(page_size, 500),
                    pageToken=page_token,
                ).execute()
            except HttpError as exc:
                if getattr(exc, "status_code", None) == 404 or "404" in str(exc):
                    raise GmailHistoryExpired(str(exc)) from exc
                raise

            latest_history_id = response.get("historyId", latest_history_id)
            for event in response.get("history", []):
                latest_history_id = event.get("id", latest_history_id)
                for message_added in event.get("messagesAdded", []):
                    message = message_added.get("message", {})
                    if message.get("id"):
                        message_ids.add(message["id"])

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return sorted(message_ids), latest_history_id

    def get_message(self, gmail_id: str) -> EmailMessage:
        response = self.service.users().messages().get(
            userId="me",
            id=gmail_id,
            format="full",
        ).execute()

        payload = response.get("payload", {})
        headers = {
            item.get("name", ""): item.get("value", "")
            for item in payload.get("headers", [])
        }
        sender = headers.get("From", "")
        recipients = [addr for _, addr in getaddresses([headers.get("To", "")]) if addr]
        cc = [addr for _, addr in getaddresses([headers.get("Cc", "")]) if addr]

        internal_date_ms = int(response.get("internalDate", "0"))
        received_at = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)

        return EmailMessage(
            gmail_id=str(response["id"]),
            thread_id=str(response["threadId"]),
            history_id=str(response.get("historyId")) if response.get("historyId") else None,
            subject=headers.get("Subject", "(no subject)"),
            sender=sender,
            recipients=recipients,
            cc=cc,
            received_at=received_at,
            snippet=str(response.get("snippet", "")),
            body_text=self._extract_body(payload),
            label_ids=[str(label) for label in response.get("labelIds", [])],
            headers=headers,
        )

    def _extract_body(self, payload: dict[str, Any]) -> str:
        text = self._extract_mime(payload, preferred="text/plain")
        if text:
            return text

        html = self._extract_mime(payload, preferred="text/html")
        if not html:
            return ""

        stripper = _HTMLStripper()
        stripper.feed(html)
        return stripper.get_text()

    def _extract_mime(self, payload: dict[str, Any], preferred: str) -> str:
        mime_type = payload.get("mimeType")
        if mime_type == preferred:
            body_data = payload.get("body", {}).get("data")
            if body_data:
                return self._decode_body(body_data)

        for part in payload.get("parts", []):
            text = self._extract_mime(part, preferred)
            if text:
                return text

        return ""

    def _decode_body(self, data: str) -> str:
        padded = data + "=" * (-len(data) % 4)
        return urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
