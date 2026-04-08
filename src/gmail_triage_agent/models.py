from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class EmailMessage:
    gmail_id: str
    thread_id: str
    history_id: str | None
    subject: str
    sender: str
    recipients: list[str]
    cc: list[str]
    received_at: datetime
    snippet: str
    body_text: str
    label_ids: list[str]
    headers: dict[str, str]

    def prompt_payload(self, body_char_limit: int) -> dict[str, Any]:
        payload = asdict(self)
        payload["received_at"] = self.received_at.isoformat()
        payload["body_text"] = self.body_text[:body_char_limit]
        return payload


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    source: str
    priority: str
    needs_reply: bool
    confidence: float
    summary: str
    suggested_action: str
    reason: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClassificationResult":
        return cls(
            category=str(payload.get("category", "other")),
            source=str(payload.get("source", "other")),
            priority=str(payload.get("priority", "normal")),
            needs_reply=bool(payload.get("needs_reply", False)),
            confidence=float(payload.get("confidence", 0.5)),
            summary=str(payload.get("summary", "")).strip(),
            suggested_action=str(payload.get("suggested_action", "")).strip(),
            reason=str(payload.get("reason", "")).strip(),
        )


@dataclass(frozen=True)
class StoredEmail:
    gmail_id: str
    subject: str
    sender: str
    received_at: datetime
    category: str
    source: str
    priority: str
    needs_reply: bool
    summary: str
    suggested_action: str

