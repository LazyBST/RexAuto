# Moving to Supabase — runbook

Everything below runs **from this Mac** (the OCR for Pensol and the Meko catalogue uses Apple Vision, which does not exist
on Linux servers). The database and the files end up on Supabase; the public search app is a small container that only reads.

## 1. What you create in Supabase (about 5 minutes, in their web app)

1. New project, region **Mumbai (ap-south-1)**. Choose a strong database password and keep it in your password manager.
2. Plan: **Pro** is recommended. A fresh load of the ~10k products here is 36 MB of database and 106 MB of files, but the
   history tables grow with every resync and the free plan stops at 500 MB database / 1 GB files. About 360 MB per 100k products.
3. Collect three things (Project Settings):
   - **Project URL** (`https://<ref>.supabase.co`)
   - **service_role key** (API settings — treat like a password, it bypasses all row-level security)
   - **Database connection string**, *Direct connection* or *Session pooler* (port 5432). Do **not** use the "Transaction
     pooler" (port 6543): the loader holds a lock across a transaction and the pooler breaks that.

You never paste these into a chat or commit them. Put them in a file called `.env` in this folder (it is git-ignored):

```
DATABASE_URL=postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role key>
WHATSAPP_NUMBER=91XXXXXXXXXX
SITE_NAME=<your shop name>
```

## 2. Before loading: decide the two things that are cheap now and costly later

- **Does each brand's MRP include GST?** You do not have to decide now. It is a yes / no / unknown switch on each price list
  (`import_batches.price_includes_gst`), and the site shows "(incl. GST)", "(excl. GST)" or plain "MRP" from it. Fras-le (footer:
  excludes GST) and Pensol (footer: includes all taxes) are set from their footers; the others start as unknown. Flip any of them
  later, no resync, effective immediately:
  `.venv/bin/python -m ingest set-gst --brand uno-minda --includes yes` (or `--batch <id>`, `no`, `unknown`).
  Every change is recorded in the audit log.
- **Make and category names.** `data/config/make_canonical.csv` / `category_canonical.csv` hold the merges applied on every
  load (e.g. Leyland → Ashok Leyland). Add rows there, not in the database.

## 3. Load

```bash
cd ~/Desktop/spareparts
set -a; source .env; set +a
.venv/bin/python -m ingest init-db                                 # migrations 001–005, config tables, brands, storage buckets
.venv/bin/python -m ingest load-all --dir ~/Downloads/original     # 7 sources: upload → redact → parse → apply (≈3 min locally)
.venv/bin/python -m ingest verify                                  # PASS/FAIL list; exit code 1 on any FAIL
```

- Safe to re-run: a source already applied is skipped, so an interrupted load just continues.
- The archived originals in the private `batch-files` bucket are **redacted** before upload (Uno Minda's TD% column and
  Pensol's dealer RATE column are physically removed; the program refuses to archive a file if it cannot prove that).
- Product photos go to the public `product-images` bucket.

## 4. Run the public app

```bash
docker compose up --build        # reads .env, serves on 127.0.0.1:8000
```

Put it behind your host's HTTPS (Render / Fly / Railway). Set `TRUST_PROXY=1` when a proxy sits in front (the rate limit
then uses the real visitor address). The app is read-only; there is no admin login yet (see "Not built yet").

## 5. What was fixed in the schema before this load (all expensive after)

| Gap found in the audit | Now |
|---|---|
| Source columns dropped (class, product type, NPD status, group no., position, pcs/set) | `products.attributes` (closed key list) |
| No effective date of a price list | `products.price_effective_from`, `import_batches.effective_from` |
| Hand edits would be overwritten by a resync | `products.locked_fields`: locked fields are skipped by every resync |
| One image per product | `product_images` (extra photos), `products.image_url` stays the main one |
| Fitments empty, untracked, no year range | new `fitments` table (make, model, variant, year range, engine), tracked and restored like cross references |
| Supersession had no direction | `cross_refs.direction` |
| Make / category spelled differently per brand | canonical maps applied on every load |
| GST basis only guessable per product | switch on the price list; `products.mrp_batch_id` says which list a price came from |
| Unindexed foreign keys, no search index | indexes added; trigram index created automatically where `pg_trgm` exists (Supabase) |
| History could be emptied with TRUNCATE | blocked |
| `cross_refs` readable even for hidden products | public policies check the product is published |
| Trailing spaces in variant labels | trimmed on load and enforced by a constraint |
| Row-by-row writes (hours over a remote link) | set-based writes, one statement per page of products |
| Dealer-rate numbers cached on disk by OCR | removed before caching; the leaked files were deleted |
| Originals archived with TD% / RATE columns | redaction on by default, fail-closed |
| No rate limit, public API docs | per-IP limit, shallow paging, docs off |

## 6. Not built yet (code only — none of it needs a data change later)

Admin login and upload/batch screens (the CLI does this today), Meilisearch (search is Postgres; typos and "waterpump"-style
queries are the known weakness), the `Neo-Catelogue Design-1.pdf` profile (bulb fitment per Neolite code; `attributes` and the
update-only enrichment path are ready for it), a backup routine beyond Supabase's own daily backups, CI.

## 7. Public site on Vercel (Next.js app in `apps/web`)

The Next.js app replaces the FastAPI container for the public site. It reads the same database (search logic is a port of `ingest/pgsearch.py`).

1. Push this repo to GitHub (private). Nothing in git contains data or secrets.
2. Vercel > Add New > Project > import the repo. **Root Directory: `apps/web`**. Framework: Next.js (auto).
3. Environment variables (copy from `apps/web/.env.example`): `DATABASE_URL` (Supabase pooler string), `SITE_NAME`, `WHATSAPP_NUMBER`.
   The Supabase service-role key is **not** needed on Vercel; the site only reads. Keep it on this Mac for the loader.
4. Deploy. Photos load straight from the Supabase public `product-images` bucket (full URLs are stored on each product).
5. Vercel > Firewall: add a rate-limit rule on `/api/*` (the in-app limiter is per server instance only).
6. Local run against any database: `cd apps/web && npm run dev` with the same variables (or `PGHOST/PGDATABASE/PGUSER`).
