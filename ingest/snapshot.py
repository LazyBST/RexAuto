import hashlib
import json

from .db import cursor

TABLES = ["brands", "products", "vehicles", "fitments", "cross_refs"]


def snapshot(conn):
    """sha256 over every catalogue row, serialised exactly as Postgres stores it. History tables are excluded."""
    cur = cursor(conn)
    h = hashlib.sha256()
    counts = {}
    for t in TABLES:
        cur.execute(f"select to_jsonb(t.*) as j from {t} t order by to_jsonb(t.*)::text")
        rows = cur.fetchall()
        counts[t] = len(rows)
        for r in rows:
            h.update(json.dumps(r["j"], sort_keys=True).encode())
    return {"sha256": h.hexdigest(), "counts": counts}
