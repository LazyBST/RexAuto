"""plan (preview) and apply. The preview and the apply use the exact same plan function."""
from decimal import Decimal

import psycopg2.extras as ex

from . import audit
from .db import cursor
from . import normalize as nz
from .profiles.base import EXTRA_FIELDS, HARD_FLAGS, PRODUCT_FIELDS

LOCK_KEY = 7001  # serialises every writer of `products` (apply, resync, delete)
DEFAULTS = {"price_basis": "unknown", "variant_label": "", "needs_review": False}
POSITION_FIELDS = {"source_page", "source_row"}
COMPARE_FIELDS = sorted(PRODUCT_FIELDS - POSITION_FIELDS)
MRP_SWING = 0.40


def _same(a, b):
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return Decimal(str(a)) == Decimal(str(b))
    return a == b


STATE_SQL = ("to_jsonb(p.*) || jsonb_build_object('cross_refs', coalesce((select jsonb_agg(to_jsonb(c.*) - 'product_id' "
             "order by c.ref_type, c.ref_part_no_norm, c.ref_brand, c.id) from cross_refs c where c.product_id = p.id), '[]'::jsonb))")


def fetch_state(cur, pid):
    """The product row plus its cross refs, as one jsonb document (what change_log stores)."""
    cur.execute(f"select {STATE_SQL} as j from products p where p.id = %s", (pid,))
    r = cur.fetchone()
    return r["j"] if r else None


def _ref_key(r):
    return (r["ref_type"], (r.get("ref_brand") or ""), nz.norm_part(r["ref_part_no"]))


def normalise_refs(refs):
    out, seen = [], set()
    for r in refs or []:
        if not nz.norm_part(r.get("ref_part_no")):
            continue
        r = {"ref_type": r["ref_type"], "ref_brand": r.get("ref_brand"), "ref_part_no": r["ref_part_no"].strip(), "note": r.get("note")}
        if _ref_key(r) not in seen:
            seen.add(_ref_key(r))
            out.append(r)
    return out


def write_refs(cur, pid, refs):
    cur.execute("delete from cross_refs where product_id = %s", (pid,))
    for r in refs:
        cur.execute("insert into cross_refs(product_id, ref_type, ref_brand, ref_part_no, ref_part_no_norm, note) "
                    "values (%s,%s,%s,%s,%s,%s)", (pid, r["ref_type"], r.get("ref_brand"), r["ref_part_no"],
                                                    nz.norm_part(r["ref_part_no"]), r.get("note")))


def restore_refs(cur, pid, refs):
    """Put back the exact rows (same ids) a change_log entry recorded."""
    cur.execute("delete from cross_refs where product_id = %s", (pid,))
    if refs:
        cur.execute("insert into cross_refs select * from jsonb_populate_recordset(null::cross_refs, %s)",
                    (ex.Json([{**r, "product_id": str(pid)} for r in refs]),))


def lock(cur):
    cur.execute("select pg_advisory_xact_lock(%s)", (LOCK_KEY,))


def compute_plan(cur, batch_id, remove_missing=False):
    cur.execute("select brand_id from import_batches where id=%s", (batch_id,))
    brand_id = cur.fetchone()["brand_id"]
    cur.execute(f"select {STATE_SQL} as j from products p where brand_id=%s", (brand_id,))
    existing = {(r["j"]["part_no_norm"], r["j"]["variant_label"]): r["j"] for r in cur.fetchall()}
    cur.execute("select id, page, row_no, data, flags from batch_rows where batch_id=%s order by id", (batch_id,))
    plan = {"inserts": [], "updates": [], "unchanged": 0, "removals": [], "held": [], "flagged": 0, "unmatched": []}
    partial_batch = False
    in_file = set()
    for r in cur.fetchall():
        if r["flags"]:
            plan["flagged"] += 1
        if HARD_FLAGS & set(r["flags"]):
            plan["held"].append({"page": r["page"], "row_no": r["row_no"], "flags": r["flags"],
                                 "part_no": r["data"].get("part_no")})
            continue
        extra = set(r["data"]) - PRODUCT_FIELDS - EXTRA_FIELDS
        if extra:
            raise ValueError(f"staging row {r['id']} holds non-whitelisted fields {sorted(extra)}")
        partial = bool(r["data"].get("update_only"))
        partial_batch = partial_batch or partial
        if partial:
            d = {k: v for k, v in r["data"].items() if k != "update_only"}
        else:
            d = {**{k: None for k in PRODUCT_FIELDS}, **DEFAULTS, **r["data"]}
        if "cross_refs" in d:
            d["cross_refs"] = normalise_refs(d["cross_refs"])
        key = (d["part_no_norm"], d["variant_label"])
        in_file.add(key)
        cur_row = existing.get(key)
        if cur_row is None:
            if partial:
                plan["unmatched"].append({"part_no": d.get("part_no") or d["part_no_norm"], "page": r["page"]})
                continue
            plan["inserts"].append({"row": d, "flags": r["flags"]})
            continue
        changes = {f: [cur_row[f], d[f]] for f in COMPARE_FIELDS if f in d and not _same(cur_row[f], d[f])}
        if "cross_refs" in d and {_ref_key(r) for r in cur_row["cross_refs"]} != {_ref_key(r) for r in d["cross_refs"]}:
            changes["cross_refs"] = [[r["ref_part_no"] for r in cur_row["cross_refs"]], [r["ref_part_no"] for r in d["cross_refs"]]]
        if not changes:
            plan["unchanged"] += 1
            continue
        flags = list(r["flags"])
        old, new = cur_row["mrp"], d.get("mrp")
        if old and new and abs(new - old) / old > MRP_SWING:
            flags.append("mrp_swing")
        plan["updates"].append({"product_id": cur_row["id"], "before": cur_row, "row": d, "changes": changes,
                                "flags": flags})
    if remove_missing and not partial_batch:
        for key, j in existing.items():
            if key not in in_file and j["last_batch_id"] == str(batch_id):
                plan["removals"].append({"product_id": j["id"], "before": j})
    return plan


def summarise(plan, sample=25):
    return {
        "insert": len(plan["inserts"]), "update": len(plan["updates"]), "unchanged": plan["unchanged"],
        "remove": len(plan["removals"]), "held_not_applied": len(plan["held"]), "flagged": plan["flagged"],
        "unmatched": len(plan["unmatched"]), "sample_unmatched": [u["part_no"] for u in plan["unmatched"][:25]],
        "sample_inserts": [i["row"]["part_no"] for i in plan["inserts"][:sample]],
        "sample_updates": [{"part_no": u["row"].get("part_no") or u["row"]["part_no_norm"], "changes": u["changes"], "flags": u["flags"]}
                           for u in plan["updates"][:sample]],
        "sample_removals": [r["before"]["part_no"] for r in plan["removals"][:sample]],
        "mrp_swings": sum(1 for u in plan["updates"] if "mrp_swing" in u["flags"]),
    }


def preview(conn, batch_id, remove_missing=False):
    return summarise(compute_plan(cursor(conn), batch_id, remove_missing))


def _cols(d):
    return [c for c in sorted(PRODUCT_FIELDS) if c in d]  # cross_refs is not a column; it is written separately


def apply_batch(conn, batch_id, actor, run_type=None, remove_missing=False):
    cur = cursor(conn)
    cur.execute("select * from import_batches where id=%s", (batch_id,))
    b = cur.fetchone()
    if b["status"] not in ("needs_review", "ready"):
        raise SystemExit(f"batch is {b['status']}; parse it first (needs_review/ready) before applying")
    if run_type is None:
        cur.execute("select 1 from sync_runs where batch_id=%s and status='done' and run_type in ('initial','resync')",
                    (batch_id,))
        run_type = "resync" if cur.fetchone() else "initial"
    try:
        lock(cur)
        plan = compute_plan(cur, batch_id, remove_missing)
        cur.execute("""insert into sync_runs(batch_id, run_type, parser_version, actor) values (%s,%s,%s,%s)
                       returning id""", (batch_id, run_type, b["parser_version"], actor))
        run_id = cur.fetchone()["id"]
        touched = []

        def log_change(pid, action, before, after):
            cur.execute("insert into change_log(run_id, batch_id, product_id, action, before, after) "
                        "values (%s,%s,%s,%s,%s,%s)", (run_id, batch_id, pid, action, ex.Json(before), ex.Json(after)))

        for item in plan["inserts"]:
            d = item["row"]
            cols = _cols(d)
            cur.execute(
                f"insert into products(brand_id, first_batch_id, last_batch_id, {', '.join(cols)}) "
                f"values (%s,%s,%s,{', '.join(['%s'] * len(cols))}) returning to_jsonb(products.*) as j",
                [b["brand_id"], batch_id, batch_id] + [d[c] for c in cols])
            j = cur.fetchone()["j"]
            if "cross_refs" in d:
                write_refs(cur, j["id"], d["cross_refs"])
            j = fetch_state(cur, j["id"])
            log_change(j["id"], "insert", None, j)
            touched.append(j["id"])
        for item in plan["updates"]:
            d = item["row"]
            cols = _cols(d)
            cur.execute(
                f"update products set {', '.join(c + ' = %s' for c in cols)}, last_batch_id = %s, updated_at = now() "
                f"where id = %s returning to_jsonb(products.*) as j",
                [d[c] for c in cols] + [batch_id, item["product_id"]])
            if "cross_refs" in d and "cross_refs" in item["changes"]:
                write_refs(cur, item["product_id"], d["cross_refs"])
            j = fetch_state(cur, item["product_id"])
            log_change(item["product_id"], "update", item["before"], j)
            touched.append(item["product_id"])
        for item in plan["removals"]:
            cur.execute("delete from products where id = %s", (item["product_id"],))
            log_change(item["product_id"], "delete", item["before"], None)
            touched.append(item["product_id"])

        n_ins, n_upd, n_rem = len(plan["inserts"]), len(plan["updates"]), len(plan["removals"])
        cur.execute("""update sync_runs set inserted=%s, updated=%s, unchanged=%s, removed=%s, flagged=%s,
                           finished_at=now(), status='done' where id=%s""",
                    (n_ins, n_upd, plan["unchanged"], n_rem, plan["flagged"], run_id))
        cur.execute("""update import_batches set status='applied', rows_inserted=%s, rows_updated=%s,
                           rows_unchanged=%s, rows_removed=%s where id=%s""",
                    (n_ins, n_upd, plan["unchanged"], n_rem, batch_id))
        audit.log(cur, actor, "batch_applied" if run_type == "initial" else "resync_applied", batch_id,
                  run_id=str(run_id), inserted=n_ins, updated=n_upd, unchanged=plan["unchanged"], removed=n_rem,
                  held=len(plan["held"]))
        conn.commit()
    except BaseException as e:
        conn.rollback()
        cur = cursor(conn)
        cur.execute("update import_batches set status='failed', notes=%s where id=%s", (f"apply failed: {e}", batch_id))
        audit.log(cur, actor, "apply_failed", batch_id, error=str(e))
        conn.commit()
        raise
    reindex(conn, batch_id, actor, touched)
    return {"run_id": run_id, "inserted": n_ins, "updated": n_upd, "unchanged": plan["unchanged"], "removed": n_rem,
            "held": len(plan["held"]), "unmatched": len(plan["unmatched"])}


SEARCH_TEXT_SQL = """
insert into product_search(product_id, text)
select p.id, concat_ws(' ', p.part_no, p.description, p.application, p.oem_name, p.oem_raw, p.category, b.name, p.variant_label,
       (select string_agg(c.ref_part_no, ' ') from cross_refs c where c.product_id = p.id))
from products p join brands b on b.id = p.brand_id %s
on conflict (product_id) do update set text = excluded.text"""


def refresh_search_text(cur, product_ids=None):
    """Rebuild the search text for the given products (all when None). Products that no longer exist drop out by cascade."""
    if product_ids is None:
        cur.execute(SEARCH_TEXT_SQL % "")
    elif product_ids:
        cur.execute(SEARCH_TEXT_SQL % "where p.id = any(%s::uuid[])", ([str(i) for i in product_ids],))


def reindex(conn, batch_id, actor, product_ids):
    from . import index
    cur = cursor(conn)
    refresh_search_text(cur, product_ids)
    conn.commit()
    try:
        res = index.sync(conn, product_ids)
    except Exception as e:  # DB is the source of truth; a search outage must not undo a committed apply
        res = {"error": str(e)}
    audit.log(cur, actor, "search_reindexed", batch_id, products=len(product_ids), **res)
    conn.commit()
    return res
