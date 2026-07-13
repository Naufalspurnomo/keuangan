# Production State Persistence

The bot can run with the legacy local JSON + `_BOT_STATE` Google Sheets backup, but Koyeb filesystem is ephemeral. For production, configure the external Postgres state backend so pending confirmations, dedup refs, and bot message references survive restarts.

## Recommended Koyeb Env

```env
STATE_STORE_BACKEND=postgres
STATE_STORE_REQUIRED=1
DURABLE_INBOX_REQUIRED=1
STATE_DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require
STATE_STORE_KEY=default
SPLIT_EVENT_JOIN_SECONDS=2.5
SPLIT_EVENT_PAIR_WINDOW_SECONDS=30
INBOX_RETENTION_DAYS=14
```

`STATE_STORE_REQUIRED=1` makes the bot fail closed if Postgres cannot load or save state. That is safer for financial workflows than silently continuing with empty in-memory state.

`DURABLE_INBOX_REQUIRED=1` makes `/webhook_wuzapi` return HTTP 503 when the
transaction inbox cannot be persisted. WuzAPI can retry the delivery instead
of receiving a false HTTP 200 while the evidence is lost. The same Postgres
database also stores failed Google Sheets writes and coordinates cross-replica
idempotency locks.

Gunicorn must load `gunicorn.conf.py`. Its `post_worker_init` hook starts the
inbox recovery and durable retry workers. Both the included `Procfile` and
`Dockerfile` already use this configuration.

## Fallback Behavior

When `STATE_STORE_BACKEND` is empty or `local`, the bot keeps using:

1. `data/user_state.json`
2. `data/user_state.json.bak`
3. Google Sheets `_BOT_STATE`

Google Sheets backup supports both the old single-cell format and the new chunked format with checksum validation.

## Verification

Run:

```powershell
python -m py_compile main.py ai_helper.py sheets_helper.py handlers\smart_handler.py handlers\pending_handler.py handlers\revision_handler.py handlers\query_handler.py services\state_manager.py services\state_store.py services\project_service.py services\retry_service.py utils\groq_analyzer.py utils\context_detector.py utils\transaction_scope_detector.py layers\context_detector.py layers\addressing_context.py pdf_report.py security.py
python -m unittest tests.state_manager_safety_test tests.sheets_state_persistence_test tests.state_store_test
```
