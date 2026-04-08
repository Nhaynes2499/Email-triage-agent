from __future__ import annotations

from email.message import EmailMessage
import smtplib

from .config import Settings


class DigestNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, subject: str, body: str) -> bool:
        if not (
            self.settings.daily_digest_recipient
            and self.settings.smtp_host
            and self.settings.smtp_from
        ):
            return False

        message = EmailMessage()
        message["From"] = self.settings.smtp_from
        message["To"] = self.settings.daily_digest_recipient
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as client:
            if self.settings.smtp_use_tls:
                client.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                client.login(self.settings.smtp_username, self.settings.smtp_password)
            client.send_message(message)

        return True
