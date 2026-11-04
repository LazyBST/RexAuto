"""Public search UI + JSON API, all from Postgres. Run:  .venv/bin/python -m ingest serve --port 3000
Read-only, no login. Abuse limits: API docs off, per-IP rate limit, shallow paging (no bulk download of the catalogue)."""
import os
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from . import db, pgsearch

WEB = Path(__file__).resolve().parent.parent / "web"
RATE_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "90"))
MAX_DEPTH = int(os.environ.get("MAX_RESULT_DEPTH", "300"))      # offset + limit a visitor may reach for one query
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"                # behind Vercel/nginx: first X-Forwarded-For hop is the client

app = FastAPI(title="Parts catalogue", docs_url=None, redoc_url=None, openapi_url=None)
_hits = defaultdict(deque)


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() if TRUST_PROXY else "") or \
             (request.client.host if request.client else "?")
        now, q = time.time(), _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_PER_MINUTE:
            return JSONResponse({"detail": "too many requests"}, status_code=429, headers={"Retry-After": "30"})
        q.append(now)
        if len(_hits) > 5000:                                     # forget idle clients
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60]:
                _hits.pop(k, None)
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


@app.get("/api/config")
def config():
    return {"name": os.environ.get("SITE_NAME", "Parts Catalogue"), "whatsapp": os.environ.get("WHATSAPP_NUMBER", "919999999999")}


@app.get("/api/search")
def api_search(q: str = Query("", max_length=120), brand: str = "", make: str = "", segment: str = "", category: str = "",
               min_price: str = "", max_price: str = "", limit: int = Query(30, ge=1, le=50), offset: int = Query(0, ge=0)):
    if offset + limit > MAX_DEPTH:
        raise HTTPException(400, f"results are limited to the first {MAX_DEPTH}; narrow the search")
    f = dict(brand=brand, make=make, segment=segment, category=category, min_price=min_price, max_price=max_price)
    try:
        with db.connect() as conn:
            return pgsearch.search(conn, q, f, limit, offset)
    except ValueError:
        raise HTTPException(400, "bad filter value")


@app.get("/api/product/{pid}")
def api_product(pid: str):
    with db.connect() as conn:
        try:
            p = pgsearch.product(conn, pid)
        except Exception:
            raise HTTPException(404, "not found")
    if not p:
        raise HTTPException(404, "not found")
    return p


@app.get("/img/{path:path}")
def image(path: str):
    from .storage import LocalStorage
    base = (LocalStorage().base / "images").resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(f, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
