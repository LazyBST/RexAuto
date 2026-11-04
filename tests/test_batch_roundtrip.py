import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import fitz
import psycopg2
import pytest

from ingest import apply as ap, parse, resync, rollback
from ingest.db import cursor
from ingest.profiles.base import HARD_FLAGS, ParsedRow
from ingest.snapshot import snapshot


def applicable(parsed):
    return [r for r in parsed.rows if not (HARD_FLAGS & set(r.flags))]


def edited(parsed, mrp_up=(), drop=(), add=0, dup=False):
    """parse_fn that returns the cached parse with a few controlled edits."""
    def fn(_path):
        res = copy.deepcopy(parsed)
        rows = res.rows
        for i in mrp_up:
            rows[i].data["mrp"] = rows[i].data["mrp"] + 7
        res.rows = [r for i, r in enumerate(rows) if i not in set(drop)]
        for k in range(add):
            base = copy.deepcopy(rows[-1])
            base.data.update(part_no=f"NEW-{k}", part_no_norm=f"NEW{k}", source_row=90000 + k)
            res.rows.append(base)
        if dup:
            res.rows.append(copy.deepcopy(rows[0]))
        return res
    return fn


def new_batch(conn, pdf, fn):
    b = parse.upload_batch(conn, "uno-minda", "uno_minda", pdf, "tester")["batch_id"]
    parse.parse_batch(conn, b, "tester", parse_fn=fn)
    return b


def test_apply_then_delete_restores_exactly(conn, small_pdf, cached_parse, parsed_small):
    before = snapshot(conn)
    b = new_batch(conn, small_pdf, cached_parse)
    res = ap.apply_batch(conn, b, "tester")
    n = len(applicable(parsed_small))
    assert res["inserted"] == n and res["updated"] == 0
    assert snapshot(conn)["counts"]["products"] == n
    assert snapshot(conn)["sha256"] != before["sha256"]
    preview = rollback.delete_preview(conn, b)
    assert preview["delete"] == n and not preview["conflicts"]
    rollback.delete_batch(conn, b, "tester", confirm="um_small.pdf")
    assert snapshot(conn) == before


def test_delete_requires_exact_filename(conn, small_pdf, cached_parse):
    b = new_batch(conn, small_pdf, cached_parse)
    ap.apply_batch(conn, b, "tester")
    with pytest.raises(SystemExit):
        rollback.delete_batch(conn, b, "tester", confirm="wrong.pdf")


def test_second_batch_updates_then_delete_restores_first_state(conn, small_pdf, parsed_small, cached_parse):
    a = new_batch(conn, small_pdf, cached_parse)
    ap.apply_batch(conn, a, "tester")
    after_a = snapshot(conn)
    n = len(applicable(parsed_small))
    dup = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "tester")
    assert dup["duplicates"], "same sha256 must raise a duplicate-file warning"
    b = dup["batch_id"]
    parse.parse_batch(conn, b, "tester", parse_fn=edited(parsed_small, mrp_up=range(5), drop=[10, 11, 12], add=2))
    res = ap.apply_batch(conn, b, "tester")
    assert (res["inserted"], res["updated"], res["unchanged"]) == (2, 5, n - 3 - 5)
    assert snapshot(conn)["counts"]["products"] == n + 2
    rollback.delete_batch(conn, b, "tester", confirm="um_small.pdf")
    assert snapshot(conn) == after_a


def test_delete_skips_products_changed_by_a_later_batch(conn, small_pdf, parsed_small, cached_parse):
    a = new_batch(conn, small_pdf, cached_parse)
    ap.apply_batch(conn, a, "tester")
    n = len(applicable(parsed_small))
    b = parse.upload_batch(conn, "uno-minda", "uno_minda", small_pdf, "tester")["batch_id"]
    parse.parse_batch(conn, b, "tester", parse_fn=edited(parsed_small, mrp_up=range(5)))
    ap.apply_batch(conn, b, "tester")
    prev = rollback.delete_preview(conn, a)
    assert len(prev["conflicts"]) == 5 and prev["delete"] == n - 5
    out = rollback.delete_batch(conn, a, "tester", confirm="um_small.pdf")
    assert len(out["skipped_conflicts"]) == 5 and out["deleted"] == n - 5
    assert snapshot(conn)["counts"]["products"] == 5
    # a forced delete of A after B is gone: restoring removes the remaining five
    rollback.delete_batch(conn, b, "tester", confirm="um_small.pdf")


def test_resync_of_unchanged_file_changes_nothing(conn, small_pdf, parsed_small, cached_parse):
    b = new_batch(conn, small_pdf, cached_parse)
    ap.apply_batch(conn, b, "tester")
    snap = snapshot(conn)
    cur = cursor(conn)
    cur.execute("select count(*) n from change_log"); logged = cur.fetchone()["n"]
    prev = resync.resync_preview(conn, b, "tester", remove_missing=True, parse_fn=cached_parse)
    assert (prev["insert"], prev["update"], prev["remove"]) == (0, 0, 0)
    out = resync.resync_apply(conn, b, "tester", remove_missing=True)
    assert (out["inserted"], out["updated"], out["removed"]) == (0, 0, 0)
    cur.execute("select count(*) n from change_log"); assert cur.fetchone()["n"] == logged
    assert snapshot(conn) == snap


def test_resync_of_edited_file_gives_exact_diff_and_delete_still_restores(conn, small_pdf, parsed_small, cached_parse):
    before = snapshot(conn)
    b = new_batch(conn, small_pdf, cached_parse)
    ap.apply_batch(conn, b, "tester")
    n = len(applicable(parsed_small))
    fn = edited(parsed_small, mrp_up=[0, 1, 2], drop=[20, 21], add=1)
    prev = resync.resync_preview(conn, b, "tester", remove_missing=False, parse_fn=fn)
    assert (prev["insert"], prev["update"], prev["remove"]) == (1, 3, 0)
    assert {u["part_no"] for u in prev["sample_updates"]} == {parsed_small.rows[i].data["part_no"] for i in (0, 1, 2)}
    prev = resync.resync_preview(conn, b, "tester", remove_missing=True, parse_fn=fn)
    assert (prev["insert"], prev["update"], prev["remove"]) == (1, 3, 2)
    out = resync.resync_apply(conn, b, "tester", remove_missing=True)
    assert (out["inserted"], out["updated"], out["removed"]) == (1, 3, 2)
    assert snapshot(conn)["counts"]["products"] == n - 2 + 1
    rollback.delete_batch(conn, b, "tester", confirm="um_small.pdf")
    assert snapshot(conn) == before


def test_hard_flagged_rows_are_staged_but_never_applied(conn, small_pdf, parsed_small):
    b = new_batch(conn, small_pdf, edited(parsed_small, dup=True))
    cur = cursor(conn)
    cur.execute("select count(*) n from batch_rows where batch_id=%s and 'duplicate_in_batch' = any(flags)", (b,))
    assert cur.fetchone()["n"] == 1
    out = ap.apply_batch(conn, b, "tester")
    assert out["held"] == 1 and out["inserted"] == len(applicable(parsed_small))


def test_pages_without_text_layer_are_listed_not_guessed(conn, tmp_path):
    doc = fitz.open()
    doc.new_page()
    pdf = tmp_path / "scan.pdf"
    doc.save(pdf)
    b = parse.upload_batch(conn, "uno-minda", "uno_minda", pdf, "tester")["batch_id"]
    parse.parse_batch(conn, b, "tester")
    cur = cursor(conn)
    cur.execute("select pages_needing_ocr, rows_extracted, status from import_batches where id=%s", (b,))
    r = cur.fetchone()
    assert r["pages_needing_ocr"] == [1] and r["rows_extracted"] == 0 and r["status"] == "needs_review"


def test_history_tables_are_append_only(conn, small_pdf, cached_parse):
    b = new_batch(conn, small_pdf, cached_parse)
    ap.apply_batch(conn, b, "tester")
    cur = conn.cursor()
    for sql in ("update audit_events set actor='x'", "delete from audit_events",
                "update change_log set action='insert'", "delete from change_log"):
        with pytest.raises(psycopg2.Error):
            cur.execute(sql)
        conn.rollback()


class FakeMeili(BaseHTTPRequestHandler):
    docs = {}

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else None

    def do_GET(self):
        self._send({"status": "succeeded"})

    def do_PATCH(self):
        self._body(); self._send({"taskUid": 1})

    def do_DELETE(self):
        FakeMeili.docs.clear(); self._send({"taskUid": 1})

    def do_POST(self):
        body = self._body()
        if self.path.endswith("/documents/delete-batch"):
            for i in body:
                FakeMeili.docs.pop(i, None)
        elif self.path.endswith("/documents"):
            for d in body:
                FakeMeili.docs[d["id"]] = d
        self._send({"taskUid": 1})

    def log_message(self, *a):
        pass


def test_search_index_matches_database_after_each_operation(conn, small_pdf, parsed_small, cached_parse, monkeypatch):
    FakeMeili.docs.clear()
    srv = HTTPServer(("127.0.0.1", 0), FakeMeili)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("MEILI_URL", f"http://127.0.0.1:{srv.server_port}")

    def db_ids():
        cur = cursor(conn)
        cur.execute("select id from products where status='published'")
        return {str(r["id"]) for r in cur.fetchall()}

    b = new_batch(conn, small_pdf, cached_parse)
    ap.apply_batch(conn, b, "tester")
    assert set(FakeMeili.docs) == db_ids() and len(FakeMeili.docs) == len(applicable(parsed_small))
    resync.resync_preview(conn, b, "tester", remove_missing=True, parse_fn=edited(parsed_small, drop=[3], add=1))
    resync.resync_apply(conn, b, "tester", remove_missing=True)
    assert set(FakeMeili.docs) == db_ids()
    rollback.delete_batch(conn, b, "tester", confirm="um_small.pdf")
    assert set(FakeMeili.docs) == db_ids() == set()
    cur = cursor(conn)
    cur.execute("select count(*) n from audit_events where event_type='search_reindexed'")
    assert cur.fetchone()["n"] >= 3
    srv.shutdown()
