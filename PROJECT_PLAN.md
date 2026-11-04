# Spare Parts Catalogue — Project Plan (v2)

Hand-off document for Claude Code. Read fully before writing code. Owner is a solo maintainer, so **simple, boring, low-maintenance choices win** over clever ones.

**Changes from v1:** (1) counter staff are also users; (2) discounts/dealer rates/trade cuts are **never stored anywhere**, only MRP, and there is no private table; (3) English only, no i18n; (4) no OCR, PDF libraries only, with pages that would need OCR flagged; (5) every import is a tracked **batch** tied to its saved source file, with an audit trail, sync timeline, and admin UI to delete a whole batch or resync it.

---

## 1. Goal

A fast, searchable catalogue of commercial-vehicle (~90%) and passenger-vehicle (~10%) spare parts, aggregating many manufacturers' catalogues and price lists in one place. Built for a distribution business in India. Later it evolves into an ordering/marketplace app.

**Users:** retailers, mechanics, workshop owners, and the business's own counter staff. All use the same app. Because no discount or margin data is stored, there is no "internal-only" view of the catalogue. Only the admin area (uploads, batches, audit) needs login.

**Scale:** 15–20 PDFs of ~100 pages each at first (roughly 20k–40k rows), growing toward 100k+ products.

**v1 deadline:** 2–3 days for a working, deployed, clean (not fancy) web app. Android/iOS wrapper comes after.

---

## 2. Decisions already made by the owner

- Show and store **MRP only**. No distributor rate, trade discount, dealer rate, margin or any "cut", in any table, staging row, log, CSV or search document.
- Stock: show "Ask us for availability" (most items are in stock or available within ~7 days). No inventory integration in v1.
- Supplier catalogue images and data may be republished. Use supplier images where available; no own photography for now.
- Cross-references aren't written anywhere. **OEM number is the initial link** between brands. Staff knowledge fills the rest later via an internal page (phase 2).
- Search by part number AND by vehicle + part type ("Tata 1612 water pump"). Vehicle browsing is required.
- **English only.** No Hindi/Hinglish, no i18n framework.
- **No OCR for now.** Use PDF libraries only. Anything that would need OCR is flagged and handled later.
- Every import is tagged with its source file; the file is saved with name, date and time; there is an audit trail; a batch can be deleted entirely or resynced from the admin UI.
- v1: web only, no offline, no barcode scanning. Barcode scanning and mobile wrappers are phase 2.
- Solo maintainer.

---

## 3. Stack (defaults; change only with a reason)

| Layer | Choice | Why |
|---|---|---|
| Web app | Next.js (App Router) + TypeScript + Tailwind | SSR gives Google-indexable product pages; one codebase for the later PWA/Capacitor wrap |
| Database + auth + files | Supabase (Postgres, Auth, **private** Storage bucket), Mumbai region | Source of truth; free tier is enough to start |
| Search | Meilisearch | Typo tolerant, very fast at 100k docs, simple ops. Rebuilt from Postgres, never the source of truth |
| Ingest service | Python 3.11 + FastAPI, with pdfplumber and PyMuPDF (no OCR) | Best PDF tooling. Exposes parse / apply / resync / rollback to the admin UI and also works as a CLI |
| Hosting | Vercel (web) · Supabase · one small VPS or container host (Render/Fly) running the ingest service + Meilisearch via Docker Compose | The ingest service is long-running Python, so it can't live on Vercel |
| Admin auth | Supabase Auth (email magic link) + allow-list of emails | Simple; actor is recorded in every audit event |
| Later | Capacitor wrap for Android/iOS | Avoids a second UI codebase |

Keep the search layer behind a small interface (`searchProducts(query, filters)`) so it can be swapped.

---

## 4. Data model (Postgres)

```sql
brands(id, name, slug, logo_url, owned boolean)

products(
  id uuid pk,
  brand_id fk,
  part_no text,                 -- as printed
  part_no_norm text,            -- UPPER, strip everything except A-Z0-9
  description text,
  category text,                -- normalised (Brake Valves, Water Pumps, Head Lamps...)
  segment text,                 -- HCV | LCV | CAR | TRACTOR | OTHER
  oem_name text,                -- normalised make (Tata, Ashok Leyland, Mahindra...)
  oem_raw text,                 -- as printed (TTA., ASLY, MHRD...)
  application text,             -- as printed, "where it is used"
  variant_label text,           -- e.g. STD / OS-1 / OS-2 (brake linings), pack size (oils)
  mrp numeric,
  mrp_prev numeric,             -- previous MRP when the source prints both
  price_basis text,             -- 'incl_tax' | 'ex_tax' | 'unknown' (confirm per brand)
  gst_pct numeric, hsn text, moq int, pack_qty int, unit text,
  image_url text,               -- nullable
  stock_status text default 'ask',
  status text default 'published',   -- published | hidden
  needs_review boolean default false, review_note text,
  first_batch_id fk, last_batch_id fk,       -- which import created / last wrote this row
  source_page int, source_row int,           -- position inside the batch's file
  created_at, updated_at,
  unique (brand_id, part_no_norm, variant_label)
)

vehicles(id, make, model, engine, notes)       -- v1 may only fill make
fitments(product_id fk, vehicle_id fk, note)
cross_refs(id, product_id fk, ref_type, ref_brand, ref_part_no, ref_part_no_norm, note)
  -- ref_type: oem | competitor | supersession. Meko "REF. NOS." go here as 'oem'.

make_aliases(raw text pk, make text)           -- TTA./TML -> Tata, ASLY/AL -> Ashok Leyland... owner-reviewable CSV
abbreviations(abbr text, expansion text)       -- H.L. -> head lamp ... used by search
```

### What is never stored (hard rule)

Trade discount (e.g. Uno Minda `TD% W/O GST`), dealer/distributor rate (e.g. Pensol `RATE`), margins, schemes, net prices, or any "cut". Enforcement:
1. Profiles use a **whitelist**: they read only the columns mapped to the schema above. Other columns are never copied into memory structures that get saved, logged, exported or staged.
2. A test scans the database schema, staging JSON keys, review CSV headers, logs and search documents for names like `discount`, `td`, `rate` (except `gst_pct`), `dealer`, `trade`, `margin`, `net`, and fails the build on any hit.
3. A profile test per brand feeds a real sample page and asserts those columns are absent from the output.

**Note on saved source files:** the original PDF archive is a verbatim copy of what the supplier sent, so e.g. the Uno Minda PDF still contains its TD% column and the Pensol PDF its RATE column. Originals live in a **private** bucket, are downloadable only by logged-in admins via short-lived signed URLs, and are never served publicly. If you would rather not archive those columns at all, redact them on upload (see assumption 1).

---

## 5. Import batches, audit trail, delete and resync

Every import is a **batch**: one uploaded file, processed by one profile, tracked end to end.

```sql
import_batches(
  id uuid pk, brand_id fk, profile text, parser_version text,
  original_filename text, stored_path text,          -- private bucket path
  file_sha256 text, file_size_bytes bigint, page_count int,
  uploaded_at timestamptz, uploaded_by text,         -- date AND time, actor
  status text,    -- uploaded | parsing | needs_review | ready | applying | applied | failed | deleted
  rows_extracted int, rows_flagged int, rows_inserted int, rows_updated int,
  rows_unchanged int, rows_removed int,
  pages_needing_ocr int[],                           -- pages with no usable text layer, skipped
  notes text
)

batch_rows(id, batch_id fk, page int, row_no int, data jsonb, flags text[])
  -- staging: parsed rows waiting to be applied (whitelisted columns only)

sync_runs(id, batch_id fk, run_type,                 -- initial | resync | delete
          parser_version, started_at, finished_at, actor,
          inserted int, updated int, unchanged int, removed int, flagged int, status)

change_log(id bigserial, at, run_id fk, batch_id fk, product_id fk,
           action,                                   -- insert | update | delete
           before jsonb, after jsonb)                -- field-level history of every product change

audit_events(id bigserial, at timestamptz, actor text, event_type text,
             batch_id fk null, product_id fk null, details jsonb)
  -- append-only; never updated or deleted by the app
```

`audit_events.event_type` includes: `file_uploaded`, `duplicate_file_warning`, `parse_started`, `parse_finished`, `rows_flagged`, `ocr_pages_flagged`, `batch_applied`, `resync_previewed`, `resync_applied`, `batch_delete_requested`, `batch_deleted`, `file_purged`, `search_reindexed`, `login`.

### Lifecycle

1. **Upload** (admin UI): pick brand + profile + PDF. The file is saved to the private bucket under `batches/<batch_id>/<original_filename>`, with sha256, size, pages, uploader and timestamp recorded. If the same sha256 already exists, warn and show the earlier batch.
2. **Parse** (ingest service): extract with the profile into `batch_rows` (staging). Pages with no usable text layer are listed in `pages_needing_ocr` and skipped. Nothing touches `products` yet.
3. **Review**: show a preview diff against the current database (new / changed / unchanged), plus flagged rows. The admin can fix profile mapping and re-parse, or proceed.
4. **Apply**: upsert into `products` in one transaction, tagging every row with the batch, writing one `change_log` entry per product (before/after), creating a `sync_run`, and then updating Meilisearch for exactly the affected product ids.
5. **Resync** (any time, from the batch page): re-parse the **saved file** with the current profile and reconcile against the rows this batch owns. Show a preview first: added / changed (field-level before/after) / removed-from-file / unchanged. On confirmation, apply as a new `sync_run`. Rows that are no longer in the file are removed only if the admin ticks "remove rows missing from the file".
6. **Delete batch ("shred")**: remove everything the batch contributed, completely, then update the search index.
   - Products the batch **inserted**: deleted (with their cross-refs/fitments).
   - Products the batch **updated**: restored to their `before` values from the change log.
   - **Conflicts:** if a later batch has since changed the same product, that product is *not* reverted blindly. The confirmation screen lists these conflicts. Default is to skip them; the admin may choose to force-revert.
   - Staging rows for the batch are purged.
   - The **batch header, sync runs, change_log and audit events are kept** (status `deleted`) so the history of what happened still exists. The saved file is kept unless the admin also ticks "permanently delete the stored file" (logged as `file_purged`).
   - Requires typed confirmation (e.g. the filename) and shows exact counts first.

Correctness tests (must pass before the admin UI is built): apply then delete restores the database to a byte-identical snapshot; resync of an unchanged file produces zero changes; resync of an edited file produces exactly the expected diff; the search index matches the database after each operation.

### Analytics (per batch and overall)

- Per batch: rows extracted per page, flagged rows by reason, pages needing OCR, inserted/updated/unchanged/removed counts, parser version, duration.
- Overall: products per brand/category/segment, batches over time, last sync per brand, count of rows needing review.

---

## 6. Ingestion (PDF libraries only, no OCR)

Location: `ingest/` (Python package, CLI + FastAPI). Example: `python -m ingest parse --brand uno_minda --file data/pdfs/uno_minda/x.pdf`.

1. **Extract** with `pdfplumber` (tables and word coordinates) and `PyMuPDF` (fast text, embedded images). Check each page's text layer first; if a page yields too little text, record it in `pages_needing_ocr`, skip it, and surface it in the batch report. **No OCR or vision model in v1.**
2. **Profile**: one parser per layout in `ingest/profiles/<brand>.py`. New layout = new profile (written with Claude Code). The upload form requires choosing a profile; an unrecognised layout is reported, never guessed.
3. **Normalise**: `part_no_norm`, make via `make_aliases`, category via a per-brand map, prices to numbers (strip ₹, commas).
4. **Validate**: reject rows with no part number or a non-numeric MRP (blank MRP allowed when the source says NA), duplicates inside the batch, MRP outliers (>10× the category median), and old/new MRP swings above 40%. Flagged rows are kept in staging with `flags` and are visible in the UI (and downloadable as CSV).
5. **Report**: rows per page; a page with far fewer rows than its neighbours is a red flag.

### Known layouts (from the owner's samples)

**Uno Minda "MASTER PRICE LIST" (WEF APR'26)**: clean single-line table with text layer.
Columns: S.No, PART NO, P'GROUP (ABR / AST / BAH), DESCRIPTION, CLASS (4WH), SEGMENT (HCV / TTR / CAR), PRODUCT TYPE, OEM (codes: TTA., ASLY, VECV, ECST, MHRD, JHDR, VLVO, CASE NEW HOLLAND...), APPLICATION, NPD STATUS, MOQ, GST%, ~~TD% W/O GST~~ (**ignored, never read into storage**), HSN, MRP.
- P'GROUP appears to mean ABR = air-brake parts, AST = seats and seat parts, BAH = bulbs. Confirm and map to categories.
- Some descriptions are clipped in the source; set `needs_review` when a description ends mid-word or mid-bracket.
- Segment TTR = tractor. The yellow NPD highlight is lost in text extraction, so ignore it.

**Fras-le "XTRA LIFE" brake linings (w.e.f. 01-04-2026)**: grid with merged cells.
Columns: Sr.No, OEM, Segment, New Part No, Vehicle Application (merged across the group's rows), Front/Rear, pcs per set, std packing, MRP.
- The part number carries the variant in brackets: `AFF/XL/TTS/1 (OS-1)` → part_no `AFF/XL/TTS/1`, variant_label `OS-1` (STD/OS-1/OS-2/OS-3 are oversizes).
- The application text applies to every row in its group; this needs coordinate-based extraction because plain text extraction separates it from the rows.
- Footer says prices exclude GST → `price_basis = 'ex_tax'`. HSN 68138100.

**Neolite lamps, aftermarket price list (W.E.F. 01-April-2026)**: columns Product Code, Description, Unit, Std Pkg, MRP till 31.03.2026, Revised MRP.
- Section header rows are vehicle groups (MSZ 8-00, MSZ VAN T2, TAL TRUK/BUS, HDY ACCNT, MHND...). They become fitment/vehicle data, not products.
- The same code appears under several sections: one product, many fitments.
- Use **Revised MRP** as `mrp`, old value as `mrp_prev`; flag outliers (e.g. NEO-1641 drops from 3830 to 2399).
- The Neolite visual catalogue (images, "Suitable for", bulb fitment) can later enrich products by code.
- Maker codes: MSZ = Maruti Suzuki, TAL = Tata, MHND = Mahindra, HDY = Hyundai, CVRLT = Chevrolet, FOD = Ford, FAT = Fiat, PP = Premier (owner to confirm in `make_aliases`).

**Car International (Feb-26)**: columns PART NO, DESCRIPTION, NEW LIST (price), UNIT, HSN, GST RATE.
- No brand/vehicle column; the vehicle is inside the description ("Alto", "Ambassador", "Tata Ace", "I-10"). Extract make/model by keyword match and flag the rest.
- The price column is labelled "NEW LIST", not MRP. Treat it as the list price and confirm with the owner that it is the MRP.
- Some part numbers are doubled (`141/1203`, `366/9802`): keep the first as `part_no` and add the second as a `cross_refs` entry.
- At page breaks rows can run together (e.g. 158/159); parse with a part-number-then-description row regex, not by line.
- Some HSN codes are malformed (`8301000`): flag only.

**Pensol lubricants (dealer price list)**: the text layer looks poor/garbled and the page is two-column.
- Extract **MRP per pc only**. The `RATE` column is a dealer rate and is **ignored**.
- Try the PDF libraries first. If the text layer is unusable, the pages are listed in `pages_needing_ocr` and skipped (decide on OCR later).
- Each pack size is its own product row (variant_label = packing). Prices are tax-inclusive. `MRP = NA` on drums means no MRP; leave null. Category: Lubricants. Confirm that oils are in scope.

**Meko water pump catalogue**: visual catalogue (photo, model code M-401..., application text, **REF. NOS.** = OEM numbers).
- If the pages have a text layer, parse model code, application and ref numbers, and pull the embedded product photos with PyMuPDF (match photo to item by position on the page). If a page has no text layer it is flagged `needs_ocr` and skipped.
- REF. NOS. go into `cross_refs` as `oem`; this is the first real cross-reference data.
- The Meko "price list" sample contained only cover pages; use the real price pages when available.

---

## 7. Search design

Meilisearch index `products`, fields: `part_no`, `part_no_norm`, `ref_part_nos_norm` (all cross-ref numbers), `description`, `description_expanded` (abbreviations expanded), `brand`, `oem_name`, `application`, `category`, `segment`, `mrp`.

- **Ranking order**: part_no_norm → ref_part_nos_norm → description → category → oem_name → application → brand.
- **Filterable**: brand, oem_name, segment, category, mrp range.
- **Part number queries**: a token with a digit and ≥4 chars is also searched in normalised form, so `MB 0401-5028` finds `MB04015028`. Prefix matching on; **typo tolerance off** for these tokens.
- **Vehicle + part queries** ("tata 1612 water pump"): match across oem_name, application and description; aliases (tata/tml/telco → Tata) come from `make_aliases`.
- **Abbreviation expansion** in both directions, since the catalogues are full of them. Starter set, owner to review: H.L. = head lamp · T.L. = tail lamp · S.L. = side/indicator lamp · W.R. = window regulator · O.H. = outside handle · F.T. = fuel tank · B.O. = bonnet opener · DBV = dual brake valve · SBA = spring brake actuator · MSA = manual slack adjuster · QRV = quick release valve · MPV = multi protection valve · ULV = unloader valve · RV = relay valve. Beware `HCV` (hand control valve in brake lists vs heavy commercial vehicle as a segment label).
- **Index updates**: after every batch apply, resync or delete, update Meilisearch **incrementally** for the affected product ids and log `search_reindexed`. A full rebuild command exists for recovery.
- Performance target: p95 under 100 ms server-side at 100k documents.
- `search/tests/queries.json` holds 30–50 real queries with expected top results; run it as a regression test after every index change.

---

## 8. UI spec (clean, not fancy; English only)

### Public app (retailers, mechanics, counter staff), no login
- **Home**: large search box (autofocus on desktop), "Browse by vehicle make" tiles, "Browse by category" tiles.
- **Results**: instant search as you type (debounced), filters (brand, make, segment, category, price), infinite scroll or pagination, and a **compact list view toggle** for fast scanning at the counter.
- **Product card**: image (neutral placeholder if none) · brand · description · part number (tap to copy) · "Used for" (application, 2 lines) · OEM/cross-ref number if known · MRP · "Ask for availability" button.
- **Product page** `/p/[brand]-[part-no]` (SSR, indexable, title/meta/JSON-LD): all fields, cross-references, related items, WhatsApp button with a prefilled message (brand, part number, page URL).
- Empty state: "No results. Try the part number or the vehicle name, or ask us on WhatsApp."
- Mobile-first; works well on a cheap Android phone; large tap targets and good contrast.

WhatsApp number and business name live in `config/site.ts` / `.env`; placeholders are fine for now.

### Admin app (`/admin`, login required, allow-listed emails)
1. **Upload**: brand, profile, PDF. Duplicate-file warning by hash.
2. **Batches list**: filename, brand, uploaded date and time, uploader, status, row counts (inserted/updated/flagged), last sync time, actions.
3. **Batch detail**:
   - Summary analytics (rows per page, flags by reason, pages needing OCR, counts, parser version, duration).
   - **Timeline** of uploads, parses, applies, resyncs, deletes and search reindexes, each with time and actor.
   - **Changes tab**: every inserted/updated/removed product with field-level before/after, filterable.
   - **Flagged rows** review, with CSV download.
   - Actions: **Apply**, **Resync** (shows preview diff first), **Delete batch** (typed confirmation, exact counts, conflict list, optional "also delete stored file"), **Download original file**.
4. **Audit log**: global, filter by actor / event / batch / date / product, CSV export.
5. **Product history** (admin-only): the full change history of any product across batches.
6. **Dashboard**: the overall analytics from section 5.

---

## 9. Security and privacy

1. Public API and search index contain only published products and public columns. There are no discount fields anywhere (section 4), and the "never stored" test runs in CI.
2. Supabase RLS: anonymous read of published products only; no anonymous write. All writes go through the ingest service (service role), never from the browser.
3. Ingest service accepts calls only from the admin app (shared secret + user JWT check) and records the actor in `audit_events`.
4. Original PDFs: private bucket, signed URLs for admins only.
5. `audit_events` and `change_log` are append-only (no update/delete policy for any role except an explicit, logged purge of the stored file).
6. Rate-limit the public search API per IP to discourage bulk scraping.
7. Secrets only in env vars, never in the repo.

---

## 10. Repo structure

```
/
  PROJECT_PLAN.md
  apps/web/                 # Next.js: public app + /admin
  ingest/                   # Python: CLI + FastAPI service
    profiles/               # one file per brand layout
    parse.py  validate.py  apply.py  resync.py  rollback.py  index.py  audit.py
  db/migrations/
  data/pdfs/                # local samples only (git-ignored)
  data/config/              # make_aliases.csv, abbreviations.csv, category_map.csv
  search/tests/queries.json
  tests/                    # batch round-trip, never-stored, profile tests
  docker-compose.yml        # ingest service + Meilisearch
```

---

## 11. Milestones (2–3 days, solo owner)

Adding the batch/audit/admin scope makes 3 days tight. Build in this order so the riskiest and most valuable parts come first.

**Day 1: data foundation and batch engine**
- Repo, Supabase schema + migrations (including batches, staging, sync_runs, change_log, audit_events), private bucket, Meilisearch, config CSVs.
- Ingest engine: upload → parse → stage → preview → apply → resync → delete, via CLI and FastAPI.
- Profiles: Uno Minda, Fras-le, Neolite price list, Car International.
- *Done when:* the four round-trip tests in section 5 pass, the never-stored test passes, ≥1,500 published rows across ≥4 brands, and the 30-query search set passes.

**Day 2: public web app**
- Home, results, filters, card, product page, compact view, make/category browse, WhatsApp CTA.
- Deploy to staging.
- *Done when:* the owner can find a part by number, by description, and by "make + part type" on a phone and at a desktop counter.

**Day 3: admin UI and rollout**
- Admin login, upload, batches list, batch detail with timeline, changes, diff preview, apply, resync, delete, audit log, basic dashboard.
- Process more PDFs; production deploy.
- *Done when:* a batch can be uploaded, applied, resynced and deleted from the UI, and the timeline and audit log show every step.

**If time runs short, cut in this order:** dashboard charts → product history page → processing the remaining PDFs. Never cut the correctness tests or the audit trail. Not all of the 15–20 PDFs will be loaded in 3 days; each new layout needs a profile.

---

## 12. Later phases (do NOT build now)

**Phase 2:** Capacitor wrap for Android/iOS · barcode/part-number scanning · vehicle model/engine fitment · internal staff page to link cross-references and upload photos (resync must then not overwrite manually edited fields) · offline caching · OCR for flagged pages · saved lists / enquiry list.

**Phase 3:** retailer accounts and tiered pricing · cart / quote requests · stock sync from the accounting software (Tally/Busy) · payments, GST invoicing and delivery.

---

## 13. Assumptions to confirm with the owner

1. **Saved originals vs. "never store discounts":** archived PDFs still contain the supplier's discount/rate columns (Uno Minda TD%, Pensol RATE). Default: keep originals unmodified in a private, admin-only bucket. Alternative: redact those columns on upload before saving.
2. **"Delete batch" keeps the audit history** (batch header, runs, change log, events) and the saved file, unless you tick the purge box. Confirm this is what "shred" should mean.
3. **"Resync" means** re-reading the saved file with the current profile and reconciling the database with it (with a preview). Confirm.
4. Whether each brand's MRP includes GST (Fras-le says ex-GST; Pensol incl.; Uno Minda and Car International unclear). Until confirmed, show "MRP" and record `price_basis`.
5. Whether Car International's "NEW LIST" is the MRP.
6. Meaning of the Uno Minda P'GROUP codes (ABR/AST/BAH) and the make codes in `make_aliases`.
7. Whether lubricants (Pensol) are in scope at launch.
8. Real WhatsApp number, app name, domain, and the admin email allow-list.
9. Hosting budget: Vercel + Supabase + one small VPS/container (ingest service + Meilisearch).

---

## 14. Working agreements for Claude Code

- Work milestone by milestone; commit at the end of each, with a short README update.
- Prefer boring, well-known libraries. No microservices beyond the one ingest service, no premature optimisation.
- Every parse produces flagged rows in staging. Never silently drop or guess rows.
- Write tests for: part-number normalisation, each profile (real sample rows), the never-stored scan, batch apply/delete/resync round trips, and the search regression set.
- If a source layout is ambiguous, stop and ask rather than invent a parsing rule.
- No OCR, no i18n, no private tables.

---

## 15. First prompt to give Claude Code

> Read `PROJECT_PLAN.md` fully. Start Milestone 1 (Day 1). Set up the repo, the Postgres schema and migrations (including `import_batches`, `batch_rows`, `sync_runs`, `change_log`, `audit_events`), the private file bucket, and the Meilisearch config. Then build the batch engine (upload → parse → stage → preview → apply → resync → delete) and the Uno Minda profile, using only the PDF libraries and never reading or storing the TD% column. Run it end to end on the sample PDF, prove that apply followed by delete restores the database exactly, and show me the batch report (rows per page, flagged rows, pages needing OCR) before moving to the next brand. Ask me if anything in the plan conflicts with what you see in the PDFs.
