"""Load every source listed in data/config/sources.csv into the configured database (DATABASE_URL / Supabase), then verify.
Re-running is safe: a file already applied for the brand is skipped, so an interrupted load can simply be started again."""
import re
import time
from pathlib import Path

from . import apply as ap
from . import normalize as nz
from . import parse, report
from .db import cursor
from .rules import bad_name
from .snapshot import snapshot


def sources():
    return nz.load_csv("sources.csv")


def load_all(conn, folder, actor, only=None):
    folder = Path(folder).expanduser()
    done = []
    for s in sources():
        if only and s["brand_slug"] not in only and s["profile"] not in only:
            continue
        path = folder / s["filename"]
        if not path.exists():
            raise SystemExit(f"missing source file: {path}")
        cur = cursor(conn)
        cur.execute("""select b.id from import_batches b join brands br on br.id = b.brand_id
                       where br.slug=%s and b.profile=%s and b.original_filename=%s and b.status='applied'""",
                    (s["brand_slug"], s["profile"], s["filename"]))
        if cur.fetchone():
            print(f"skip   {s['brand_slug']:<18}{s['profile']:<16}{s['filename']} (already applied)")
            continue
        t0 = time.time()
        up = parse.upload_batch(conn, s["brand_slug"], s["profile"], path, actor)
        bid = up["batch_id"]
        res = parse.parse_batch(conn, bid, actor)
        if res["rows"] < int(s["min_rows"]):
            raise SystemExit(f"{s['filename']}: parsed {res['rows']} rows, expected at least {s['min_rows']}; not applying")
        out = ap.apply_batch(conn, bid, actor)
        print(f"loaded {s['brand_slug']:<18}{s['profile']:<16}rows={res['rows']:<5} +{out['inserted']} ~{out['updated']} "
              f"held={out['held']} unmatched={out['unmatched']}  ({time.time() - t0:.0f}s)")
        done.append((s, bid))
    return done


def verify(conn):
    """Post-load checks; returns [(name, ok, detail)]."""
    cur = cursor(conn)
    out = []

    def check(name, ok, detail=""):
        out.append((name, bool(ok), detail))

    cur.execute("select b.slug, count(p.id) n from brands b left join products p on p.brand_id = b.id group by 1")
    per = {r["slug"]: r["n"] for r in cur.fetchall()}
    for s in sources():
        if s["profile"] == "meko_catalogue":
            continue
        check(f"{s['brand_slug']} products >= {s['min_rows']}", per.get(s["brand_slug"], 0) >= int(s["min_rows"]) - 20,
              f"{per.get(s['brand_slug'], 0)} products")
    cur.execute("select count(*) n from products where part_no is null or part_no='' or brand_id is null")
    check("every product has a part number and brand", cur.fetchone()["n"] == 0)
    cur.execute("select count(*) n from product_search s right join products p on p.id=s.product_id where s.product_id is null")
    check("search text exists for every product", cur.fetchone()["n"] == 0)
    cur.execute("select count(*) n from products where variant_label <> btrim(variant_label)")
    check("variant labels trimmed", cur.fetchone()["n"] == 0)
    cur.execute("select relname from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname=current_schema() "
                "and relkind='r' and not relrowsecurity and relname <> 'schema_migrations'")
    check("row-level security on every table", not cur.fetchall(), "")
    cur.execute("select table_name, column_name from information_schema.columns where table_schema=current_schema()")
    bad = [(t, c) for t, c in ((r["table_name"], r["column_name"]) for r in cur.fetchall()) if bad_name(c)]
    check("no discount / dealer-rate column exists", not bad, str(bad))
    cur.execute("select count(*) n from import_batches where status='applied' and not redacted and profile in ('uno_minda','pensol')")
    check("archived originals with a discount/dealer column are redacted", cur.fetchone()["n"] == 0)
    cur.execute("select count(*) n from products where price_effective_from is null and mrp is not null")
    check("every priced product has its price-list date", cur.fetchone()["n"] == 0, "")
    cur.execute("select count(*) n from products where price_basis = 'unknown'")
    n = cur.fetchone()["n"]
    check("price basis (incl./excl. GST) known for every product", n == 0, f"{n} products unknown; set data/config/price_basis.csv")
    snap = snapshot(conn)
    check("catalogue fingerprint computed", True, f"{snap['sha256'][:12]} {snap['counts']}")
    return out
