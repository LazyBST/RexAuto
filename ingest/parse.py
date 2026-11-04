"""upload -> parse -> stage. Nothing here touches `products`."""
import hashlib
import os
import json
import time
import uuid
from collections import Counter
from pathlib import Path

import fitz
import psycopg2.extras as ex

from . import audit, canon
from .db import cursor
from .profiles import get_profile
from .profiles.base import HARD_FLAGS
from .storage import get_storage
from .validate import validate


def upload_batch(conn, brand_slug, profile_name, file_path, actor):
    profile = get_profile(profile_name)
    path = Path(file_path)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    cur = cursor(conn)
    cur.execute("select id, name from brands where slug = %s", (brand_slug,))
    brand = cur.fetchone()
    if not brand:
        raise SystemExit(f"unknown brand slug {brand_slug!r}")
    try:
        pages = len(fitz.open(stream=data, filetype="pdf"))
    except Exception as e:
        raise SystemExit(f"not a readable PDF: {e}")

    bid = uuid.uuid4()
    stored = f"batches/{bid}/{path.name}"
    redact = getattr(profile, "redact", None) if os.environ.get("REDACT_ON_UPLOAD", "1") != "0" else None  # on by default
    try:
        archived = redact(data) if redact else data  # the unredacted upload is never written anywhere
    except RuntimeError as e:
        raise SystemExit(f"upload refused: the file cannot be archived safely ({e})")
    get_storage().put(stored, archived)
    cur.execute("""insert into import_batches(id, brand_id, profile, parser_version, original_filename, stored_path,
                       file_sha256, file_size_bytes, page_count, uploaded_by, stored_sha256, redacted)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (bid, brand["id"], profile_name, profile.parser_version, path.name, stored, sha, len(archived), pages, actor,
                 hashlib.sha256(archived).hexdigest(), bool(redact)))
    audit.log(cur, actor, "file_uploaded", bid, filename=path.name, sha256=sha, size=len(archived), pages=pages, stored=stored, redacted=bool(redact))
    cur.execute("select id, original_filename, uploaded_at, status from import_batches where file_sha256 = %s and id <> %s",
                (sha, bid))
    dups = cur.fetchall()
    if dups:
        audit.log(cur, actor, "duplicate_file_warning", bid, earlier=[str(d["id"]) for d in dups])
    conn.commit()
    return {"batch_id": bid, "duplicates": dups}


def parse_batch(conn, batch_id, actor, parse_fn=None):
    """Parse the saved file with the batch's profile and (re)write its staging rows."""
    cur = cursor(conn)
    cur.execute("select * from import_batches where id = %s", (batch_id,))
    b = cur.fetchone()
    if b["status"] in ("deleted", "applying"):
        raise SystemExit(f"batch is {b['status']}; cannot parse")
    profile = get_profile(b["profile"])
    cur.execute("update import_batches set status='parsing' where id=%s", (batch_id,))
    audit.log(cur, actor, "parse_started", batch_id, parser_version=profile.parser_version)
    conn.commit()

    t0 = time.time()
    try:
        local = get_storage().local_path(b["stored_path"])
        result = (parse_fn or profile.parse)(str(local))
        canon.apply(result.rows)
        findings = validate(result.rows, result.pages)
    except Exception as e:
        conn.rollback()
        cur = cursor(conn)
        cur.execute("update import_batches set status='failed', notes=%s where id=%s", (f"parse failed: {e}", batch_id))
        audit.log(cur, actor, "parse_finished", batch_id, ok=False, error=str(e))
        conn.commit()
        raise

    cur.execute("delete from batch_rows where batch_id=%s", (batch_id,))
    ex.execute_values(cur, "insert into batch_rows(batch_id, page, row_no, data, flags) values %s",
                      [(batch_id, r.page, r.row_no, ex.Json(r.data), r.flags) for r in result.rows])
    flag_counts = Counter(f for r in result.rows for f in r.flags)
    flagged = sum(1 for r in result.rows if r.flags)
    per_page = {str(p.page): p.rows for p in result.pages}
    ocr = [p.page for p in result.pages if p.needs_ocr]
    unrec = [p.page for p in result.pages if p.unrecognised]
    notes = {"page_notes": {str(p.page): p.note for p in result.pages if p.note}, **findings}
    status = "needs_review" if flagged or ocr or unrec else "ready"
    cur.execute("""update import_batches set status=%s, parser_version=%s, rows_extracted=%s, rows_flagged=%s,
                       pages_needing_ocr=%s, pages_unrecognised=%s, rows_per_page=%s, flag_counts=%s,
                       parse_seconds=%s, notes=%s where id=%s""",
                (status, profile.parser_version, len(result.rows), flagged, ocr, unrec, ex.Json(per_page),
                 ex.Json(dict(flag_counts)), round(time.time() - t0, 2), json.dumps(notes), batch_id))
    audit.log(cur, actor, "parse_finished", batch_id, ok=True, rows=len(result.rows), flagged=flagged,
              seconds=round(time.time() - t0, 2))
    if flagged:
        audit.log(cur, actor, "rows_flagged", batch_id, by_reason=dict(flag_counts))
    if ocr:
        audit.log(cur, actor, "ocr_pages_flagged", batch_id, pages=ocr)
    conn.commit()
    return {"status": status, "rows": len(result.rows), "flagged": flagged}
