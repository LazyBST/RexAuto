"""Child rows the batch engine manages per product: cross references, extra images, vehicle fitments.

A profile that emits one of these keys owns the product's whole set of that kind (rows are compared by identity, replaced
when the set differs, and restored byte-for-byte by delete). A profile that does not emit the key leaves the rows alone.
Everything is set-based (one statement per page of products), because round trips dominate when the database is remote.
"""
import psycopg2.extras as ex

from . import normalize as nz

CHILDREN = {
    "cross_refs": {"table": "cross_refs",
                   "cols": ["ref_type", "ref_brand", "ref_part_no", "ref_part_no_norm", "note", "direction"],
                   "order": "ref_type, ref_part_no_norm, ref_brand, id"},
    "images": {"table": "product_images", "cols": ["url", "kind", "sort", "caption"], "order": "sort, url, id"},
    "fitments": {"table": "fitments", "cols": ["make", "model", "variant", "year_from", "year_to", "engine", "note"],
                 "order": "make, model, year_from, id"},
}

def _agg(v):
    order = ", ".join("c." + o.strip() for o in v["order"].split(","))
    return (f"coalesce((select jsonb_agg(to_jsonb(c.*) - 'product_id' order by {order}) "
            f"from {v['table']} c where c.product_id = p.id), '[]'::jsonb)")


# one jsonb document per product: its row plus all its child rows (this is what change_log stores and rollback compares)
STATE_SQL = "to_jsonb(p.*) || jsonb_build_object(" + ", ".join(f"'{k}', {_agg(v)}" for k, v in CHILDREN.items()) + ")"

CHUNK = 400


def chunks(seq, n=CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def identity(kind, r):
    """What makes two child rows 'the same row' when the file is compared with the database."""
    if kind == "cross_refs":
        return (r["ref_type"], r.get("ref_brand") or "", nz.norm_part(r["ref_part_no"]), r.get("direction") or "")
    if kind == "images":
        return (r["url"], r.get("kind") or "photo", r.get("sort") or 0)
    return (r["make"], r.get("model") or "", r.get("variant") or "", r.get("year_from"), r.get("year_to"), r.get("engine") or "")


def label(kind, r):
    return r.get("ref_part_no") or r.get("url") or " ".join(x for x in (r.get("make"), r.get("model")) if x)


def normalise(kind, items):
    """Trim, drop empties, fill missing keys with None, drop duplicates (first wins)."""
    keys = CHILDREN[kind]["cols"]
    out, seen = [], set()
    for r in items or []:
        r = {k: (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
        if kind == "cross_refs" and not nz.norm_part(r.get("ref_part_no")):
            continue
        if kind == "images" and not r.get("url"):
            continue
        if kind == "fitments" and not r.get("make"):
            continue
        row = {k: r.get(k) for k in keys if k != "ref_part_no_norm"}
        if kind == "images":
            row["kind"], row["sort"] = row["kind"] or "photo", row["sort"] or 0
        if identity(kind, row) not in seen:
            seen.add(identity(kind, row))
            out.append(row)
    return out


def differs(kind, existing, new):
    return {identity(kind, r) for r in existing} != {identity(kind, r) for r in new}


def write(cur, kind, rows_by_pid):
    """Replace the children of the given products with the given rows (all products in one delete + one insert)."""
    spec = CHILDREN[kind]
    pids = [str(p) for p in rows_by_pid]
    if not pids:
        return
    for part in chunks(pids):
        cur.execute(f"delete from {spec['table']} where product_id = any(%s::uuid[])", (part,))
    cols = spec["cols"]
    values = []
    for pid, rows in rows_by_pid.items():
        for r in rows:
            r = dict(r)
            if kind == "cross_refs":
                r["ref_part_no_norm"] = nz.norm_part(r["ref_part_no"])
            values.append((str(pid),) + tuple(r.get(c) for c in cols))
    if values:
        ex.execute_values(cur, f"insert into {spec['table']} (product_id, {', '.join(cols)}) values %s", values, page_size=1000)


def restore(cur, kind, rows_by_pid):
    """Put back the exact rows (same ids) a change_log entry recorded."""
    spec = CHILDREN[kind]
    pids = [str(p) for p in rows_by_pid]
    if not pids:
        return
    for part in chunks(pids):
        cur.execute(f"delete from {spec['table']} where product_id = any(%s::uuid[])", (part,))
    flat = [{**r, "product_id": str(pid)} for pid, rows in rows_by_pid.items() for r in rows]
    for part in chunks(flat):
        cur.execute(f"insert into {spec['table']} select * from jsonb_populate_recordset(null::{spec['table']}, %s)", (ex.Json(part),))
