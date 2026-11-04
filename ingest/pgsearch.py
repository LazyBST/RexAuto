"""Search straight from Postgres (proof-of-concept). Same shape as the Meilisearch plan's searchProducts(query, filters),
so the Meilisearch backend can replace this file's search() later without touching the UI."""
import difflib
import re
import time

from . import normalize as nz
from .db import cursor

HAY = "coalesce(ps.text, '')"   # product_search: own columns + brand + cross references, refreshed by the batch engine
FROM = "from products p join brands b on b.id = p.brand_id left join product_search ps on ps.product_id = p.id"
_cache = {}


def _lookups(cur):
    if "aliases" not in _cache:
        cur.execute("select upper(raw) raw, make from make_aliases")
        _cache["aliases"] = {r["raw"].strip(".").strip(): r["make"] for r in cur.fetchall()}
        cur.execute("select abbr, expansion from abbreviations")
        _cache["abbr"] = [(re.sub(r"[^A-Za-z0-9]", "", r["abbr"]).upper(), r["expansion"].lower().split()) for r in cur.fetchall()]
    return _cache["aliases"], _cache["abbr"]


def _like(s):
    return "%" + s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"


def _where(cur, q, f, exclude=None):
    aliases, abbr = _lookups(cur)
    sql, args = ["p.status = 'published'"], []
    q = (q or "").strip()
    if q:
        qn = nz.norm_part(q)
        tokens = [t for t in re.findall(r"[A-Za-z0-9./&+-]+", q.lower()) if t not in ("for", "of", "the")]
        parts = []
        if len(qn) >= 3 and any(ch.isdigit() for ch in qn):
            parts.append("p.part_no_norm like %s")
            args.append(_like(qn)[1:] if len(qn) < 5 else _like(qn))  # short codes: prefix only
            parts.append("exists (select 1 from cross_refs c where c.product_id = p.id and c.ref_part_no_norm like %s)")
            args.append(_like(qn)[1:])  # OEM / competitor numbers: prefix match
        tok_sql = []
        if not tokens and not parts:
            sql.append("false")           # only symbols ('%', '_', quotes): nothing to look for, so nothing matches
        for t in tokens:
            alts, a = ["(" + HAY + ") ilike %s"], [_like(t)]
            if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):     # brake pads -> brake pad
                alts.append("(" + HAY + ") ilike %s"); a.append(_like(t[:-1]))
            make = aliases.get(t.upper().strip("."))
            if make:
                alts.append("p.oem_name ilike %s"); a.append(_like(make))
            for ab, words in abbr:
                if t in words:  # "lamp" -> also rows that only say TL / HL / FL
                    alts.append("(" + HAY + r") ~* %s")  # W.R. / WR / W R written with or without dots
                    a.append(r"(?<![A-Za-z0-9])" + r"\.?".join(re.escape(ch) for ch in ab) + r"\.?(?![A-Za-z0-9])")
                elif t.replace(".", "").upper() == ab:  # "hl" -> also rows that spell it out, or write it as HL / H.L.
                    alts.append("(" + HAY + ") ilike %s"); a.append(_like(" ".join(words)))
                    alts.append("(" + HAY + r") ~* %s")
                    a.append(r"(?<![A-Za-z0-9])" + r"\.?".join(re.escape(ch) for ch in ab) + r"\.?(?![A-Za-z0-9])")
            tok_sql.append("(" + " or ".join(alts) + ")")
            args.extend(a)
        if tok_sql:
            parts.append("(" + " and ".join(tok_sql) + ")")
        if parts:
            sql.append("(" + " or ".join(parts) + ")")
    for key, col in (("brand", "b.slug"), ("segment", "p.segment"), ("category", "p.category")):
        if f.get(key) and exclude != key:
            sql.append(f"{col} = %s"); args.append(f[key])
    if f.get("make") and exclude != "make":
        sql.append("p.oem_name ilike %s"); args.append(_like(f["make"]))
    if f.get("min_price") not in (None, ""):
        sql.append("p.mrp >= %s"); args.append(f["min_price"])
    if f.get("max_price") not in (None, ""):
        sql.append("p.mrp <= %s"); args.append(f["max_price"])
    return " and ".join(sql), args


CARD = """p.id, p.part_no, p.variant_label, p.description, p.application, p.oem_name, p.oem_raw, p.category, p.segment,
          p.mrp, p.price_basis, p.image_url, p.unit, p.pack_qty, b.name as brand, b.slug as brand_slug"""


def _vocab(cur):
    """Words that occur in the catalogue (with counts), for spelling help. Rebuilt every 10 minutes."""
    if time.time() - _cache.get("vocab_at", 0) > 600:
        cur.execute("select w, count(*) n from (select lower(regexp_split_to_table(text, '[^A-Za-z]+')) w from product_search) s "
                    "where length(w) >= 3 group by w")
        _cache["vocab"] = {r["w"]: r["n"] for r in cur.fetchall()}
        _cache["vocab_at"] = time.time()
    return _cache["vocab"]


def _correct(cur, q):
    """Zero results: fix one-letter typos ('vlave' -> 'valve') and run-together words ('waterpump' -> 'water pump')."""
    vocab = _vocab(cur)
    out = []
    for t in re.findall(r"[A-Za-z0-9./&+-]+", q.lower()):
        if t in vocab or any(ch.isdigit() for ch in t) or len(t) < 2:
            out.append(t)
            continue
        split = next((f"{t[:i]} {t[i:]}" for i in range(3, len(t) - 2) if t[:i] in vocab and t[i:] in vocab), None)
        if split:
            out.append(split)
            continue
        near = difflib.get_close_matches(t, [w for w in vocab if abs(len(w) - len(t)) <= 2 and w[0] == t[0]], n=3, cutoff=0.8 if len(t) > 3 else 0.75)
        out.append(max(near, key=lambda w: vocab[w]) if near else t)
    return " ".join(out)


def search(conn, q="", filters=None, limit=30, offset=0, _retry=True):
    r = _search(conn, q, filters, limit, offset)
    if r["total"] == 0 and _retry and (q or "").strip():
        fixed = _correct(cursor(conn), q)
        if fixed != " ".join(re.findall(r"[A-Za-z0-9./&+-]+", q.lower())):
            r2 = _search(conn, fixed, filters, limit, offset)
            if r2["total"]:
                r2["corrected_from"], r2["query"] = q, fixed
                return r2
    return r


def _search(conn, q="", filters=None, limit=30, offset=0):
    t0 = time.time()
    f = filters or {}
    cur = cursor(conn)
    where, args = _where(cur, q, f)
    qn = nz.norm_part(q or "")
    rank = "4"
    rank_args = []
    if (q or "").strip():
        toks = [t for t in re.findall(r"[A-Za-z0-9./&+-]+", q.lower()) if t not in ("for", "of", "the")]
        literal = " and ".join(f"({HAY}) ilike %s" for _ in toks) or "false"  # every word typed appears as typed
        stem = [t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t for t in toks]
        rank = ("case when p.part_no_norm = %s then 0 when p.part_no_norm like %s then 1 when p.part_no_norm like %s then 2 "
                f"when p.description ilike %s then 3 when {literal} then 4 else 5 end")        # exact phrase beats scattered words
        rank_args = [qn, _like(qn)[1:], _like(qn), _like(" ".join(stem))] + [_like(t) for t in toks]
    cur.execute(f"select count(*) n {FROM} where {where}", args)
    total = cur.fetchone()["n"]
    cur.execute(f"select {CARD} {FROM} where {where} order by {rank}, p.mrp is null, b.name, p.part_no, p.variant_label "
                f"limit %s offset %s", args + rank_args + [limit, offset])
    hits = cur.fetchall()
    for h in hits:
        h["id"] = str(h["id"]); h["mrp"] = float(h["mrp"]) if h["mrp"] is not None else None

    facets = {}
    for name, expr in (("brand", "b.slug, b.name"), ("segment", "p.segment, p.segment"), ("category", "p.category, p.category")):
        w, a = _where(cur, q, f, exclude=name)
        key = expr.split(",")[0]
        cur.execute(f"select {expr.split(',')[0]} as value, {expr.split(',')[1]} as label, count(*) n {FROM} where {w} and {key} is not null "
                    f"group by 1, 2 order by n desc limit 40", a)
        facets[name] = cur.fetchall()
    w, a = _where(cur, q, f, exclude="make")
    cur.execute(f"select m as value, m as label, count(*) n from (select unnest(string_to_array(p.oem_name, ' / ')) m {FROM} "
                f"where {w}) s where m is not null group by 1 order by n desc limit 30", a)
    facets["make"] = cur.fetchall()
    return {"total": total, "hits": hits, "facets": facets, "ms": round((time.time() - t0) * 1000)}


def product(conn, pid):
    cur = cursor(conn)
    cur.execute(f"select p.*, b.name as brand, b.slug as brand_slug {FROM} where p.id = %s and p.status = 'published'", (pid,))
    p = cur.fetchone()
    if not p:
        return None
    for k in ("id", "brand_id", "first_batch_id", "last_batch_id"):
        p[k] = str(p[k]) if p.get(k) else None
    for k in ("mrp", "mrp_prev", "gst_pct"):
        p[k] = float(p[k]) if p[k] is not None else None
    p["created_at"] = p["updated_at"] = None
    p.pop("locked_fields", None)
    cur.execute("select ref_type, ref_brand, ref_part_no, note from cross_refs where product_id = %s order by ref_type, ref_part_no",
                (p["id"],))
    p["cross_refs"] = cur.fetchall()
    cur.execute("select url, kind from product_images where product_id = %s order by sort, url", (p["id"],))
    p["images"] = ([{"url": p["image_url"], "kind": "photo"}] if p.get("image_url") else []) + cur.fetchall()
    p["fitments"] = []
    cur.execute("select make, model, variant, year_from, year_to, engine, note from fitments where product_id = %s order by make, model", (p["id"],))
    p["fitments"] = cur.fetchall()
    cur.execute(f"select {CARD} {FROM} where p.brand_id = %s and p.part_no_norm = %s and p.id <> %s and p.status='published' "
                "order by p.variant_label", (p["brand_id"], p["part_no_norm"], p["id"]))
    p["variants"] = _clean(cur.fetchall())
    cur.execute(f"select {CARD} {FROM} where p.category = %s and p.oem_name is not distinct from %s and p.id <> %s "
                "and p.status='published' order by p.mrp limit 8", (p["category"], p["oem_name"], p["id"]))
    p["related"] = _clean(cur.fetchall())
    cur.execute(f"select {CARD} {FROM} where p.part_no_norm = %s and p.brand_id <> %s and p.status='published' limit 8",
                (p["part_no_norm"], p["brand_id"]))
    p["same_number_elsewhere"] = _clean(cur.fetchall())
    return p


def _clean(rows):
    for h in rows:
        h["id"] = str(h["id"]); h["mrp"] = float(h["mrp"]) if h["mrp"] is not None else None
    return rows
