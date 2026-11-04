"""Meilisearch sync. The database is the source of truth; the index is rebuilt from it, never edited directly."""
import json
import os
import re
import urllib.error
import urllib.request

from .db import ROOT, cursor

INDEX = "products"


def _req(method, path, body=None):
    url = os.environ.get("MEILI_URL")
    if not url:
        return None
    headers = {"Content-Type": "application/json"}
    if os.environ.get("MEILI_MASTER_KEY"):
        headers["Authorization"] = f"Bearer {os.environ['MEILI_MASTER_KEY']}"
    req = urllib.request.Request(url.rstrip("/") + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def _wait(task):
    import time
    if not task:
        return
    for _ in range(300):
        t = _req("GET", f"/tasks/{task['taskUid']}")
        if t["status"] in ("succeeded", "failed", "canceled"):
            if t["status"] != "succeeded":
                raise RuntimeError(f"meili task failed: {t.get('error')}")
            return
        time.sleep(0.1)


def configure():
    if not os.environ.get("MEILI_URL"):
        return {"skipped": "MEILI_URL not set"}
    try:
        _req("POST", "/indexes", {"uid": INDEX, "primaryKey": "id"})
    except urllib.error.HTTPError:
        pass
    _wait(_req("PATCH", f"/indexes/{INDEX}/settings", json.loads((ROOT / "search" / "meili_settings.json").read_text())))
    return {"configured": True}


def _expander(cur):
    cur.execute("select abbr, expansion from abbreviations")
    pairs = [(re.compile(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", re.I), e) for a, e in
             ((r["abbr"], r["expansion"]) for r in cur.fetchall())]

    def expand(text):
        out = text or ""
        for rx, e in pairs:
            out = rx.sub(e, out)
        return out if out != (text or "") else ""
    return expand


def documents(conn, ids):
    cur = cursor(conn)
    expand = _expander(cur)
    cur.execute("""select p.*, b.name as brand, b.slug as brand_slug,
                          coalesce((select array_agg(c.ref_part_no_norm) from cross_refs c where c.product_id=p.id), '{}') as refs
                   from products p join brands b on b.id = p.brand_id
                   where p.id = any(%s::uuid[]) and p.status = 'published'""", ([str(i) for i in ids],))
    docs = []
    for p in cur.fetchall():
        docs.append({
            "id": str(p["id"]), "part_no": p["part_no"], "part_no_norm": p["part_no_norm"],
            "ref_part_nos_norm": p["refs"], "description": p["description"],
            "description_expanded": expand(p["description"]), "brand": p["brand"], "oem_name": p["oem_name"],
            "oem_raw": p["oem_raw"], "application": p["application"], "category": p["category"],
            "segment": p["segment"], "mrp": float(p["mrp"]) if p["mrp"] is not None else None,
            "variant_label": p["variant_label"], "image_url": p["image_url"],
            "slug": f"{p['brand_slug']}-{p['part_no_norm'].lower()}",
        })
    return docs


def sync(conn, product_ids):
    """Upsert the published ones among product_ids, delete the rest (hidden / removed)."""
    if not os.environ.get("MEILI_URL"):
        return {"skipped": "MEILI_URL not set"}
    ids = [str(i) for i in product_ids]
    docs = documents(conn, ids)
    live = {d["id"] for d in docs}
    gone = [i for i in ids if i not in live]
    for i in range(0, len(docs), 5000):
        _wait(_req("POST", f"/indexes/{INDEX}/documents", docs[i:i + 5000]))
    if gone:
        _wait(_req("POST", f"/indexes/{INDEX}/documents/delete-batch", gone))
    return {"upserted": len(docs), "removed": len(gone)}


def rebuild(conn):
    """Recovery: drop and refill the whole index from Postgres."""
    if not os.environ.get("MEILI_URL"):
        return {"skipped": "MEILI_URL not set"}
    try:
        _wait(_req("DELETE", f"/indexes/{INDEX}"))
    except urllib.error.HTTPError:
        pass
    configure()
    cur = cursor(conn)
    cur.execute("select id from products where status='published'")
    return sync(conn, [r["id"] for r in cur.fetchall()])


def search(q, filters=None, limit=20):
    """The one swap-point for the search layer."""
    body = {"q": q, "limit": limit}
    if filters:
        body["filter"] = filters
    return _req("POST", f"/indexes/{INDEX}/search", body)
