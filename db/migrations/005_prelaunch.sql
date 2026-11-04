-- Pre-launch schema hardening. Everything here is cheap before real data is loaded into the hosted database and
-- expensive (data-rewriting) afterwards.

-- 0. GST basis lives on the price list (batch), not on each product, and can be flipped later without a resync
alter table products drop column price_basis;
alter table import_batches add column price_includes_gst boolean;                       -- null = not known yet
alter table products add column mrp_batch_id uuid references import_batches(id);        -- the batch whose file the MRP came from
create index products_mrp_batch_id_idx on products (mrp_batch_id);

-- 1. Source columns that used to be dropped, price-list dates, and protection for hand edits ---------------------------
alter table products add column attributes jsonb not null default '{}';        -- source-specific extras (class, product type, NPD status, pcs per set ...)
alter table products add column price_effective_from date;                     -- "w.e.f." date of the price list the MRP came from
alter table products add column locked_fields text[] not null default '{}';    -- fields a person edited by hand; resync must not overwrite them
alter table import_batches add column effective_from date;
alter table products add constraint products_variant_trimmed check (variant_label = btrim(variant_label));

-- 2. Cross references: supersession direction -----------------------------------------------------------------------
alter table cross_refs add column direction text check (direction in ('replaces', 'replaced_by'));

-- 3. Several images per product (products.image_url stays the primary photo) --------------------------------------
create table product_images (
  id         uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id) on delete cascade,
  url        text not null,
  kind       text not null default 'photo',
  sort       int  not null default 0,
  caption    text
);
create index product_images_product_id_idx on product_images (product_id);

-- 4. Vehicle fitments: one row per product + vehicle, with year range and engine (replaces the empty vehicles/fitments pair)
drop table fitments;
drop table vehicles;
create table fitments (
  id         uuid primary key default gen_random_uuid(),
  product_id uuid not null references products(id) on delete cascade,
  make       text not null,
  model      text,
  variant    text,
  year_from  int,
  year_to    int,
  engine     text,
  note       text
);
create index fitments_product_id_idx on fitments (product_id);
create index fitments_make_model_idx on fitments (make, model);

-- 5. Missing indexes -------------------------------------------------------------------------------------------------
create index cross_refs_product_id_idx   on cross_refs (product_id);
create index products_first_batch_id_idx on products (first_batch_id);
create index products_brand_category_idx on products (brand_id, category);
create index products_segment_idx        on products (segment);
create index sync_runs_batch_id_idx      on sync_runs (batch_id);
create index change_log_run_id_idx       on change_log (run_id);

-- trigram index for substring search, where the extension exists (Supabase has it; the local dev Postgres may not)
do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pg_trgm') then
    if exists (select 1 from information_schema.schemata where schema_name = 'extensions') then
      create extension if not exists pg_trgm with schema extensions;
    else
      create extension if not exists pg_trgm;
    end if;
    execute 'create index product_search_text_trgm on product_search using gin (text gin_trgm_ops)';
  end if;
end $$;

-- 6. History cannot be emptied either (row triggers did not stop TRUNCATE) -------------------------------------------
create trigger audit_events_no_truncate before truncate on audit_events for each statement execute function forbid_mutation();
create trigger change_log_no_truncate   before truncate on change_log   for each statement execute function forbid_mutation();

-- 7. Row-level security: children are public only when their product is ---------------------------------------------
drop policy cross_refs_public_read on cross_refs;
create policy cross_refs_public_read on cross_refs for select
  using (exists (select 1 from products p where p.id = cross_refs.product_id and p.status = 'published'));
alter table product_images enable row level security;
create policy product_images_public_read on product_images for select
  using (exists (select 1 from products p where p.id = product_images.product_id and p.status = 'published'));
alter table fitments enable row level security;
create policy fitments_public_read on fitments for select
  using (exists (select 1 from products p where p.id = fitments.product_id and p.status = 'published'));

-- 8. Public bucket for product photos (originals stay in the private 'batch-files' bucket) --------------------------
do $$
begin
  if exists (select 1 from information_schema.schemata where schema_name = 'storage') then
    insert into storage.buckets (id, name, public) values ('product-images', 'product-images', true)
    on conflict (id) do update set public = true;
  end if;
end $$;
