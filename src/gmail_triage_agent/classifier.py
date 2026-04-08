from __future__ import annotations

from dataclasses import asdict
import json
import re
from typing import Any

from .config import Settings
from .models import ClassificationResult, EmailMessage


ALLOWED_CATEGORIES = {
    "client_request",
    "client_update",
    "jira_notification",
    "invoice_billing",
    "shipment_document",
    "internal_coordination",
    "spam_or_low_value",
    "other",
}

ALLOWED_SOURCES = {"client", "jira", "system", "other"}
ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}


CLASSIFIER_INSTRUCTIONS = """
You are classifying operational email for a freight and client service team.
Return only JSON with these keys:
- category
- source
- priority
- needs_reply
- confidence
- summary
- suggested_action
- reason

Rules:
- Use one category from: client_request, client_update, jira_notification, invoice_billing, shipment_document, internal_coordination, spam_or_low_value, other
- Use one source from: client, jira, system, other
- Use one priority from: low, normal, high, urgent
- Keep summary under 35 words
- Keep suggested_action under 25 words
- confidence must be between 0 and 1
- Prefer operational usefulness over perfect taxonomy
""".strip()


class EmailClassifier:
    def __init__(self, settings: Settings):
        self.settings = settings

    def classify(self, message: EmailMessage) -> ClassificationResult:
        heuristic = heuristic_classify(message)
        if not self.settings.openai_api_key:
            return heuristic

        try:
            return self._classify_with_openai(message, heuristic)
        except Exception:
            return heuristic

    def _classify_with_openai(
        self,
        message: EmailMessage,
        heuristic: ClassificationResult,
    ) -> ClassificationResult:
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        payload = {
            "email": message.prompt_payload(self.settings.classification_body_char_limit),
            "heuristic_guess": asdict(heuristic),
        }

        response = client.responses.create(
            model=self.settings.openai_model,
            input=[
                {"role": "system", "content": CLASSIFIER_INSTRUCTIONS},
                {"role": "user", "content": json.dumps(payload)},
            ],
        )
        raw_text = getattr(response, "output_text", "") or ""
        result = ClassificationResult.from_dict(json.loads(raw_text))
        return sanitize_classification(result, heuristic)


def sanitize_classification(
    result: ClassificationResult,
    fallback: ClassificationResult,
) -> ClassificationResult:
    category = result.category if result.category in ALLOWED_CATEGORIES else fallback.category
    source = result.source if result.source in ALLOWED_SOURCES else fallback.source
    priority = result.priority if result.priority in ALLOWED_PRIORITIES else fallback.priority
    confidence = min(1.0, max(0.0, result.confidence))

    return ClassificationResult(
        category=category,
        source=source,
        priority=priority,
        needs_reply=result.needs_reply,
        confidence=confidence,
        summary=result.summary or fallback.summary,
        suggested_action=result.suggested_action or fallback.suggested_action,
        reason=result.reason or fallback.reason,
    )


def heuristic_classify(message: EmailMessage) -> ClassificationResult:
    sender = message.sender.lower()
    subject = message.subject.lower()
    body = message.body_text.lower()
    combined = " ".join(part for part in [subject, body, message.snippet.lower()] if part)

    if _looks_like_jira(sender, subject):
        return ClassificationResult(
            category="jira_notification",
            source="jira",
            priority="normal",
            needs_reply=False,
            confidence=0.82,
            summary=_truncate(message.subject or "Jira notification"),
            suggested_action="Review the linked issue and note any required follow-up.",
            reason="Sender or subject matched Jira/Atlassian patterns.",
        )

    if _contains_any(combined, ["invoice", "payment", "billing", "remittance", "overdue"]):
        return ClassificationResult(
            category="invoice_billing",
            source="client" if "@" in sender else "other",
            priority="high" if _contains_any(combined, ["overdue", "urgent", "asap"]) else "normal",
            needs_reply=_contains_any(combined, ["please", "confirm", "approve", "pay"]),
            confidence=0.74,
            summary=_truncate(message.subject or "Billing-related email"),
            suggested_action="Route to accounts or confirm billing status.",
            reason="Invoice or payment language detected.",
        )

    if _contains_any(combined, ["attached", "bill of lading", "packing list", "awb", "bol", "documents attached"]):
        return ClassificationResult(
            category="shipment_document",
            source="client" if "@" in sender else "other",
            priority="high",
            needs_reply=False,
            confidence=0.77,
            summary=_truncate(message.subject or "Shipment document email"),
            suggested_action="Check attachments and link documents to the active shipment.",
            reason="Document or shipping paperwork language detected.",
        )

    if _contains_any(combined, ["please", "can you", "could you", "need", "request", "?"]):
        return ClassificationResult(
            category="client_request",
            source="client" if "@" in sender else "other",
            priority="high" if _contains_any(combined, ["urgent", "asap", "today", "immediately"]) else "normal",
            needs_reply=True,
            confidence=0.7,
            summary=_truncate(message.subject or "Client request"),
            suggested_action="Reply or assign an owner for the request.",
            reason="Request-style language detected.",
        )

    if _contains_any(combined, ["update", "status", "eta", "arrived", "cleared", "delivered"]):
        return ClassificationResult(
            category="client_update",
            source="client" if "@" in sender else "other",
            priority="normal",
            needs_reply=False,
            confidence=0.66,
            summary=_truncate(message.subject or "Client update"),
            suggested_action="Record the update and notify the responsible teammate if needed.",
            reason="Status or update language detected.",
        )

    if _contains_any(sender + " " + subject, ["no-reply", "noreply", "newsletter", "marketing"]) or "category_promotions" in {
        label.lower() for label in message.label_ids
    }:
        return ClassificationResult(
            category="spam_or_low_value",
            source="system",
            priority="low",
            needs_reply=False,
            confidence=0.71,
            summary=_truncate(message.subject or "Low-value email"),
            suggested_action="Archive unless a business workflow depends on it.",
            reason="Promotional or automated pattern detected.",
        )

    return ClassificationResult(
        category="other",
        source="client" if "@" in sender else "other",
        priority="normal",
        needs_reply=False,
        confidence=0.5,
        summary=_truncate(message.subject or "Unclassified email"),
        suggested_action="Review manually if it affects active work.",
        reason="No stronger pattern matched.",
    )


def _contains_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


def _looks_like_jira(sender: str, subject: str) -> bool:
    return bool(
        "atlassian" in sender
        or "jira" in sender
        or re.search(r"\b[a-z]+-\d+\b", subject)
        or "[jira]" in subject
    )


def _truncate(text: str, length: int = 120) -> str:
    if len(text) <= length:
        return text
    return text[: length - 3].rstrip() + "..."
