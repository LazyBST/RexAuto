"""Local proof-of-concept web app: public search UI + JSON API, all from the local Postgres.
Run:  .venv/bin/python -m ingest serve --port 3000"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from . import db, pgsearch

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Parts catalogue (local)")


@app.get("/api/config")
def config():
    return {"name": os.environ.get("SITE_NAME", "Parts Catalogue"), "whatsapp": os.environ.get("WHATSAPP_NUMBER", "919999999999")}


@app.get("/api/search")
def api_search(q: str = "", brand: str = "", make: str = "", segment: str = "", category: str = "",
               min_price: str = "", max_price: str = "", limit: int = Query(30, le=100), offset: int = 0):
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


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")
