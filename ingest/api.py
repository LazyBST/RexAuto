"""FastAPI wrapper used by the admin UI. Every call needs the shared secret; the admin app forwards the
verified user's email in X-Actor so it lands in audit_events."""
import os
import tempfile
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

from . import apply as ap
from . import db, parse, report, resync, rollback

app = FastAPI(title="catalogue-ingest", docs_url=None, redoc_url=None, openapi_url=None)


def auth(x_secret: str = Header(""), x_actor: str = Header("")):
    if not os.environ.get("INGEST_SHARED_SECRET") or x_secret != os.environ["INGEST_SHARED_SECRET"]:
        raise HTTPException(401, "bad secret")
    if not x_actor:
        raise HTTPException(400, "X-Actor required")
    return x_actor


def _run(fn):
    with db.connect() as conn:
        try:
            return fn(conn)
        except SystemExit as e:
            raise HTTPException(409, str(e))


@app.post("/batches")
async def upload(brand: str = Form(...), profile: str = Form(...), file: UploadFile = File(...), actor=Depends(auth)):
    tmp = Path(tempfile.mkdtemp()) / Path(file.filename).name
    tmp.write_bytes(await file.read())
    return _run(lambda c: parse.upload_batch(c, brand, profile, tmp, actor))


@app.post("/batches/{bid}/parse")
def do_parse(bid: str, actor=Depends(auth)):
    return _run(lambda c: parse.parse_batch(c, bid, actor))


@app.get("/batches/{bid}/preview")
def do_preview(bid: str, remove_missing: bool = False, actor=Depends(auth)):
    return _run(lambda c: ap.preview(c, bid, remove_missing))


@app.post("/batches/{bid}/apply")
def do_apply(bid: str, actor=Depends(auth)):
    return _run(lambda c: ap.apply_batch(c, bid, actor))


@app.post("/batches/{bid}/resync")
def do_resync(bid: str, remove_missing: bool = False, apply: bool = False, actor=Depends(auth)):
    def go(c):
        prev = resync.resync_preview(c, bid, actor, remove_missing)
        return {"preview": prev, "applied": resync.resync_apply(c, bid, actor, remove_missing) if apply else None}
    return _run(go)


@app.get("/batches/{bid}/delete-preview")
def del_preview(bid: str, actor=Depends(auth)):
    return _run(lambda c: rollback.delete_preview(c, bid))


@app.post("/batches/{bid}/delete")
def do_delete(bid: str, confirm: str, force_conflicts: bool = False, purge_file: bool = False, actor=Depends(auth)):
    return _run(lambda c: rollback.delete_batch(c, bid, actor, confirm, force_conflicts, purge_file))


@app.get("/batches/{bid}/report")
def do_report(bid: str, actor=Depends(auth)):
    return _run(lambda c: report.batch_report(c, bid))


@app.get("/batches/{bid}/flagged.csv", response_class=PlainTextResponse)
def flagged(bid: str, actor=Depends(auth)):
    return _run(lambda c: report.flagged_csv(c, bid))
