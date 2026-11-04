"""File storage. Production: Supabase Storage — private bucket 'batch-files' for the archived (redacted) PDFs, public bucket
'product-images' for product photos. Dev: plain folders. Both expose the same calls."""
import json
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from .db import ROOT

BUCKET = "batch-files"
IMAGE_BUCKET = "product-images"


class LocalStorage:
    def __init__(self, base=None):
        self.base = Path(base or os.environ.get("STORAGE_DIR") or ROOT / "data" / "storage" / BUCKET)

    def put(self, path, data: bytes):
        p = self.base / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return path

    def put_image(self, rel, data: bytes):
        """Store a product photo; returns the URL the database keeps."""
        self.put("images/" + rel, data)
        return "/img/" + rel

    def local_path(self, path):
        return self.base / path

    def delete(self, path):
        p = self.base / path
        if p.exists():
            p.unlink()
        return True

    def exists(self, path):
        return (self.base / path).exists()

    def signed_url(self, path, seconds=300):
        raise NotImplementedError("local storage has no signed URLs; admins download through the ingest API")


class SupabaseStorage:
    """Thin REST client. Every request uses the service-role key, which must never reach a browser."""

    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    def _req(self, method, path, data=None, ctype="application/octet-stream", bucket=BUCKET, extra=None):
        headers = {"Authorization": f"Bearer {self.key}", "apikey": self.key, "Content-Type": ctype, **(extra or {})}
        req = urllib.request.Request(f"{self.url}/storage/v1/object/{bucket}/{urllib.parse.quote(path)}", data=data,
                                     method=method, headers=headers)
        return urllib.request.urlopen(req, timeout=120)

    def put(self, path, data: bytes, bucket=BUCKET):
        self._req("POST", path, data, bucket=bucket, extra={"x-upsert": "true"})
        return path

    def put_image(self, rel, data: bytes):
        ctype = "image/png" if rel.endswith(".png") else "image/jpeg"
        self._req("POST", rel, data, ctype=ctype, bucket=IMAGE_BUCKET, extra={"x-upsert": "true"})
        return f"{self.url}/storage/v1/object/public/{IMAGE_BUCKET}/{urllib.parse.quote(rel)}"

    def delete(self, path):
        self._req("DELETE", path)
        return True

    def exists(self, path):
        try:
            self._req("HEAD", path)
            return True
        except Exception:
            return False

    def local_path(self, path):
        """Download to a temp file (the parsers read from disk)."""
        tmp = Path(tempfile.mkdtemp()) / Path(path).name
        tmp.write_bytes(self._req("GET", path).read())
        return tmp

    def signed_url(self, path, seconds=300):
        """Short-lived link for an admin to download an archived original."""
        body = json.dumps({"expiresIn": seconds}).encode()
        req = urllib.request.Request(f"{self.url}/storage/v1/object/sign/{BUCKET}/{urllib.parse.quote(path)}", data=body,
                                     method="POST", headers={"Authorization": f"Bearer {self.key}", "apikey": self.key,
                                                             "Content-Type": "application/json"})
        signed = json.loads(urllib.request.urlopen(req, timeout=30).read())["signedURL"]
        return f"{self.url}/storage/v1{signed}"


def get_storage():
    return SupabaseStorage() if os.environ.get("SUPABASE_URL") else LocalStorage()
