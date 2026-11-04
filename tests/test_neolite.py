from pathlib import Path

import pytest

from ingest import apply as ap, parse, rollback
from ingest.profiles import get_profile
from ingest.profiles.base import HARD_FLAGS
from ingest.snapshot import snapshot
from ingest.validate import validate

SAMPLE = Path("/Users/ayusharora/Downloads/original/Price List w.e.f 01 April 2026.pdf")
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="Neolite sample PDF not available")


@pytest.fixture(scope="module")
def res():
    r = get_profile("neolite").parse(str(SAMPLE))
    validate(r.rows, r.pages)
    return r


def one(res, code, variant=None):
    hits = [r for r in res.rows if r.data["part_no"] == code and (variant is None or r.data["variant_label"] == variant)]
    assert len(hits) == 1, (code, len(hits))
    return hits[0]


def test_old_and_revised_mrp_and_pack(res):
    d = one(res, "NEO-270").data
    assert (d["mrp_prev"], d["mrp"], d["pack_qty"], d["unit"]) == (476, 524, 16, "each")
    assert d["category"] == "Head Lamps" and d["oem_name"] == "Maruti Suzuki"
    assert d["application"].startswith("Maruti Suzuki 8-00 CC 97")


def test_code_under_several_sections_is_one_product(res):
    d = one(res, "NEO-785").data
    assert "Maruti Suzuki VAN T2" in d["application"] and "GPSY" in d["application"]
    assert len([r for r in res.rows if r.data["part_no"] == "NEO-785"]) == 1


def test_same_code_different_price_gets_variant_labels(res):
    a, b = one(res, "NEO-800A", "W/O/P"), one(res, "NEO-800A", "W/P")
    assert (a.data["mrp"], b.data["mrp"]) == (557, 582)
    assert "variant_inferred" in a.flags


def test_price_drop_is_flagged_not_hidden(res):
    r = one(res, "NEO-1641")
    assert (r.data["mrp_prev"], r.data["mrp"]) == (3830, 2399) and "mrp_decreased" in r.flags


def test_nothing_held_and_all_pages_have_rows(res):
    assert not [r for r in res.rows if HARD_FLAGS & set(r.flags)]
    assert all(p.rows > 0 for p in res.pages) and len(res.pages) == 14


def test_apply_delete_roundtrip(conn):
    conn.cursor().execute("insert into brands(name, slug) values ('Neolite','neolite')")
    conn.commit()
    before = snapshot(conn)
    b = parse.upload_batch(conn, "neolite", "neolite", SAMPLE, "t")["batch_id"]
    parse.parse_batch(conn, b, "t")
    assert ap.apply_batch(conn, b, "t")["inserted"] == 492
    rollback.delete_batch(conn, b, "t", confirm=SAMPLE.name)
    assert snapshot(conn) == before
