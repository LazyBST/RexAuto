import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import psycopg2.extras

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"


def database_url():
    """DATABASE_URL in real deployments; otherwise a local dev Postgres (pgserver) under data/pgdata."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    import pgserver
    srv = pgserver.get_server(ROOT / "data" / "pgdata", cleanup_mode=None)  # keeps running between commands
    return srv.get_uri()


@contextmanager
def connect(url=None):
    conn = psycopg2.connect(url or database_url())
    psycopg2.extras.register_uuid()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def migrate(conn):
    cur = conn.cursor()
    cur.execute("create table if not exists schema_migrations (name text primary key, applied_at timestamptz default now())")
    cur.execute("select name from schema_migrations")
    done = {r[0] for r in cur.fetchall()}
    for f in sorted(MIGRATIONS.glob("*.sql")):
        if f.name not in done:
            cur.execute(f.read_text())
            cur.execute("insert into schema_migrations(name) values (%s)", (f.name,))
            print("applied", f.name)
    conn.commit()


def seed_config(conn):
    """Load the owner-reviewable CSVs from data/config into their tables (replace-all)."""
    from . import normalize as nz
    cur = conn.cursor()
    cur.execute("truncate make_aliases, abbreviations, category_map")
    for r in nz.load_csv("make_aliases.csv"):
        cur.execute("insert into make_aliases values (%s,%s)", (r["raw"], r["make"]))
    for r in nz.load_csv("abbreviations.csv"):
        cur.execute("insert into abbreviations values (%s,%s)", (r["abbr"], r["expansion"]))
    for r in nz.load_csv("category_map.csv"):
        cur.execute("insert into category_map values (%s,%s,%s)", (r["brand_slug"], r["source_code"], r["category"]))
    conn.commit()


def ensure_brand(conn, name, slug, owned=True):
    cur = cursor(conn)
    cur.execute("""insert into brands(name, slug, owned) values (%s,%s,%s)
                   on conflict (slug) do update set name = excluded.name returning *""", (name, slug, owned))
    return cur.fetchone()
