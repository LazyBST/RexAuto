"""plan (preview) and apply. The preview and the apply use the exact same plan function.

Writes are set-based (execute_values / execute_batch / one statement per page of products): against a hosted database a
round trip per row would make a 100k-product load take hours."""
import uuid
from decimal import Decimal

import psycopg2.extras as ex

from . import audit
from . import children as kids
from .children import CHILDREN, STATE_SQL
from .db import cursor
from .profiles.base import EXTRA_FIELDS, HARD_FLAGS, PRODUCT_FIELDS

LOCK_KEY = 7001  # serialises every writer of `products` (apply, resync, delete)
DEFAULTS = {"variant_label": "", "needs_review": False, "attributes": {}}
POSITION_FIELDS = {"source_page", "source_row"}
COMPARE_FIELDS = sorted(PRODUCT_FIELDS - POSITION_FIELDS)
JSON_COLS = {"attributes"}
MRP_SWING = 0.40


def _same(a, b):
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return Decimal(str(a)) == Decimal(str(b))
    return a == b


def fetch_states(cur, pids):
    """{product id (str): state document} for the products that exist."""
    out = {}
    for part in kids.chunks([str(p) for p in pids], 2000):
        cur.execute(f"select p.id, {STATE_SQL} as j from products p where p.id = any(%s::uuid[])", (part,))
        for r in cur.fetchall():
            out[str(r["id"])] = r["j"]
    return out


def lock(cur):
    cur.execute("select pg_advisory_xact_lock(%s)", (LOCK_KEY,))


def jsonb_or_null(v):
    return ex.Json(v) if v is not None else None


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
        for kind in CHILDREN:
            if kind in d:
                d[kind] = kids.normalise(kind, d[kind])
        key = (d["part_no_norm"], d["variant_label"])
        in_file.add(key)
        cur_row = existing.get(key)
        if cur_row is None:
            if partial:
                plan["unmatched"].append({"part_no": d.get("part_no") or d["part_no_norm"], "page": r["page"]})
                continue
            plan["inserts"].append({"row": d, "flags": r["flags"]})
            continue
        if partial and "attributes" in d:     # an enrichment adds attribute keys; it never wipes the ones already there
            d["attributes"] = {**(cur_row.get("attributes") or {}), **d["attributes"]}
        locked = set(cur_row.get("locked_fields") or [])  # fields edited by hand: the file must not overwrite them
        if locked:
            d = {k: v for k, v in d.items() if k not in locked}
        changes = {f: [cur_row[f], d[f]] for f in COMPARE_FIELDS if f in d and not _same(cur_row[f], d[f])}
        for kind in CHILDREN:
            if kind in d and kids.differs(kind, cur_row[kind], d[kind]):
                changes[kind] = [[kids.label(kind, x) for x in cur_row[kind]], [kids.label(kind, x) for x in d[kind]]]
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
    return tuple(c for c in sorted(PRODUCT_FIELDS) if c in d)  # child keys are not columns; they are written separately


def _val(col, v):
    return ex.Json(v if v is not None else {}) if col in JSON_COLS else v


def apply_batch(conn, batch_id, actor, run_type=None, remove_missing=False):
    cur = cursor(conn)
    cur.execute("select * from import_batches where id=%s", (batch_id,))
    b = cur.fetchone()
    if b is None:
        raise SystemExit("no such batch")
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
        inserts, updates, removals = plan["inserts"], plan["updates"], plan["removals"]
        kid_rows = {k: {} for k in CHILDREN}          # kind -> {product id: rows to write}

        # inserts: ids are made here so no row needs RETURNING; one statement per page, grouped by column set
        new_ids, by_cols = [], {}
        for item in inserts:
            pid = str(uuid.uuid4())
            new_ids.append(pid)
            by_cols.setdefault((_cols(item["row"]), "mrp" in item["row"]), []).append((pid, item["row"]))
            for k in CHILDREN:
                if k in item["row"]:
                    kid_rows[k][pid] = item["row"][k]
        for (cols, priced), items in by_cols.items():     # priced rows remember which file their MRP came from
            head = "id, brand_id, first_batch_id, last_batch_id" + (", mrp_batch_id" if priced else "")
            ex.execute_values(
                cur, f"insert into products ({head}, {', '.join(cols)}) values %s",
                [(pid, b["brand_id"], batch_id, batch_id) + ((batch_id,) if priced else ()) + tuple(_val(c, d[c]) for c in cols)
                 for pid, d in items], page_size=500)

        # updates: grouped by column set, pipelined in pages
        by_cols = {}
        for item in updates:
            by_cols.setdefault((_cols(item["row"]), "mrp" in item["changes"]), []).append(item)
            for k in CHILDREN:
                if k in item["changes"]:
                    kid_rows[k][str(item["product_id"])] = item["row"][k]
        for (cols, mrp_changed), items in by_cols.items():   # a changed MRP now comes from this batch's file
            sql = (f"update products set {', '.join(c + ' = %s' for c in cols)}, last_batch_id = %s, updated_at = now()"
                   f"{', mrp_batch_id = %s' if mrp_changed else ''} where id = %s")
            ex.execute_batch(cur, sql, [[_val(c, it["row"][c]) for c in cols] + [batch_id] + ([batch_id] if mrp_changed else [])
                                        + [str(it["product_id"])] for it in items], page_size=500)
        for k, rows in kid_rows.items():
            kids.write(cur, k, rows)

        for part in kids.chunks([str(r["product_id"]) for r in removals], 2000):
            cur.execute("delete from products where id = any(%s::uuid[])", (part,))

        # history: one state read for everything written, one insert per page of log rows
        states = fetch_states(cur, new_ids + [str(u["product_id"]) for u in updates])
        log = [(run_id, batch_id, pid, "insert", None, jsonb_or_null(states[pid])) for pid in new_ids]
        log += [(run_id, batch_id, str(u["product_id"]), "update", jsonb_or_null(u["before"]),
                 jsonb_or_null(states[str(u["product_id"])])) for u in updates]
        log += [(run_id, batch_id, str(r["product_id"]), "delete", jsonb_or_null(r["before"]), None) for r in removals]
        ex.execute_values(cur, "insert into change_log(run_id, batch_id, product_id, action, before, after) values %s", log,
                          page_size=500)
        touched = new_ids + [str(u["product_id"]) for u in updates] + [str(r["product_id"]) for r in removals]

        n_ins, n_upd, n_rem = len(inserts), len(updates), len(removals)
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
       (select string_agg(c.ref_part_no, ' ') from cross_refs c where c.product_id = p.id),
       (select string_agg(concat_ws(' ', f.make, f.model, f.variant, f.engine), ' ') from fitments f where f.product_id = p.id))
from products p join brands b on b.id = p.brand_id %s
on conflict (product_id) do update set text = excluded.text"""


def refresh_search_text(cur, product_ids=None):
    """Rebuild the search text for the given products (all when None). Products that no longer exist drop out by cascade."""
    if product_ids is None:
        cur.execute(SEARCH_TEXT_SQL % "")
    else:
        for part in kids.chunks([str(i) for i in product_ids], 2000):
            cur.execute(SEARCH_TEXT_SQL % "where p.id = any(%s::uuid[])", (part,))


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
