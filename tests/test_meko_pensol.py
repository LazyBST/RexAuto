import copy
from pathlib import Path

import fitz
import pytest

from ingest import apply as ap, parse, resync, rollback
from ingest.db import cursor
from ingest.profiles import get_profile
from ingest.snapshot import snapshot
from ingest.validate import validate

BASE = Path("/Users/ayusharora/Downloads/original")
MEKO = BASE / "PRICE LIST 2026.pdf"
PENSOL = BASE / "Automotive Dealer Price List W.e.f. 01-04-2026.pdf"


@pytest.fixture(scope="module")
def meko_small(tmp_path_factory):
    if not MEKO.exists():
        pytest.skip("Meko sample missing")
    src, out = fitz.open(MEKO), fitz.open()
    for p in (7, 8):  # TATA / BHARAT BENZ page and the next
        out.insert_pdf(src, from_page=p, to_page=p)
    path = tmp_path_factory.mktemp("meko") / "meko_small.pdf"
    out.save(path)
    res = get_profile("meko").parse(str(path))
    validate(res.rows, res.pages)
    return path, res


@pytest.fixture(autouse=True)
def _brand(request):
    if "conn" in request.fixturenames:
        conn = request.getfixturevalue("conn")
        conn.cursor().execute("insert into brands(name, slug) values ('Meko','meko') on conflict do nothing")
        conn.commit()


def test_meko_row_fields_and_oem_refs(meko_small):
    _, res = meko_small
    r = next(x for x in res.rows if x.data["part_no"] == "M-540")
    d = r.data
    assert (d["mrp"], d["oem_name"], d["segment"], d["category"]) == (5586, "Tata", "HCV", "Water Pumps")
    refs = [c["ref_part_no"] for c in d["cross_refs"]]
    assert "2525 2010 0103" in refs and "3532005601" in refs and all(c["ref_type"] == "oem" for c in d["cross_refs"])
    assert "TATA 909 / 1313" in d["application"]


def test_meko_variant_suffix_stays_in_part_number(meko_small):
    _, res = meko_small
    assert {"M-854 H", "M-845 A"} <= {r.data["part_no"] for r in res.rows}


def test_meko_non_table_pages_are_reported_not_guessed():
    if not MEKO.exists():
        pytest.skip("Meko sample missing")
    res = get_profile("meko").parse(str(MEKO))
    skipped = {p.page for p in res.pages if p.unrecognised}
    assert {1, 2, 6, 29, 31, 32} == skipped and len(res.rows) == 512


def test_search_finds_a_part_by_its_oem_number(conn, meko_small):
    from ingest import pgsearch
    path, res = meko_small
    b = parse.upload_batch(conn, "meko", "meko", path, "t")["batch_id"]
    parse.parse_batch(conn, b, "t")
    ap.apply_batch(conn, b, "t")
    hit = pgsearch.search(conn, "3532005601")
    assert [h["part_no"] for h in hit["hits"]][:1] == ["M-540"]


def test_cross_refs_roundtrip_resync_and_delete(conn, meko_small):
    path, res = meko_small
    before = snapshot(conn)
    b = parse.upload_batch(conn, "meko", "meko", path, "t")["batch_id"]
    parse.parse_batch(conn, b, "t")
    out = ap.apply_batch(conn, b, "t")
    n = out["inserted"]
    cur = cursor(conn)
    cur.execute("select count(*) n from cross_refs"); assert cur.fetchone()["n"] > n
    after_apply = snapshot(conn)

    def edited(_path):
        r = copy.deepcopy(res)
        for x in r.rows:
            if x.data["part_no"] == "M-540":
                x.data["cross_refs"] = x.data["cross_refs"][:2] + [{"ref_type": "oem", "ref_brand": None, "ref_part_no": "NEW-REF-1", "note": None}]
        return r
    prev = resync.resync_preview(conn, b, "t", parse_fn=edited)
    assert (prev["insert"], prev["update"], prev["remove"]) == (0, 1, 0)
    assert "cross_refs" in prev["sample_updates"][0]["changes"]
    resync.resync_apply(conn, b, "t")
    cur.execute("select ref_part_no from cross_refs r join products p on p.id=r.product_id where p.part_no='M-540' order by 1")
    assert "NEW-REF-1" in [r["ref_part_no"] for r in cur.fetchall()]
    resync.resync_preview(conn, b, "t", parse_fn=lambda _p: copy.deepcopy(res))
    resync.resync_apply(conn, b, "t")           # back to the file: refs return, byte for byte
    assert snapshot(conn)["counts"] == after_apply["counts"]
    rollback.delete_batch(conn, b, "t", confirm="meko_small.pdf")
    assert snapshot(conn) == before


def test_delete_after_ref_edit_restores_original_refs(conn, meko_small):
    path, res = meko_small
    b = parse.upload_batch(conn, "meko", "meko", path, "t")["batch_id"]
    parse.parse_batch(conn, b, "t")
    ap.apply_batch(conn, b, "t")
    snap = snapshot(conn)
    b2 = parse.upload_batch(conn, "meko", "meko", path, "t")["batch_id"]

    def edited(_path):
        r = copy.deepcopy(res)
        for x in r.rows:
            if x.data["part_no"] == "M-504":
                x.data["cross_refs"] = [{"ref_type": "oem", "ref_brand": None, "ref_part_no": "ZZ-9", "note": None}]
        return r
    parse.parse_batch(conn, b2, "t", parse_fn=edited)
    assert ap.apply_batch(conn, b2, "t")["updated"] == 1
    rollback.delete_batch(conn, b2, "t", confirm="meko_small.pdf")
    assert snapshot(conn) == snap


def test_update_only_rows_enrich_without_inserting_or_blanking(conn, meko_small):
    from ingest.profiles.base import ParseResult, ParsedRow, PageStat
    path, res = meko_small
    base = parse.upload_batch(conn, "meko", "meko", path, "t")["batch_id"]
    parse.parse_batch(conn, base, "t")
    ap.apply_batch(conn, base, "t")
    snap = snapshot(conn)
    cur = cursor(conn)
    cur.execute("select mrp, application from products where part_no='M-540'")
    before = cur.fetchone()

    def enrich(_path):
        rows = [ParsedRow(page=1, row_no=1, data={"part_no_norm": "M540", "variant_label": "", "image_url": "/img/meko/x.jpg", "update_only": True}),
                ParsedRow(page=1, row_no=2, data={"part_no_norm": "ZZNOPE", "variant_label": "", "image_url": "/img/meko/y.jpg", "update_only": True})]
        return ParseResult(rows=rows, pages=[PageStat(page=1, rows=2)])
    b2 = parse.upload_batch(conn, "meko", "meko", path, "t")["batch_id"]
    parse.parse_batch(conn, b2, "t", parse_fn=enrich)
    prev = ap.preview(conn, b2)
    assert (prev["insert"], prev["update"], prev["unmatched"]) == (0, 1, 1)
    out = ap.apply_batch(conn, b2, "t")
    assert (out["inserted"], out["updated"], out["unmatched"]) == (0, 1, 1)
    cur.execute("select mrp, application, image_url from products where part_no='M-540'")
    after = cur.fetchone()
    assert after["image_url"] == "/img/meko/x.jpg" and (after["mrp"], after["application"]) == (before["mrp"], before["application"])
    resync.resync_preview(conn, b2, "t", remove_missing=True, parse_fn=enrich)   # must never delete price-list products
    assert resync.resync_apply(conn, b2, "t", remove_missing=True)["removed"] == 0
    rollback.delete_batch(conn, b2, "t", confirm="meko_small.pdf")
    assert snapshot(conn) == snap
