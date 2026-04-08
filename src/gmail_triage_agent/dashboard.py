from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .db import Database
from .models import DashboardEmail, DashboardOverview


@dataclass(frozen=True)
class DashboardFilters:
    days: int
    limit: int
    category: str | None
    source: str | None
    priority: str | None
    needs_reply: bool | None
    search: str | None


def serve_dashboard(
    *,
    db_path: Path,
    host: str,
    port: int,
    default_days: int,
    default_limit: int,
) -> None:
    database = Database(db_path)
    handler = _build_handler(database, default_days=default_days, default_limit=default_limit)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Dashboard available at http://{host}:{port}")
    server.serve_forever()


def _build_handler(
    database: Database,
    *,
    default_days: int,
    default_limit: int,
) -> type[BaseHTTPRequestHandler]:
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._send_response("ok", content_type="text/plain; charset=utf-8")
                return

            if parsed.path != "/":
                self.send_error(404)
                return

            filters = _parse_filters(parsed.query, default_days=default_days, default_limit=default_limit)
            overview = database.get_dashboard_overview(days=filters.days)
            emails = database.list_recent_emails(
                days=filters.days,
                limit=filters.limit,
                category=filters.category,
                source=filters.source,
                priority=filters.priority,
                needs_reply=filters.needs_reply,
                search=filters.search,
            )
            body = render_dashboard(overview, emails, filters)
            self._send_response(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _send_response(self, body: str, *, content_type: str = "text/html; charset=utf-8") -> None:
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return DashboardHandler


def render_dashboard(
    overview: DashboardOverview,
    emails: list[DashboardEmail],
    filters: DashboardFilters,
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = [
        ("Tracked total", str(overview.total_tracked)),
        (f"Last {filters.days}d", str(overview.total_in_window)),
        ("Needs reply", str(overview.reply_needed_in_window)),
        ("Urgent", str(overview.urgent_in_window)),
        ("High or urgent", str(overview.high_priority_in_window)),
        ("Client", str(overview.client_in_window)),
        ("Jira", str(overview.jira_in_window)),
    ]

    email_rows = "\n".join(_render_email_row(email) for email in emails) or (
        "<tr><td colspan='7' class='empty'>No emails matched the current filters.</td></tr>"
    )
    filter_summary = [
        f"days={filters.days}",
        f"limit={filters.limit}",
        f"category={filters.category or 'all'}",
        f"source={filters.source or 'all'}",
        f"priority={filters.priority or 'all'}",
        f"needs_reply={_needs_reply_label(filters.needs_reply)}",
        f"search={filters.search or 'none'}",
    ]
    last_sync = escape(overview.last_sync_at or "not synced yet")
    last_history_id = escape(overview.last_history_id or "n/a")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Email Triage Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f1e8;
      --panel: #fffaf0;
      --ink: #182230;
      --muted: #617080;
      --accent: #0a6e5a;
      --warm: #dd6b20;
      --line: #d8cdb8;
      --danger: #c53030;
      --chip: #efe4cf;
      --shadow: 0 16px 40px rgba(24, 34, 48, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(221, 107, 32, 0.12), transparent 28%),
        linear-gradient(180deg, #f9f5eb 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    .shell {{ max-width: 1380px; margin: 0 auto; padding: 28px; }}
    .hero {{
      background: linear-gradient(135deg, #18324a, #22556d);
      color: white;
      border-radius: 24px;
      padding: 28px;
      box-shadow: var(--shadow);
      margin-bottom: 22px;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: clamp(2rem, 4vw, 3.4rem);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }}
    .hero p {{ margin: 0; max-width: 760px; color: rgba(255,255,255,0.82); }}
    .meta {{ margin-top: 14px; font-size: 0.92rem; color: rgba(255,255,255,0.72); }}
    .filters, .table-wrap, .insights {{
      background: var(--panel);
      border: 1px solid rgba(24, 34, 48, 0.08);
      border-radius: 20px;
      box-shadow: var(--shadow);
    }}
    .cards {{
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      margin: 20px 0;
    }}
    .card {{
      background: rgba(255, 250, 240, 0.72);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }}
    .card .label {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 8px; }}
    .card .value {{ font-size: 1.8rem; font-weight: 700; letter-spacing: -0.04em; }}
    .layout {{
      display: grid;
      gap: 20px;
      grid-template-columns: 320px minmax(0, 1fr);
      align-items: start;
    }}
    .filters {{ padding: 18px; position: sticky; top: 18px; }}
    .filters h2, .table-wrap h2, .insights h2 {{ margin: 0 0 14px; font-size: 1.1rem; }}
    .filters form {{ display: grid; gap: 12px; }}
    label {{ display: grid; gap: 6px; font-size: 0.9rem; color: var(--muted); }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }}
    .button-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 4px;
    }}
    .button-row button, .button-row a {{
      border: 0;
      border-radius: 999px;
      padding: 10px 14px;
      text-decoration: none;
      font: inherit;
      cursor: pointer;
    }}
    .button-row button {{
      background: var(--accent);
      color: white;
      font-weight: 600;
    }}
    .button-row a {{
      background: var(--chip);
      color: var(--ink);
    }}
    .insights {{
      padding: 18px;
      margin-bottom: 20px;
    }}
    .insights p {{ margin: 8px 0; color: var(--muted); }}
    .chips {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
    .chip {{
      background: var(--chip);
      color: var(--ink);
      border-radius: 999px;
      padding: 7px 10px;
      font-size: 0.84rem;
    }}
    .table-wrap {{ padding: 18px; overflow: hidden; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: 12px 10px;
      border-top: 1px solid rgba(24, 34, 48, 0.08);
      font-size: 0.95rem;
    }}
    th {{
      border-top: 0;
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .priority {{
      display: inline-block;
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      background: #ece4d2;
    }}
    .priority.urgent {{ background: #fed7d7; color: var(--danger); }}
    .priority.high {{ background: #feebc8; color: #975a16; }}
    .priority.normal {{ background: #e6fffa; color: #285e61; }}
    .priority.low {{ background: #edf2f7; color: #4a5568; }}
    .summary {{
      color: var(--ink);
      font-weight: 600;
      margin-bottom: 6px;
    }}
    .muted {{ color: var(--muted); }}
    .empty {{ color: var(--muted); text-align: center; padding: 28px; }}
    @media (max-width: 980px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .filters {{ position: static; }}
      .shell {{ padding: 16px; }}
      .table-wrap {{ overflow-x: auto; }}
      table {{ min-width: 980px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>Email Triage Dashboard</h1>
      <p>Review the inbox as a live queue instead of a buried digest. Prioritize client replies, Jira noise, and urgent operational traffic from one page.</p>
      <div class="meta">Generated {escape(generated_at)} | Last sync checkpoint update: {last_sync} | historyId: {last_history_id}</div>
    </section>

    <section class="cards">
      {''.join(f"<article class='card'><div class='label'>{escape(label)}</div><div class='value'>{escape(value)}</div></article>" for label, value in cards)}
    </section>

    <div class="layout">
      <aside class="filters">
        <h2>Filters</h2>
        <form method="get" action="/">
          <label>Search
            <input type="text" name="search" value="{escape(filters.search or '')}" placeholder="subject, sender, summary">
          </label>
          <label>Window (days)
            <input type="number" name="days" min="1" max="90" value="{filters.days}">
          </label>
          <label>Rows
            <input type="number" name="limit" min="1" max="500" value="{filters.limit}">
          </label>
          <label>Category
            <select name="category">{_build_select(filters.category, ['', 'client_request', 'client_update', 'jira_notification', 'invoice_billing', 'shipment_document', 'internal_coordination', 'spam_or_low_value', 'other'])}</select>
          </label>
          <label>Source
            <select name="source">{_build_select(filters.source, ['', 'client', 'jira', 'system', 'other'])}</select>
          </label>
          <label>Priority
            <select name="priority">{_build_select(filters.priority, ['', 'urgent', 'high', 'normal', 'low'])}</select>
          </label>
          <label>Needs reply
            <select name="needs_reply">{_build_select(_needs_reply_param(filters.needs_reply), ['', 'yes', 'no'])}</select>
          </label>
          <div class="button-row">
            <button type="submit">Apply filters</button>
            <a href="/">Reset</a>
          </div>
        </form>
      </aside>

      <main>
        <section class="insights">
          <h2>Current View</h2>
          <p>This view is optimized for queue review: urgent and high-priority emails rise to the top, then reply-needed items, then the rest by recency.</p>
          <div class="chips">
            {''.join(f"<span class='chip'>{escape(item)}</span>" for item in filter_summary)}
          </div>
        </section>

        <section class="table-wrap">
          <h2>Recent Emails</h2>
          <table>
            <thead>
              <tr>
                <th>Priority</th>
                <th>Received</th>
                <th>From</th>
                <th>Category</th>
                <th>Subject</th>
                <th>Summary</th>
                <th>Next Action</th>
              </tr>
            </thead>
            <tbody>
              {email_rows}
            </tbody>
          </table>
        </section>
      </main>
    </div>
  </div>
</body>
</html>"""


def _render_email_row(email: DashboardEmail) -> str:
    received = email.received_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
    reply_badge = "Reply needed" if email.needs_reply else "No reply"
    return (
        "<tr>"
        f"<td><span class='priority {escape(email.priority)}'>{escape(email.priority)}</span><div class='muted'>{escape(reply_badge)}</div></td>"
        f"<td>{escape(received)}</td>"
        f"<td><div>{escape(email.sender)}</div><div class='muted'>{escape(email.source)}</div></td>"
        f"<td><div>{escape(email.category)}</div><div class='muted'>confidence {email.confidence:.2f}</div></td>"
        f"<td><div class='summary'>{escape(email.subject)}</div><div class='muted'>{escape(email.snippet[:180])}</div></td>"
        f"<td>{escape(email.summary)}</td>"
        f"<td>{escape(email.suggested_action)}</td>"
        "</tr>"
    )


def _parse_filters(query_string: str, *, default_days: int, default_limit: int) -> DashboardFilters:
    params = parse_qs(query_string)
    needs_reply_raw = (params.get("needs_reply", [""])[0] or "").strip().lower()
    needs_reply: bool | None
    if needs_reply_raw == "yes":
        needs_reply = True
    elif needs_reply_raw == "no":
        needs_reply = False
    else:
        needs_reply = None

    return DashboardFilters(
        days=_parse_bounded_int(params.get("days", [str(default_days)])[0], default_days, minimum=1, maximum=90),
        limit=_parse_bounded_int(params.get("limit", [str(default_limit)])[0], default_limit, minimum=1, maximum=500),
        category=_clean_optional(params.get("category", [""])[0]),
        source=_clean_optional(params.get("source", [""])[0]),
        priority=_clean_optional(params.get("priority", [""])[0]),
        needs_reply=needs_reply,
        search=_clean_optional(params.get("search", [""])[0]),
    )


def _parse_bounded_int(raw: str, fallback: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, value))


def _clean_optional(value: str) -> str | None:
    cleaned = value.strip()
    return cleaned or None


def _build_select(selected: str | None, options: list[str]) -> str:
    rendered: list[str] = []
    for option in options:
        label = option or "All"
        is_selected = " selected" if (selected or "") == option else ""
        rendered.append(f"<option value='{escape(option)}'{is_selected}>{escape(label)}</option>")
    return "".join(rendered)


def _needs_reply_param(value: bool | None) -> str | None:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return None


def _needs_reply_label(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "all"
