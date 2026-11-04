"""Delete ("shred") a batch: undo everything it contributed, keep the history."""
import psycopg2.extras as ex

from . import audit
from .apply import apply_batch, fetch_state, lock, reindex, restore_refs  # noqa: F401
from .db import cursor
from .storage import get_storage


def _chains(cur, batch_id):
    """Per product: the batch's first change (-> state to restore) and last change (-> state we expect now)."""
    cur.execute("""select c.* from change_log c join sync_runs r on r.id = c.run_id
                   where c.batch_id=%s and r.run_type in ('initial','resync') order by c.id""", (batch_id,))
    chains = {}
    for c in cur.fetchall():
        e = chains.setdefault(c["product_id"], {"first": c, "last": c})
        e["last"] = c
    return chains


def delete_preview(conn, batch_id):
    cur = cursor(conn)
    cur.execute("select * from import_batches where id=%s", (batch_id,))
    b = cur.fetchone()
    res = {"filename": b["original_filename"], "status": b["status"], "delete": 0, "restore": 0, "reinsert": 0,
           "already_gone": 0, "conflicts": []}
    for pid, ch in _chains(cur, batch_id).items():
        current = fetch_state(cur, pid)
        expected = ch["last"]["after"]
        first = ch["first"]
        if current != expected:
            if current is None and first["action"] == "insert":
                res["already_gone"] += 1
                continue
            res["conflicts"].append({"product_id": str(pid), "part_no": (current or expected or first["before"] or {}).get("part_no"),
                                     "reason": "removed since" if current is None else "changed since this batch wrote it"})
            continue
        if first["action"] == "insert":
            res["delete"] += 1
        elif current is None:
            res["reinsert"] += 1
        else:
            res["restore"] += 1
    cur.execute("select count(*) n from batch_rows where batch_id=%s", (batch_id,))
    res["staging_rows"] = cur.fetchone()["n"]
    return res


def delete_batch(conn, batch_id, actor, confirm, force_conflicts=False, purge_file=False):
    cur = cursor(conn)
    cur.execute("select * from import_batches where id=%s", (batch_id,))
    b = cur.fetchone()
    if b["status"] in ("deleted", "applying", "parsing"):
        raise SystemExit(f"batch is {b['status']}; cannot delete")
    if confirm != b["original_filename"]:
        raise SystemExit(f"confirmation must be the exact filename: {b['original_filename']!r}")
    audit.log(cur, actor, "batch_delete_requested", batch_id, force_conflicts=force_conflicts, purge_file=purge_file)
    conn.commit()

    lock(cur)
    cur.execute("""insert into sync_runs(batch_id, run_type, parser_version, actor) values (%s,'delete',%s,%s)
                   returning id""", (batch_id, b["parser_version"], actor))
    run_id = cur.fetchone()["id"]
    n_del = n_res = n_rei = 0
    skipped = []
    touched = []

    def log_change(pid, action, before, after):
        cur.execute("insert into change_log(run_id, batch_id, product_id, action, before, after) values (%s,%s,%s,%s,%s,%s)",
                    (run_id, batch_id, pid, action, ex.Json(before), ex.Json(after)))

    cur.execute("""select column_name from information_schema.columns
                   where table_name='products' and table_schema=current_schema() and column_name <> 'id'
                   order by ordinal_position""")
    cols = [r["column_name"] for r in cur.fetchall()]
    set_sql = ", ".join(f"{c} = r.{c}" for c in cols)
    try:
        for pid, ch in _chains(cur, batch_id).items():
            current = fetch_state(cur, pid)
            first, last = ch["first"], ch["last"]
            if current != last["after"]:
                if current is None and first["action"] == "insert":
                    continue
                if not force_conflicts:
                    skipped.append(str(pid))
                    continue
            target = first["before"]  # None when this batch inserted the product
            if target is None:
                if current is not None:
                    cur.execute("delete from products where id=%s", (pid,))
                    log_change(pid, "delete", current, None)
                    n_del += 1
            elif current is None:
                cur.execute("insert into products select * from jsonb_populate_record(null::products, %s)", (ex.Json(target),))
                restore_refs(cur, pid, target.get("cross_refs") or [])
                log_change(pid, "insert", None, target)
                n_rei += 1
            else:
                cur.execute(f"update products set {set_sql} from jsonb_populate_record(null::products, %s) r "
                            f"where products.id = %s", (ex.Json(target), pid))
                restore_refs(cur, pid, target.get("cross_refs") or [])
                log_change(pid, "update", current, target)
                n_res += 1
            touched.append(pid)
        cur.execute("delete from batch_rows where batch_id=%s", (batch_id,))
        cur.execute("""update sync_runs set removed=%s, updated=%s, inserted=%s, finished_at=now(), status='done'
                       where id=%s""", (n_del, n_res, n_rei, run_id))
        cur.execute("update import_batches set status='deleted' where id=%s", (batch_id,))
        audit.log(cur, actor, "batch_deleted", batch_id, run_id=str(run_id), deleted=n_del, restored=n_res,
                  reinserted=n_rei, skipped_conflicts=skipped)
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
    return {"deleted": n_del, "restored": n_res, "reinserted": n_rei, "skipped_conflicts": skipped}
