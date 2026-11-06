-- Usage analytics: what people search for and which products they open.
-- No personal data: the visitor is a random per-tab session id plus a salted hash of the IP (same scheme as visits).
-- Rows are append-only. product_id / top_ids are deliberately NOT foreign keys: a re-imported or removed product
-- must not erase its history.

create table search_events (
  id        bigserial primary key,
  at        timestamptz not null default now(),
  sid       text,                                   -- random id kept in the browser tab (sessionStorage)
  ip_hash   text,
  query     text   not null default '',             -- as typed
  query_norm text  not null default '',             -- lower-case, single spaces
  filters   jsonb  not null default '{}',           -- {brand, make, segment, category, min_price, max_price} that were applied
  total     int,                                    -- number of results
  ms        int,
  corrected boolean not null default false,         -- the search corrected a typo
  top_ids   uuid[] not null default '{}'            -- first (up to 10) products shown
);
create index search_events_at_idx on search_events (at);
create index search_events_query_idx on search_events (query_norm);
create index search_events_sid_idx on search_events (sid, at);

create table product_views (
  id         bigserial primary key,
  at         timestamptz not null default now(),
  sid        text,
  ip_hash    text,
  product_id uuid not null,
  source     text not null default 'list',          -- list | related | link
  query      text                                   -- the search that led to the view, if any
);
create index product_views_at_idx on product_views (at);
create index product_views_product_idx on product_views (product_id);
create index product_views_sid_idx on product_views (sid, at);

alter table search_events enable row level security;
alter table product_views enable row level security;
