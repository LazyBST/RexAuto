-- Logos / icons for the catalogue lists.
--   brands.logo_url   already exists (product brands: Uno Minda, Car International ...)
--   makes             vehicle makes shown as tags (Tata, Maruti Suzuki ...); one row per make name as it appears in products.oem_name
--   categories        product categories, with a small icon
-- URLs point at the public "product-images" storage bucket (logos/...), copied there from the brands' official
-- sites / Wikimedia / Simple Icons so the app never hot-links someone else's server.

create table makes (
  name     text primary key,
  slug     text not null unique,
  logo_url text,
  source   text                     -- where the image came from (simpleicons / official-site / wikimedia)
);

create table categories (
  name     text primary key,
  icon_url text,
  source   text
);

alter table brands add column logo_source text;

-- same posture as every other table: RLS on, no policies; only the server role reads/writes
alter table makes      enable row level security;
alter table categories enable row level security;
