-- Spare parts catalogue: core schema. Plain Postgres, Supabase compatible.
-- HARD RULE: no discount / dealer rate / trade cut / margin / net price column exists anywhere.

create table brands (
  id          uuid primary key default gen_random_uuid(),
  name        text not null unique,
  slug        text not null unique,
  logo_url    text,
  owned       boolean not null default true
);

create table import_batches (
  id                  uuid primary key default gen_random_uuid(),
  brand_id            uuid not null references brands(id),
  profile             text not null,
  parser_version      text not null,
  original_filename   text not null,
  stored_path         text not null,
  file_sha256         text not null,
  file_size_bytes     bigint not null,
  page_count          int,
  uploaded_at         timestamptz not null default now(),
  uploaded_by         text not null,
  status              text not null default 'uploaded'
    check (status in ('uploaded','parsing','needs_review','ready','applying','applied','failed','deleted')),
  rows_extracted      int not null default 0,
  rows_flagged        int not null default 0,
  rows_inserted       int not null default 0,
  rows_updated        int not null default 0,
  rows_unchanged      int not null default 0,
  rows_removed        int not null default 0,
  pages_needing_ocr   int[] not null default '{}',
  pages_unrecognised  int[] not null default '{}',
  rows_per_page       jsonb not null default '{}',
  flag_counts         jsonb not null default '{}',
  parse_seconds       numeric,
  notes               text
);
create index on import_batches (file_sha256);
create index on import_batches (brand_id);

create table products (
  id             uuid primary key default gen_random_uuid(),
  brand_id       uuid not null references brands(id),
  part_no        text not null,
  part_no_norm   text not null,
  description    text,
  category       text,
  segment        text,
  oem_name       text,
  oem_raw        text,
  application    text,
  variant_label  text not null default '',
  mrp            numeric,
  mrp_prev       numeric,
  price_basis    text not null default 'unknown' check (price_basis in ('incl_tax','ex_tax','unknown')),
  gst_pct        numeric,
  hsn            text,
  moq            int,
  pack_qty       int,
  unit           text,
  image_url      text,
  stock_status   text not null default 'ask',
  status         text not null default 'published' check (status in ('published','hidden')),
  needs_review   boolean not null default false,
  review_note    text,
  first_batch_id uuid references import_batches(id),
  last_batch_id  uuid references import_batches(id),
  source_page    int,
  source_row     int,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (brand_id, part_no_norm, variant_label)
);
create index on products (part_no_norm text_pattern_ops);
create index on products (last_batch_id);

create table vehicles (
  id     uuid primary key default gen_random_uuid(),
  make   text not null,
  model  text,
  engine text,
  notes  text
);

create table fitments (
  product_id uuid not null references products(id) on delete cascade,
  vehicle_id uuid not null references vehicles(id) on delete cascade,
  note       text,
  primary key (product_id, vehicle_id)
);

create table cross_refs (
  id               uuid primary key default gen_random_uuid(),
  product_id       uuid not null references products(id) on delete cascade,
  ref_type         text not null check (ref_type in ('oem','competitor','supersession')),
  ref_brand        text,
  ref_part_no      text not null,
  ref_part_no_norm text not null,
  note             text
);
create index on cross_refs (ref_part_no_norm);

create table make_aliases (raw text primary key, make text not null);
create table abbreviations (abbr text primary key, expansion text not null);
create table category_map (brand_slug text not null, source_code text not null, category text not null,
                           primary key (brand_slug, source_code));

-- staging: parsed rows waiting to be applied (whitelisted product columns only)
create table batch_rows (
  id        bigserial primary key,
  batch_id  uuid not null references import_batches(id),
  page      int not null,
  row_no    int not null,
  data      jsonb not null,
  flags     text[] not null default '{}'
);
create index on batch_rows (batch_id);

create table sync_runs (
  id             uuid primary key default gen_random_uuid(),
  batch_id       uuid not null references import_batches(id),
  run_type       text not null check (run_type in ('initial','resync','delete')),
  parser_version text,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  actor          text not null,
  inserted       int not null default 0,
  updated        int not null default 0,
  unchanged      int not null default 0,
  removed        int not null default 0,
  flagged        int not null default 0,
  status         text not null default 'running' check (status in ('running','done','failed'))
);

create table change_log (
  id         bigserial primary key,
  at         timestamptz not null default now(),
  run_id     uuid not null references sync_runs(id),
  batch_id   uuid not null references import_batches(id),
  product_id uuid not null,                -- no FK: the product may be deleted, history stays
  action     text not null check (action in ('insert','update','delete')),
  before     jsonb,
  after      jsonb
);
create index on change_log (batch_id);
create index on change_log (product_id);

create table audit_events (
  id         bigserial primary key,
  at         timestamptz not null default now(),
  actor      text not null,
  event_type text not null,
  batch_id   uuid references import_batches(id),
  product_id uuid,
  details    jsonb not null default '{}'
);
create index on audit_events (batch_id);
create index on audit_events (event_type);

-- append-only history
create function forbid_mutation() returns trigger language plpgsql as $$
begin raise exception '% is append-only', tg_table_name; end $$;
create trigger audit_events_append_only before update or delete on audit_events
  for each row execute function forbid_mutation();
create trigger change_log_append_only before update or delete on change_log
  for each row execute function forbid_mutation();

-- public read: published products only; no anonymous writes (all writes use the service role)
alter table products enable row level security;
create policy products_public_read on products for select using (status = 'published');
alter table brands enable row level security;
create policy brands_public_read on brands for select using (true);
alter table cross_refs enable row level security;
create policy cross_refs_public_read on cross_refs for select using (true);

-- everything else: RLS on, no policies => invisible to anon/authenticated; service role bypasses RLS
alter table import_batches enable row level security;
alter table batch_rows     enable row level security;
alter table sync_runs      enable row level security;
alter table change_log     enable row level security;
alter table audit_events   enable row level security;
alter table vehicles       enable row level security;
alter table fitments       enable row level security;
alter table make_aliases   enable row level security;
alter table abbreviations  enable row level security;
alter table category_map   enable row level security;
