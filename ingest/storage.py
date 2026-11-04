"""Private file bucket. Production: Supabase Storage bucket 'batch-files' (public = false, signed URLs only).
Local/dev: a directory outside any web root. Both expose the same three calls."""
import os
import urllib.request
from pathlib import Path

from .db import ROOT

BUCKET = "batch-files"


class LocalStorage:
    def __init__(self, base=None):
        self.base = Path(base or os.environ.get("STORAGE_DIR") or ROOT / "data" / "storage" / BUCKET)

    def put(self, path, data: bytes):
        p = self.base / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return path

    def local_path(self, path):
        return self.base / path

    def delete(self, path):
        p = self.base / path
        if p.exists():
            p.unlink()
        return True

    def exists(self, path):
        return (self.base / path).exists()


class SupabaseStorage:
    """Thin REST client; every request uses the service-role key, never exposed to browsers."""

    def __init__(self):
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    def _req(self, method, path, data=None, ctype="application/octet-stream"):
        req = urllib.request.Request(f"{self.url}/storage/v1/object/{BUCKET}/{path}", data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": ctype})
        return urllib.request.urlopen(req)

    def put(self, path, data: bytes):
        self._req("POST", path, data)
        return path

    def delete(self, path):
        self._req("DELETE", path)
        return True

    def local_path(self, path):
        import tempfile
        req = urllib.request.Request(f"{self.url}/storage/v1/object/{BUCKET}/{path}",
                                     headers={"Authorization": f"Bearer {self.key}"})
        tmp = Path(tempfile.mkdtemp()) / Path(path).name
        tmp.write_bytes(urllib.request.urlopen(req).read())
        return tmp


def get_storage():
    return SupabaseStorage() if os.environ.get("SUPABASE_URL") else LocalStorage()
