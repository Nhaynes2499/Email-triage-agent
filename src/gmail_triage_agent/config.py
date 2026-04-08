from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    db_path: Path
    gmail_credentials_file: Path
    gmail_token_file: Path
    gmail_query: str
    backfill_max_messages: int
    sync_page_size: int
    classification_body_char_limit: int
    openai_api_key: str | None
    openai_model: str
    daily_digest_recipient: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_from: str | None
    smtp_use_tls: bool

    @classmethod
    def load(cls) -> "Settings":
        project_root = Path(__file__).resolve().parents[2]
        _load_dotenv(project_root / ".env")

        data_dir = Path(os.getenv("DATA_DIR", project_root / "data"))
        db_path = Path(os.getenv("TRIAGE_DB_PATH", data_dir / "triage.db"))

        return cls(
            project_root=project_root,
            data_dir=data_dir,
            db_path=db_path,
            gmail_credentials_file=Path(os.getenv("GMAIL_CREDENTIALS_FILE", project_root / "credentials.json")),
            gmail_token_file=Path(os.getenv("GMAIL_TOKEN_FILE", project_root / "token.json")),
            gmail_query=os.getenv("GMAIL_QUERY", "in:anywhere -category:promotions"),
            backfill_max_messages=int(os.getenv("BACKFILL_MAX_MESSAGES", "20000")),
            sync_page_size=int(os.getenv("SYNC_PAGE_SIZE", "250")),
            classification_body_char_limit=int(os.getenv("CLASSIFICATION_BODY_CHAR_LIMIT", "5000")),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            daily_digest_recipient=os.getenv("DAILY_DIGEST_RECIPIENT") or None,
            smtp_host=os.getenv("SMTP_HOST") or None,
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME") or None,
            smtp_password=os.getenv("SMTP_PASSWORD") or None,
            smtp_from=os.getenv("SMTP_FROM") or None,
            smtp_use_tls=_parse_bool(os.getenv("SMTP_USE_TLS"), True),
        )
