# Spare parts catalogue

See `PROJECT_PLAN.md` (v2). Status: **Milestone 1, Day 1 in progress** — batch engine + Uno Minda profile done.

## Dev setup (no Docker needed)
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m ingest init-db            # local Postgres 16 (pgserver) in data/pgdata, migrations, config CSVs
.venv/bin/python -m ingest upload --brand uno-minda --profile uno_minda --file path.pdf
.venv/bin/python -m ingest parse|report|preview|apply --batch <id>
.venv/bin/python -m ingest resync --batch <id> [--remove-missing] [--apply]
.venv/bin/python -m ingest delete-preview|delete --batch <id> [--confirm <filename>] [--force-conflicts] [--purge-file]
.venv/bin/python -m pytest tests
```
Production: set `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `MEILI_URL`, `MEILI_MASTER_KEY`, `INGEST_SHARED_SECRET`
(see `.env.example`); run `docker compose up` for Meilisearch + the FastAPI service (`uvicorn ingest.api:app`).

## Never stored
No discount / dealer rate / trade cut / margin column exists. Profiles emit only `PRODUCT_FIELDS`
(`ingest/profiles/base.py`); the Uno Minda profile drops the TD% column's characters before any text lookup.
`tests/test_never_stored.py` enforces this on the schema, staging, change log, audit log, CSV and search documents.
