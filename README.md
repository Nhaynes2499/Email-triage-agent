# gmail-triage-agent

Standalone agent for a Gmail inbox that:

- backfills and classifies historic mail
- incrementally reads new mail every day
- builds a daily digest of everything processed

This repo is designed for a mailbox with a large backlog, like 20,000 mixed client and Jira emails.

## What It Does

The agent stores email metadata and AI classifications in SQLite, so it can:

- avoid reprocessing the same message twice
- resume from the last Gmail `historyId`
- group emails into useful operational categories
- produce a daily summary with action items

## Categories

Out of the box, the classifier uses these categories:

- `client_request`
- `client_update`
- `jira_notification`
- `invoice_billing`
- `shipment_document`
- `internal_coordination`
- `spam_or_low_value`
- `other`

Each email also gets:

- `source` (`client`, `jira`, `system`, or `other`)
- `priority` (`low`, `normal`, `high`, or `urgent`)
- `needs_reply`
- `summary`
- `suggested_action`

## Architecture

```text
Gmail API
  -> backfill / sync worker
  -> message parser
  -> AI classifier
  -> SQLite state store
  -> daily digest builder
  -> optional SMTP digest sender
```

## Why Polling First

This starter uses Gmail incremental sync via `history.list` for the day-to-day worker, which keeps deployment simple and works well for scheduled jobs. If you want real push later, Gmail also supports mailbox `watch` with Cloud Pub/Sub, but that adds Google Cloud plumbing and watch renewal.

## Quick Start

1. Create a virtualenv and install the package.
2. Copy `.env.example` to `.env`.
3. Add your Gmail OAuth desktop credentials to `credentials.json`.
4. Run an initial auth/bootstrap:

```bash
python -m gmail_triage_agent.cli auth
```

5. Backfill the mailbox:

```bash
python -m gmail_triage_agent.cli backfill
```

6. Sync only new messages:

```bash
python -m gmail_triage_agent.cli sync
```

7. Generate today’s digest:

```bash
python -m gmail_triage_agent.cli digest --date 2026-04-08
```

## Environment

Copy `.env.example` and set:

- `GMAIL_CREDENTIALS_FILE`: Google OAuth client credentials JSON
- `GMAIL_TOKEN_FILE`: saved OAuth token
- `GMAIL_QUERY`: filter for the mailbox scope
- `OPENAI_API_KEY`: API key for classification
- `OPENAI_MODEL`: defaults to `gpt-5-mini`
- `BACKFILL_MAX_MESSAGES`: safety cap for initial ingestion
- `SYNC_PAGE_SIZE`: Gmail page size for sync runs
- `DAILY_DIGEST_RECIPIENT`: optional address that receives the digest
- `SMTP_*`: optional SMTP config for sending the digest

## Suggested Deployment

For a practical first deployment:

- run `backfill` once
- run `sync` every 5-15 minutes with cron or a scheduler
- run `digest` once near the end of the work day

Example cron:

```cron
*/10 * * * * cd /path/to/gmail-triage-agent && . .venv/bin/activate && python -m gmail_triage_agent.cli sync
0 17 * * 1-5 cd /path/to/gmail-triage-agent && . .venv/bin/activate && python -m gmail_triage_agent.cli digest
```

## Data Model

The local SQLite database stores:

- Gmail message id and thread id
- sender, recipients, subject, snippet, body excerpt
- classification output
- sync checkpoint state like `last_history_id`
- generated digests

The database lives at `data/triage.db` by default.

## Notes

- The repo defaults to Gmail read-only access.
- If the saved Gmail `historyId` expires, the worker falls back to a recent sync window and re-establishes the checkpoint.
- The classifier includes a rule-based fallback so the pipeline still works if the AI call fails.
