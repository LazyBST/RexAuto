"""The Supabase storage client against a stand-in HTTP server that speaks the same paths."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ingest import storage


class Fake(BaseHTTPRequestHandler):
    files, seen = {}, []

    def _auth(self):
        Fake.seen.append((self.command, self.path, self.headers.get("Authorization"), self.headers.get("apikey")))

    def _send(self, code=200, body=b"", ctype="application/json"):
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        self._auth()
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n)
        if "/object/sign/" in self.path:
            return self._send(200, json.dumps({"signedURL": "/object/sign/batch-files/x.pdf?token=abc"}).encode())
        Fake.files[self.path.split("/object/", 1)[1]] = body
        self._send(200, b"{}")

    def do_GET(self):
        self._auth(); key = self.path.split("/object/", 1)[1]
        self._send(200 if key in Fake.files else 404, Fake.files.get(key, b"{}"), "application/octet-stream")

    do_HEAD = do_GET

    def do_DELETE(self):
        self._auth(); Fake.files.pop(self.path.split("/object/", 1)[1], None); self._send(200, b"{}")

    def log_message(self, *a):
        pass


@pytest.fixture()
def sb(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("SUPABASE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    Fake.files.clear(); Fake.seen.clear()
    yield storage.get_storage()
    srv.shutdown()


def test_get_storage_picks_supabase_when_configured(sb):
    assert isinstance(sb, storage.SupabaseStorage)


def test_originals_go_to_the_private_bucket_and_come_back(sb):
    sb.put("batches/abc/file name.pdf", b"%PDF-1")
    assert any(k.startswith("batch-files/") for k in Fake.files)
    assert sb.exists("batches/abc/file name.pdf")
    assert sb.local_path("batches/abc/file name.pdf").read_bytes() == b"%PDF-1"
    sb.delete("batches/abc/file name.pdf")
    assert not sb.exists("batches/abc/file name.pdf")


def test_photos_go_to_the_public_bucket_and_return_a_public_url(sb):
    url = sb.put_image("meko/a.jpg", b"jpeg")
    assert "/storage/v1/object/public/product-images/meko/a.jpg" in url and "product-images/meko/a.jpg" in Fake.files


def test_signed_url_for_admin_downloads(sb):
    assert "token=abc" in sb.signed_url("batches/x.pdf", 120)


def test_every_request_carries_the_service_key(sb):
    sb.put("a.pdf", b"x")
    assert all(a == "Bearer service-key" and k == "service-key" for _, _, a, k in Fake.seen)
