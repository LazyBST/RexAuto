import copy
import os
import shutil
import tempfile
from pathlib import Path

import fitz
import pytest

from ingest import db, normalize  # noqa: F401
from ingest.profiles import get_profile

SAMPLE = Path("/Users/ayusharora/Downloads/original/03_Master Price List 4WH MAR FY 26-27.pdf")
LOCAL_SAMPLE = Path(__file__).resolve().parent.parent / "data" / "pdfs" / "uno_minda" / SAMPLE.name


def _sample():
    for p in (LOCAL_SAMPLE, SAMPLE):
        if p.exists():
            return p
    pytest.skip("Uno Minda sample PDF not available")


@pytest.fixture(scope="session")
def small_pdf(tmp_path_factory):
    """Pages 1, 2, 38, 39 of the real price list: first rows, a mid page, and the odd pages at the end."""
    src = fitz.open(_sample())
    out = fitz.open()
    for pno in (0, 1, 37, 38):
        out.insert_pdf(src, from_page=pno, to_page=pno)
    path = tmp_path_factory.mktemp("pdf") / "um_small.pdf"
    out.save(path)
    return path


@pytest.fixture(scope="session")
def parsed_small(small_pdf):
    return get_profile("uno_minda").parse(str(small_pdf))


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory):
    import pgserver
    srv = pgserver.get_server(tmp_path_factory.mktemp("pg"))
    yield srv
    srv.cleanup()


@pytest.fixture()
def conn(pg_server, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_server.get_uri())
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "bucket"))
    monkeypatch.delenv("MEILI_URL", raising=False)
    with db.connect() as c:
        cur = c.cursor()
        cur.execute("drop schema public cascade; create schema public;")
        c.commit()
        db.migrate(c)
        db.seed_config(c)
        db.ensure_brand(c, "Uno Minda", "uno-minda")
        c.commit()
        yield c


@pytest.fixture()
def cached_parse(parsed_small):
    return lambda _path: copy.deepcopy(parsed_small)
