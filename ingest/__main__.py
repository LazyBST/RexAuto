import argparse
import getpass
import json
import sys

from . import apply as ap
from . import db, index, parse, report, resync, rollback
from .snapshot import snapshot


def _actor(a):
    return a.actor or getpass.getuser()


def main(argv=None):
    p = argparse.ArgumentParser(prog="ingest")
    p.add_argument("--actor", help="recorded in audit_events (default: OS user)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="run migrations, load config CSVs, seed brands")
    s = sub.add_parser("upload"); s.add_argument("--brand", required=True); s.add_argument("--profile", required=True); s.add_argument("--file", required=True)
    for name in ("parse", "preview", "apply", "report", "flagged-csv", "delete-preview"):
        s = sub.add_parser(name); s.add_argument("--batch", required=True)
    s = sub.add_parser("resync"); s.add_argument("--batch", required=True); s.add_argument("--apply", action="store_true"); s.add_argument("--remove-missing", action="store_true")
    s = sub.add_parser("delete"); s.add_argument("--batch", required=True); s.add_argument("--confirm", required=True)
    s.add_argument("--force-conflicts", action="store_true"); s.add_argument("--purge-file", action="store_true")
    sub.add_parser("snapshot"); sub.add_parser("reindex")
    sub.add_parser("list")
    s = sub.add_parser("load-all", help="upload, parse and apply every source in data/config/sources.csv")
    s.add_argument("--dir", required=True); s.add_argument("--only", help="comma-separated brand slugs or profiles")
    sub.add_parser("verify", help="post-load checks")
    s = sub.add_parser("set-gst", help="say whether a price list's MRPs include GST (no resync needed)")
    s.add_argument("--includes", required=True, choices=["yes", "no", "unknown"])
    g = s.add_mutually_exclusive_group(required=True); g.add_argument("--batch"); g.add_argument("--brand")
    s = sub.add_parser("serve", help="local search UI + API"); s.add_argument("--port", type=int, default=3000)
    a = p.parse_args(argv)
    actor = _actor(a)
    if a.cmd == "serve":
        import uvicorn
        print(f"Open http://localhost:{a.port}")
        uvicorn.run("ingest.web:app", host="127.0.0.1", port=a.port, log_level="warning")
        return

    with db.connect() as conn:
        if a.cmd == "init-db":
            db.migrate(conn); db.seed_config(conn)
            from . import normalize as nz
            for src in nz.load_csv("sources.csv"):
                db.ensure_brand(conn, src["brand_name"], src["brand_slug"], owned=True)
            conn.commit()
            print("ok")
        elif a.cmd == "upload":
            r = parse.upload_batch(conn, a.brand, a.profile, a.file, actor)
            print("batch", r["batch_id"])
            for d in r["duplicates"]:
                print("  WARNING identical file already uploaded:", d["id"], d["original_filename"], d["uploaded_at"], d["status"])
        elif a.cmd == "parse":
            print(parse.parse_batch(conn, a.batch, actor))
        elif a.cmd == "preview":
            print(json.dumps(ap.preview(conn, a.batch), indent=1, default=str))
        elif a.cmd == "apply":
            print(ap.apply_batch(conn, a.batch, actor))
        elif a.cmd == "report":
            print(report.render(report.batch_report(conn, a.batch)))
        elif a.cmd == "flagged-csv":
            sys.stdout.write(report.flagged_csv(conn, a.batch))
        elif a.cmd == "resync":
            print(json.dumps(resync.resync_preview(conn, a.batch, actor, a.remove_missing), indent=1, default=str))
            if a.apply:
                print(resync.resync_apply(conn, a.batch, actor, a.remove_missing))
        elif a.cmd == "delete-preview":
            print(json.dumps(rollback.delete_preview(conn, a.batch), indent=1, default=str))
        elif a.cmd == "delete":
            print(rollback.delete_batch(conn, a.batch, actor, a.confirm, a.force_conflicts, a.purge_file))
        elif a.cmd == "snapshot":
            print(json.dumps(snapshot(conn)))
        elif a.cmd == "reindex":
            print(index.rebuild(conn))
        elif a.cmd == "load-all":
            from . import loadall
            loadall.load_all(conn, a.dir, actor, set(a.only.split(",")) if a.only else None)
        elif a.cmd == "set-gst":
            val = {"yes": True, "no": False, "unknown": None}[a.includes]
            print(parse.set_price_includes_gst(conn, actor, val, batch_id=a.batch, brand_slug=a.brand), "batch(es) updated")
        elif a.cmd == "verify":
            from . import loadall
            res = loadall.verify(conn)
            for name, ok, detail in res:
                print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
            sys.exit(0 if all(ok for _, ok, _ in res) else 1)
        elif a.cmd == "list":
            cur = db.cursor(conn)
            cur.execute("select id, original_filename, uploaded_at, status, rows_extracted, rows_flagged from import_batches order by uploaded_at")
            for r in cur.fetchall():
                print(r["id"], r["status"], r["rows_extracted"], r["rows_flagged"], r["original_filename"])


if __name__ == "__main__":
    main()
