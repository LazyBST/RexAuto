"""Delete ("shred") a batch: undo everything it contributed, keep the history. Set-based, like apply."""
import psycopg2.extras as ex

from . import audit
from . import children as kids
from .apply import apply_batch, fetch_states, jsonb_or_null, lock, reindex  # noqa: F401
from .children import CHILDREN
from .db import cursor
from .storage import get_storage


def _chains(cur, batch_id):
    """Per product: the batch's first change (-> state to restore) and last change (-> state we expect now)."""
    cur.execute("""select c.* from change_log c join sync_runs r on r.id = c.run_id
                   where c.batch_id=%s and r.run_type in ('initial','resync') order by c.id""", (batch_id,))
    chains = {}
    for c in cur.fetchall():
        e = chains.setdefault(str(c["product_id"]), {"first": c, "last": c})
        e["last"] = c
    return chains


def _classify(chains, current, force):
    out = {"delete": [], "restore": [], "reinsert": [], "already_gone": 0, "conflicts": []}
    for pid, ch in chains.items():
        now, expected, first = current.get(pid), ch["last"]["after"], ch["first"]
        if now != expected:
            if now is None and first["action"] == "insert":
                out["already_gone"] += 1
                continue
            out["conflicts"].append({"product_id": pid, "part_no": (now or expected or first["before"] or {}).get("part_no"),
                                     "reason": "removed since" if now is None else "changed since this batch wrote it"})
            if not force:
                continue
        target = first["before"]  # None when this batch inserted the product
        if target is None:
            if now is not None:
                out["delete"].append((pid, now))
        elif now is None:
            out["reinsert"].append((pid, target))
        else:
            out["restore"].append((pid, now, target))
    return out


def delete_preview(conn, batch_id):
    cur = cursor(conn)
    cur.execute("select * from import_batches where id=%s", (batch_id,))
    b = cur.fetchone()
    if b is None:
        raise SystemExit("no such batch")
    chains = _chains(cur, batch_id)
    c = _classify(chains, fetch_states(cur, chains), force=False)
    cur.execute("select count(*) n from batch_rows where batch_id=%s", (batch_id,))
    return {"filename": b["original_filename"], "status": b["status"], "delete": len(c["delete"]), "restore": len(c["restore"]),
            "reinsert": len(c["reinsert"]), "already_gone": c["already_gone"], "conflicts": c["conflicts"],
            "staging_rows": cur.fetchone()["n"]}


def delete_batch(conn, batch_id, actor, confirm, force_conflicts=False, purge_file=False):
    cur = cursor(conn)
    cur.execute("select * from import_batches where id=%s", (batch_id,))
    b = cur.fetchone()
    if b is None:
        raise SystemExit("no such batch")
    if b["status"] in ("deleted", "applying", "parsing"):
        raise SystemExit(f"batch is {b['status']}; cannot delete")
    if confirm != b["original_filename"]:
        raise SystemExit(f"confirmation must be the exact filename: {b['original_filename']!r}")
    audit.log(cur, actor, "batch_delete_requested", batch_id, force_conflicts=force_conflicts, purge_file=purge_file)
    conn.commit()

    try:
        lock(cur)
        cur.execute("""insert into sync_runs(batch_id, run_type, parser_version, actor) values (%s,'delete',%s,%s)
                       returning id""", (batch_id, b["parser_version"], actor))
        run_id = cur.fetchone()["id"]
        chains = _chains(cur, batch_id)
        c = _classify(chains, fetch_states(cur, chains), force_conflicts)
        cur.execute("""select column_name from information_schema.columns
                       where table_name='products' and table_schema=current_schema() and column_name <> 'id'
                       order by ordinal_position""")
        set_sql = ", ".join(f"{col['column_name']} = r.{col['column_name']}" for col in cur.fetchall())
        skipped = [x["product_id"] for x in c["conflicts"]] if not force_conflicts else []

        for part in kids.chunks([p for p, _ in c["delete"]], 2000):
            cur.execute("delete from products where id = any(%s::uuid[])", (part,))
        for part in kids.chunks([t for _, _, t in c["restore"]]):
            cur.execute(f"update products p set {set_sql} from jsonb_populate_recordset(null::products, %s) r where p.id = r.id",
                        (ex.Json(part),))
        for part in kids.chunks([t for _, t in c["reinsert"]]):
            cur.execute("insert into products select * from jsonb_populate_recordset(null::products, %s)", (ex.Json(part),))
        back = {pid: t for pid, _, t in c["restore"]}
        back.update({pid: t for pid, t in c["reinsert"]})
        for kind in CHILDREN:
            kids.restore(cur, kind, {pid: t.get(kind) or [] for pid, t in back.items()})

        log = [(run_id, batch_id, pid, "delete", jsonb_or_null(now), None) for pid, now in c["delete"]]
        log += [(run_id, batch_id, pid, "update", jsonb_or_null(now), jsonb_or_null(t)) for pid, now, t in c["restore"]]
        log += [(run_id, batch_id, pid, "insert", None, jsonb_or_null(t)) for pid, t in c["reinsert"]]
        if log:
            ex.execute_values(cur, "insert into change_log(run_id, batch_id, product_id, action, before, after) values %s",
                              log, page_size=500)
        touched = [x[2] for x in log]
        cur.execute("delete from batch_rows where batch_id=%s", (batch_id,))
        cur.execute("""update sync_runs set removed=%s, updated=%s, inserted=%s, finished_at=now(), status='done'
                       where id=%s""", (len(c["delete"]), len(c["restore"]), len(c["reinsert"]), run_id))
        cur.execute("update import_batches set status='deleted' where id=%s", (batch_id,))
        audit.log(cur, actor, "batch_deleted", batch_id, run_id=str(run_id), deleted=len(c["delete"]),
                  restored=len(c["restore"]), reinserted=len(c["reinsert"]), skipped_conflicts=skipped)
        conn.commit()
    except BaseException as e:
        conn.rollback()
        cur = cursor(conn)
        audit.log(cur, actor, "apply_failed", batch_id, error=f"delete failed: {e}")
        conn.commit()
        raise
    reindex(conn, batch_id, actor, touched)
    if purge_file:
        get_storage().delete(b["stored_path"])
        audit.log(cur, actor, "file_purged", batch_id, path=b["stored_path"])
        conn.commit()
    return {"deleted": len(c["delete"]), "restored": len(c["restore"]), "reinserted": len(c["reinsert"]),
            "skipped_conflicts": skipped}
