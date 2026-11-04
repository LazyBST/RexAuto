-- Denormalised search text per product (own columns + brand + cross references), refreshed after every
-- apply / resync / delete. Keeps search a single indexed-table scan. Derived data: never part of a snapshot.
create table product_search (
  product_id uuid primary key references products(id) on delete cascade,
  text       text not null
);
alter table product_search enable row level security;
