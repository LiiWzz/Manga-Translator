"""Owner-only, atomic local credential storage for one OSS ChatGPT registration.

Never return this payload from any HTTP endpoint.
"""
import json
import os
import tempfile
import uuid
from pathlib import Path


class CredentialStore:
    def __init__(self, directory=None):
        self.directory = Path(directory or os.getenv("MANGA_AUTH_DIR") or
                              (Path.home() / ".config" / "manga-translator"))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.directory.is_symlink():
            raise RuntimeError("Credential directory must not be a symlink")
        if os.name == "posix":
            self.directory.chmod(0o700)

    def _read(self, name):
        path = self.directory / name
        if not path.exists():
            return None
        if path.is_symlink():
            raise RuntimeError("Refusing symlink credential file")
        if os.name == "posix" and (path.stat().st_mode & 0o077):
            raise RuntimeError("Credentials file permissions must be owner-only")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, name, value):
        path = self.directory / name
        if path.is_symlink():
            raise RuntimeError("Refusing symlink credential file")
        fd, temp_path = tempfile.mkstemp(prefix=".tmp-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(value, file, ensure_ascii=False)
                file.flush()
                os.fsync(file.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def host_id(self):
        record = self._read("host.json")
        if record:
            return record["ext_agent_host_id"]
        identifier = "urn:uuid:" + str(uuid.uuid4())
        self._write("host.json", {"ext_agent_host_id": identifier})
        return identifier

    def load(self):
        return self._read("credentials.json")

    def save(self, record):
        self._write("credentials.json", record)

    def clear_tokens(self):
        record = self.load()
        if not record:
            return
        for name in ("access_token", "refresh_token", "id_token", "expires_at"):
            record.pop(name, None)
        record["scopes"] = []
        record.pop("reconnect_required", None)
        self.save(record)
