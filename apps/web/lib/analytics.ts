import { sql } from "./db";

type Row = Record<string, any>;
export type Dim = { name: string; searched: number; typed: number; filtered: number; viewed: number; total: number };

const TZ = "Asia/Kolkata";
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function merge(parts: { key: "searched" | "typed" | "filtered" | "viewed"; rows: Row[] }[]): Dim[] {
  const m = new Map<string, Dim>();
  for (const { key, rows } of parts)
    for (const r of rows) {
      if (!r.name) continue;
      const d = m.get(r.name) ?? { name: r.name, searched: 0, typed: 0, filtered: 0, viewed: 0, total: 0 };
      d[key] += Number(r.n);
      m.set(r.name, d);
    }
  return [...m.values()].map((d) => ({ ...d, total: d.searched + d.typed + d.filtered + d.viewed })).sort((a, b) => b.total - a.total);
}

// Everything the /analytics page shows, for events since `days` ago (0 = all time).
export async function loadAnalytics(days: number) {
  const since = days > 0 ? new Date(Date.now() - days * 864e5) : new Date(0);
  const S = sql`${since}::timestamptz`;
  const span = days > 0 ? Math.min(days, 90) : 90;

  const dominant = (col: "category" | "segment" | "brand" | "make") => {
    if (col === "brand")
      return sql`select x.name, count(*)::int n from search_events e cross join lateral
        (select b.name from products p join brands b on b.id = p.brand_id where p.id = any(e.top_ids) group by 1 order by count(*) desc, 1 limit 1) x
        where e.at >= ${S} group by 1`;
    if (col === "make")
      return sql`select x.name, count(*)::int n from search_events e cross join lateral
        (select m as name from products p cross join lateral unnest(string_to_array(p.oem_name, ' / ')) m where p.id = any(e.top_ids) group by 1 order by count(*) desc, 1 limit 1) x
        where e.at >= ${S} group by 1`;
    const c = sql(col);
    return sql`select x.name, count(*)::int n from search_events e cross join lateral
      (select p.${c} as name from products p where p.id = any(e.top_ids) and p.${c} is not null group by 1 order by count(*) desc, 1 limit 1) x
      where e.at >= ${S} group by 1`;
  };
  const filtered = (key: string) => sql`select filters->>${key} as name, count(*)::int n from search_events where at >= ${S} and filters ? ${key} group by 1`;
  const viewed = (col: "category" | "segment" | "brand" | "make") => {
    if (col === "brand")
      return sql`select b.name, count(*)::int n from product_views v join products p on p.id = v.product_id join brands b on b.id = p.brand_id where v.at >= ${S} group by 1`;
    if (col === "make")
      return sql`select m as name, count(*)::int n from product_views v join products p on p.id = v.product_id cross join lateral unnest(string_to_array(p.oem_name, ' / ')) m where v.at >= ${S} group by 1`;
    const c = sql(col);
    return sql`select p.${c} as name, count(*)::int n from product_views v join products p on p.id = v.product_id where v.at >= ${S} and p.${c} is not null group by 1`;
  };

  const [sum, vsum, ctr, daily, hourly, topQ, zeroQ, topViewed, topShown, recent, logoM, logoB, logoC, aliases, allMakes, allBrands,
    dCat, dBrand, dMake, dSeg, fCat, fBrand, fMake, fSeg, vCat, vBrand, vMake, vSeg, qAgg] = await Promise.all([
    sql`select count(*)::int searches, count(distinct sid)::int sessions, count(distinct ip_hash)::int people,
        count(*) filter (where total = 0)::int zero, coalesce(round(avg(total)), 0)::int avg_results, count(*) filter (where corrected)::int corrected
        from search_events where at >= ${S}`,
    sql`select count(*)::int views, count(distinct product_id)::int products, count(distinct sid)::int sessions from product_views where at >= ${S}`,
    sql`select count(*)::int searches, count(*) filter (where exists
          (select 1 from product_views v where v.sid = e.sid and v.at >= e.at and v.at < e.at + interval '10 minutes'))::int clicked
        from search_events e where e.at >= ${S} and e.sid is not null and e.total > 0`,
    sql`with d as (select generate_series((now() at time zone ${TZ})::date - ${span - 1}::int, (now() at time zone ${TZ})::date, interval '1 day')::date as day)
        select d.day::text as day, coalesce(s.n, 0)::int searches, coalesce(v.n, 0)::int views from d
        left join (select (at at time zone ${TZ})::date as day, count(*) as n from search_events group by 1) s on s.day = d.day
        left join (select (at at time zone ${TZ})::date as day, count(*) as n from product_views group by 1) v on v.day = d.day order by d.day`,
    sql`select extract(hour from at at time zone ${TZ})::int h, count(*)::int n from search_events where at >= ${S} group by 1`,
    sql`select query_norm as q, count(*)::int n, count(distinct sid)::int people, coalesce(round(avg(total)), 0)::int avg_results,
        count(*) filter (where total = 0)::int zero from search_events where at >= ${S} and query_norm <> '' group by 1 order by n desc, 1 limit 30`,
    sql`select query_norm as q, count(*)::int n, to_char(max(at) at time zone ${TZ}, 'DD Mon, HH12:MI am') as last from search_events where at >= ${S} and query_norm <> '' and total = 0 group by 1 order by n desc, 1 limit 20`,
    sql`select p.id::text, p.part_no, p.description, p.category, p.oem_name, b.name brand, count(*)::int views, count(distinct v.sid)::int people,
        count(*) filter (where v.source = 'list')::int from_list
        from product_views v join products p on p.id = v.product_id join brands b on b.id = p.brand_id where v.at >= ${S}
        group by p.id, b.name order by views desc, p.part_no limit 25`,
    sql`select p.id::text, p.part_no, p.description, p.category, p.oem_name, b.name brand, count(*)::int shown
        from search_events e cross join lateral unnest(e.top_ids) as t(pid) join products p on p.id = t.pid join brands b on b.id = p.brand_id
        where e.at >= ${S} group by p.id, b.name order by shown desc, p.part_no limit 25`,
    sql`select to_char(at at time zone ${TZ}, 'DD Mon, HH12:MI am') as at, query, filters, total from search_events order by id desc limit 40`,
    sql`select name, logo_url from makes where logo_url is not null`,
    sql`select name, logo_url from brands where logo_url is not null`,
    sql`select name, icon_url as logo_url from categories where icon_url is not null`,
    sql`select upper(raw) as raw, make from make_aliases`,
    sql`select name from makes`,
    sql`select name from brands`,
    dominant("category"), dominant("brand"), dominant("make"), dominant("segment"),
    filtered("category"), filtered("brand"), filtered("make"), filtered("segment"),
    viewed("category"), viewed("brand"), viewed("make"), viewed("segment"),
    sql`select query_norm as q, count(*)::int n from search_events where at >= ${S} and query_norm <> '' group by 1 order by n desc limit 5000`,
  ]);

  // names typed in the query itself (e.g. "tata brake valve" mentions Tata); matched in code so word boundaries and aliases are easy
  const mention = (names: { name: string; terms: string[] }[]) => {
    const res = new Map<string, number>();
    const rx = names.map((n) => ({ name: n.name, re: new RegExp("(^|[^a-z0-9])(" + n.terms.map((t) => esc(t.toLowerCase())).join("|") + ")($|[^a-z0-9])") }));
    for (const r of qAgg) for (const { name, re } of rx) if (re.test(r.q)) res.set(name, (res.get(name) ?? 0) + Number(r.n));
    return [...res].map(([name, n]) => ({ name, n }));
  };
  const makeTerms = new Map<string, string[]>();
  for (const r of allMakes) makeTerms.set(r.name, [r.name]);
  for (const a of aliases) { const t = makeTerms.get(a.make) ?? [a.make]; if (!t.includes(String(a.raw))) t.push(String(a.raw).replace(/^\.+|\.+$/g, "")); makeTerms.set(a.make, t); }
  const typedMake = mention([...makeTerms].map(([name, terms]) => ({ name, terms: terms.filter((t) => t.length >= 2) })));
  const typedBrand = mention(allBrands.map((b: Row) => ({ name: b.name, terms: [b.name] })));

  const hours = Array.from({ length: 24 }, (_, h) => ({ h, n: Number(hourly.find((r: Row) => r.h === h)?.n ?? 0) }));
  const logos = {
    makes: Object.fromEntries(logoM.map((r: Row) => [r.name, r.logo_url])),
    brands: Object.fromEntries(logoB.map((r: Row) => [r.name, r.logo_url])),
    categories: Object.fromEntries(logoC.map((r: Row) => [r.name, r.logo_url])),
  };

  return {
    days, summary: { ...(sum[0] as Row), ...(vsum[0] as Row), click_searches: ctr[0].searches, click_through: ctr[0].clicked } as Row,
    daily, hours, topQueries: topQ, zeroQueries: zeroQ, topViewed, topShown, recent, logos,
    categories: merge([{ key: "searched", rows: dCat }, { key: "filtered", rows: fCat }, { key: "viewed", rows: vCat }]),
    brands: merge([{ key: "searched", rows: dBrand }, { key: "typed", rows: typedBrand }, { key: "filtered", rows: fBrand }, { key: "viewed", rows: vBrand }]),
    makes: merge([{ key: "searched", rows: dMake }, { key: "typed", rows: typedMake }, { key: "filtered", rows: fMake }, { key: "viewed", rows: vMake }]),
    segments: merge([{ key: "searched", rows: dSeg }, { key: "filtered", rows: fSeg }, { key: "viewed", rows: vSeg }]),
  };
}
