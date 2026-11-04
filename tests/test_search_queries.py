"""Search regression set (search/tests/queries.json) against a loaded catalogue.
Set CATALOGUE_TEST_DB to a loaded database URL (e.g. the dry-run database) to run it; skipped otherwise."""
import json
import os
import re
from pathlib import Path

import psycopg2
import pytest

from ingest import pgsearch

QUERIES = json.loads((Path(__file__).resolve().parent.parent / "search" / "tests" / "queries.json").read_text())
pytestmark = pytest.mark.skipif(not os.environ.get("CATALOGUE_TEST_DB"), reason="needs a loaded catalogue (CATALOGUE_TEST_DB)")


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(os.environ["CATALOGUE_TEST_DB"])
    c.set_session(readonly=True)
    yield c
    c.close()


@pytest.mark.parametrize("case", QUERIES, ids=[c["q"][:30] for c in QUERIES])
def test_query(conn, case):
    r = pgsearch.search(conn, case["q"], {}, limit=30)
    if case.get("expect_none"):
        assert r["total"] == 0
        return
    ok = lambda h: all(re.search(v, str(h.get(k) or ""), re.I) for k, v in case["expect"].items())
    rank = next((i + 1 for i, h in enumerate(r["hits"]) if ok(h)), None)
    assert rank is not None and rank <= case["rank_max"], f"{case['q']!r}: expected within top {case['rank_max']}, got {rank}"


def test_latency(conn):
    import statistics, time
    lat = []
    for q in ["tata water pump", "M-513", "brake", "filter", "door lock swift", "oil filter tata"] * 4:
        t = time.time(); pgsearch.search(conn, q, {}, limit=30); lat.append((time.time() - t) * 1000)
    lat.sort()
    assert lat[int(len(lat) * .95) - 1] < 150, f"p95 {lat[int(len(lat) * .95) - 1]:.0f} ms"
