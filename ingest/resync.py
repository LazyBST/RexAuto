"""Resync: re-read the SAVED file with the current profile, stage it, and diff against the database."""
from . import audit
from .apply import apply_batch, compute_plan, summarise
from .db import cursor
from .parse import parse_batch


def resync_preview(conn, batch_id, actor, remove_missing=False, parse_fn=None):
    cur = cursor(conn)
    cur.execute("select status from import_batches where id=%s", (batch_id,))
    if cur.fetchone()["status"] not in ("applied", "ready", "needs_review", "failed"):
        raise SystemExit("batch cannot be resynced in its current state")
    parse_batch(conn, batch_id, actor, parse_fn=parse_fn)
    cur = cursor(conn)
    plan = summarise(compute_plan(cur, batch_id, remove_missing))
    audit.log(cur, actor, "resync_previewed", batch_id, remove_missing=remove_missing,
              **{k: plan[k] for k in ("insert", "update", "unchanged", "remove", "held_not_applied")})
    conn.commit()
    return plan


def resync_apply(conn, batch_id, actor, remove_missing=False):
    return apply_batch(conn, batch_id, actor, run_type="resync", remove_missing=remove_missing)
