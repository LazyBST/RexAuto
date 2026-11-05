-- Website visitors. One row per opening of the site (once per browser tab session); the public counter is a single row.
-- The IP address is never stored: only a salted hash, which is enough to count unique visitors.
create table visit_counter (
  id    int primary key default 1 check (id = 1),
  total bigint not null default 0
);
insert into visit_counter (id, total) values (1, 0);

create table visits (
  id          bigserial primary key,
  visited_at  timestamptz not null default now(),
  ip_hash     text not null,
  is_new_ip   boolean not null,          -- first time this IP hash was ever seen
  country     text,
  user_agent  text,
  referrer    text
);
create index visits_visited_at_idx on visits (visited_at);
create index visits_ip_hash_idx on visits (ip_hash);

-- For the future admin page: select * from visitor_stats;
create view visitor_stats as
  select (select total from visit_counter where id = 1)                         as total_visits,
         count(distinct ip_hash)                                                as unique_visitors,
         count(*) filter (where visited_at >= now() - interval '24 hours')      as visits_24h,
         count(distinct ip_hash) filter (where visited_at >= now() - interval '24 hours') as unique_24h,
         count(*) filter (where visited_at >= date_trunc('day', now()))         as visits_today
  from visits;

-- Only the server (database owner) reads or writes these; nothing is exposed through the public API.
alter table visit_counter enable row level security;
alter table visits enable row level security;
