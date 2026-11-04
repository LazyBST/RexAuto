from pathlib import Path

import pytest

from ingest import apply as ap, parse, rollback
from ingest.profiles import get_profile
from ingest.snapshot import snapshot

SAMPLE = Path("/Users/ayusharora/Downloads/original/AFF_XL_PRICE_LIST_01.04.26.pdf")
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="Fras-le sample PDF not available")


@pytest.fixture(scope="module")
def rows():
    return get_profile("fras_le").parse(str(SAMPLE))


def by(rows, part, var):
    return next(r.data for r in rows.rows if r.data["part_no"] == part and r.data["variant_label"] == var)


def test_counts_and_variants(rows):
    assert len(rows.rows) == 157 and [p.rows for p in rows.pages] == [43, 45, 45, 24]
    assert {r.data["variant_label"] for r in rows.rows} == {"STD", "OS-1", "OS-2", "OS-3"}


def test_group_application_is_carried_to_every_variant(rows):
    for v, mrp in (("STD", 3474), ("OS-1", 3803), ("OS-2", 4189)):
        d = by(rows, "AFF/XL/TTS/1", v)
        assert d["mrp"] == mrp and d["price_basis"] == "ex_tax" and d["hsn"] == "68138100"
        assert d["application"] == "TATA 1510/1612/2515/3516/4018 EICHER JUMBO 2016 WITH AIR BRAKE (SCAM)"
    assert by(rows, "AFF/XL/TTS/2", "STD")["description"].startswith("Brake lining set, rear")


def test_suffix_after_variant_stays_in_part_number(rows):
    assert by(rows, "AFF/XL/TBS6 10 HOLE", "OS-1")["mrp"] == 5845


def test_nothing_held_back(rows):
    from ingest.profiles.base import HARD_FLAGS
    assert not [r for r in rows.rows if HARD_FLAGS & set(r.flags)]


def test_apply_delete_roundtrip(conn):
    cur = conn.cursor()
    cur.execute("insert into brands(name, slug) values ('Fras-le','fras-le')")
    conn.commit()
    before = snapshot(conn)
    b = parse.upload_batch(conn, "fras-le", "fras_le", SAMPLE, "t")["batch_id"]
    parse.parse_batch(conn, b, "t")
    assert ap.apply_batch(conn, b, "t")["inserted"] == 157
    rollback.delete_batch(conn, b, "t", confirm=SAMPLE.name)
    assert snapshot(conn) == before
