// Catalogue search straight from Postgres: a TypeScript port of ingest/pgsearch.py (same rules, same results).
import { sql } from "./db";

type Row = Record<string, any>;
export type Filters = { brand?: string; make?: string; segment?: string; category?: string; min_price?: string; max_price?: string };

const HAY = "coalesce(ps.text, '')";
const FROM =
  "from products p join brands b on b.id = p.brand_id left join product_search ps on ps.product_id = p.id " +
  "left join import_batches mb on mb.id = p.mrp_batch_id";
const BASIS = "case mb.price_includes_gst when true then 'incl_tax' when false then 'ex_tax' else 'unknown' end";
const CARD = `p.id, p.part_no, p.variant_label, p.description, p.application, p.oem_name, p.oem_raw, p.category, p.segment,
  p.mrp, ${BASIS} as price_basis, p.image_url, p.unit, p.pack_qty, b.name as brand, b.slug as brand_slug`;
const STOP = new Set(["for", "of", "the"]);

const esc = (s: string) => s.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_");
const like = (s: string) => "%" + esc(s) + "%";
const normPart = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]/g, "");
const tokenize = (q: string) => (q.toLowerCase().match(/[a-z0-9./&+-]+/g) ?? []).filter((t) => !STOP.has(t));
const reEsc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const stem = (t: string) => (t.length > 3 && t.endsWith("s") && !t.endsWith("ss") ? t.slice(0, -1) : t);
// how an abbreviation may be written: W.R. / WR / W R, with or without dots
const abbrRegex = (ab: string) => "(?<![A-Za-z0-9])" + [...ab].map(reEsc).join("\\.?") + "\\.?(?![A-Za-z0-9])";

class Args {
  list: any[] = [];
  p(v: any) { this.list.push(v); return "$" + this.list.length; }
}

let cache: { aliases: Map<string, string>; abbr: [string, string[]][]; at: number } | null = null;
async function lookups() {
  if (!cache || Date.now() - cache.at > 600_000) {
    const [al, ab] = await Promise.all([
      sql.unsafe("select upper(raw) as raw, make from make_aliases"),
      sql.unsafe("select abbr, expansion from abbreviations"),
    ]);
    cache = {
      aliases: new Map(al.map((r: Row) => [String(r.raw).replace(/^\.+|\.+$/g, "").trim(), r.make])),
      abbr: ab.map((r: Row) => [String(r.abbr).replace(/[^A-Za-z0-9]/g, "").toUpperCase(), String(r.expansion).toLowerCase().split(/\s+/)] as [string, string[]]),
      at: Date.now(),
    };
  }
  return cache;
}

async function where(q: string, f: Filters, exclude?: string) {
  const { aliases, abbr } = await lookups();
  const a = new Args();
  const sqlParts = ["p.status = 'published'"];
  q = (q || "").trim();
  if (q) {
    const qn = normPart(q);
    const tokens = tokenize(q);
    const parts: string[] = [];
    if (qn.length >= 3 && /\d/.test(qn)) {
      parts.push(`p.part_no_norm like ${a.p(qn.length < 5 ? like(qn).slice(1) : like(qn))}`);          // short codes: prefix only
      parts.push(`exists (select 1 from cross_refs c where c.product_id = p.id and c.ref_part_no_norm like ${a.p(like(qn).slice(1))})`);
    }
    if (!tokens.length && !parts.length) sqlParts.push("false"); // only symbols: nothing to look for
    const tok: string[] = [];
    for (const t of tokens) {
      const alts = [`(${HAY}) ilike ${a.p(like(t))}`];
      if (t.length > 3 && t.endsWith("s") && !t.endsWith("ss")) alts.push(`(${HAY}) ilike ${a.p(like(t.slice(0, -1)))}`);
      const make = aliases.get(t.toUpperCase().replace(/^\.+|\.+$/g, ""));
      if (make) alts.push(`p.oem_name ilike ${a.p(like(make))}`);
      for (const [ab, words] of abbr) {
        if (words.includes(t)) alts.push(`(${HAY}) ~* ${a.p(abbrRegex(ab))}`);               // "lamp" -> rows that only say TL / HL
        else if (t.replace(/\./g, "").toUpperCase() === ab) {                                // "hl" -> rows that spell it out or write H.L.
          alts.push(`(${HAY}) ilike ${a.p(like(words.join(" ")))}`);
          alts.push(`(${HAY}) ~* ${a.p(abbrRegex(ab))}`);
        }
      }
      tok.push("(" + alts.join(" or ") + ")");
    }
    if (tok.length) parts.push("(" + tok.join(" and ") + ")");
    if (parts.length) sqlParts.push("(" + parts.join(" or ") + ")");
  }
  const eq: [keyof Filters, string][] = [["brand", "b.slug"], ["segment", "p.segment"], ["category", "p.category"]];
  for (const [k, col] of eq) if (f[k] && exclude !== k) sqlParts.push(`${col} = ${a.p(f[k])}`);
  if (f.make && exclude !== "make") sqlParts.push(`p.oem_name ilike ${a.p(like(f.make))}`);
  if (f.min_price) sqlParts.push(`p.mrp >= ${a.p(Number(f.min_price))}`);
  if (f.max_price) sqlParts.push(`p.mrp <= ${a.p(Number(f.max_price))}`);
  return { text: sqlParts.join(" and "), a };
}

let vocab: { words: Map<string, number>; at: number } | null = null;
async function getVocab() {
  if (!vocab || Date.now() - vocab.at > 600_000) {
    const rows = await sql.unsafe(
      "select w, count(*)::int n from (select lower(regexp_split_to_table(text, '[^A-Za-z]+')) w from product_search) s where length(w) >= 3 group by w");
    vocab = { words: new Map(rows.map((r: Row) => [r.w, r.n])), at: Date.now() };
  }
  return vocab.words;
}
const ratio = (a: string, b: string) => { // edit-distance based similarity, enough for one-letter typos
  const m = a.length, n = b.length; const d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
  for (let j = 1; j <= n; j++) d[0][j] = j;
  for (let i = 1; i <= m; i++) for (let j = 1; j <= n; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  return 1 - d[m][n] / Math.max(m, n);
};
async function correct(q: string) {
  const v = await getVocab();
  const out: string[] = [];
  for (const t of tokenize(q)) {
    if (v.has(t) || /\d/.test(t) || t.length < 2) { out.push(t); continue; }
    let split: string | null = null;
    for (let i = 3; i < t.length - 2 && !split; i++) if (v.has(t.slice(0, i)) && v.has(t.slice(i))) split = `${t.slice(0, i)} ${t.slice(i)}`;
    if (split) { out.push(split); continue; }
    const cutoff = t.length > 3 ? 0.8 : 0.75;
    let best: string | null = null, bestN = -1;
    for (const [w, n] of v) if (Math.abs(w.length - t.length) <= 2 && w[0] === t[0] && ratio(t, w) >= cutoff && n > bestN) { best = w; bestN = n; }
    out.push(best ?? t);
  }
  return out.join(" ");
}

const clean = (r: Row) => ({ ...r, id: String(r.id), mrp: r.mrp == null ? null : Number(r.mrp) });

async function searchOnce(q: string, f: Filters, limit: number, offset: number) {
  const t0 = Date.now();
  const w = await where(q, f);
  const qn = normPart(q || "");
  let rank = "4", rankArgs: any[] = [];
  if ((q || "").trim()) {
    const toks = tokenize(q);
    const st = toks.map(stem);
    const literal = toks.length ? toks.map(() => `(${HAY}) ilike $@`).join(" and ") : "false";
    rank = `case when p.part_no_norm = $@ then 0 when p.part_no_norm like $@ then 1 when p.part_no_norm like $@ then 2 when p.description ilike $@ then 3 when ${literal} then 4 else 5 end`;
    rankArgs = [qn, like(qn).slice(1), like(qn), like(st.join(" ")), ...toks.map(like)];
  }
  const base = w.a.list.length;
  let i = base; rank = rank.replace(/\$@/g, () => "$" + ++i);
  const hitsSql = `select ${CARD} ${FROM} where ${w.text} order by ${rank}, p.mrp is null, b.name, p.part_no, p.variant_label limit $${i + 1} offset $${i + 2}`;
  const facet = async (name: string, key: string, label: string) => {
    const fw = await where(q, f, name);
    return sql.unsafe(`select ${key} as value, ${label} as label, count(*)::int n ${FROM} where ${fw.text} and ${key} is not null group by 1, 2 order by n desc limit 40`, fw.a.list);
  };
  const makeW = await where(q, f, "make");
  const [total, hits, brand, segment, category, make] = await Promise.all([
    sql.unsafe(`select count(*)::int n ${FROM} where ${w.text}`, w.a.list),
    sql.unsafe(hitsSql, [...w.a.list, ...rankArgs, limit, offset]),
    facet("brand", "b.slug", "b.name"), facet("segment", "p.segment", "p.segment"), facet("category", "p.category", "p.category"),
    sql.unsafe(`select m as value, m as label, count(*)::int n from (select unnest(string_to_array(p.oem_name, ' / ')) m ${FROM} where ${makeW.text}) s where m is not null group by 1 order by n desc limit 30`, makeW.a.list),
  ]);
  return { total: total[0].n as number, hits: hits.map(clean), facets: { brand, segment, category, make }, ms: Date.now() - t0 } as Row;
}

export async function search(q = "", f: Filters = {}, limit = 30, offset = 0): Promise<Row> {
  const r = await searchOnce(q, f, limit, offset);
  if (r.total === 0 && q.trim()) {
    const fixed = await correct(q);
    if (fixed !== tokenize(q).join(" ")) {
      const r2 = await searchOnce(fixed, f, limit, offset);
      if (r2.total) return { ...r2, corrected_from: q, query: fixed };
    }
  }
  return r;
}

export async function product(id: string): Promise<Row | null> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) return null;
  const rows = await sql.unsafe(`select p.*, ${BASIS} as price_basis, b.name as brand, b.slug as brand_slug ${FROM} where p.id = $1 and p.status = 'published'`, [id]);
  if (!rows.length) return null;
  const p: Row = { ...rows[0] };
  delete p.locked_fields; delete p.created_at; delete p.updated_at;
  p.mrp = p.mrp == null ? null : Number(p.mrp);
  const [refs, imgs, fit, variants, related, same] = await Promise.all([
    sql.unsafe("select ref_type, ref_brand, ref_part_no, note from cross_refs where product_id = $1 order by ref_type, ref_part_no", [id]),
    sql.unsafe("select url, kind from product_images where product_id = $1 order by sort, url", [id]),
    sql.unsafe("select make, model, variant, year_from, year_to, engine, note from fitments where product_id = $1 order by make, model", [id]),
    sql.unsafe(`select ${CARD} ${FROM} where p.brand_id = $1 and p.part_no_norm = $2 and p.id <> $3 and p.status = 'published' order by p.variant_label`, [p.brand_id, p.part_no_norm, id]),
    sql.unsafe(`select ${CARD} ${FROM} where p.category = $1 and p.oem_name is not distinct from $2 and p.id <> $3 and p.status = 'published' order by p.mrp limit 8`, [p.category, p.oem_name, id]),
    sql.unsafe(`select ${CARD} ${FROM} where p.part_no_norm = $1 and p.brand_id <> $2 and p.status = 'published' limit 8`, [p.part_no_norm, p.brand_id]),
  ]);
  p.cross_refs = refs; p.fitments = fit;
  p.images = [...(p.image_url ? [{ url: p.image_url, kind: "photo" }] : []), ...imgs];
  p.variants = variants.map(clean); p.related = related.map(clean); p.same_number_elsewhere = same.map(clean);
  return p;
}
