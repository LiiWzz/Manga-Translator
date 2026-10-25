"""Single-user local gate: CLI-provisioned admin key, extension pairing and caps.

The local HTTP listener is not itself an authentication boundary. Run one Uvicorn
worker only; this POC does not support multi-process atomic redemption.
"""
import hashlib
import hmac
import secrets
import sys
import threading
import time
from fastapi import HTTPException, Request
from .siwc_store import CredentialStore

LOCAL_HOST = "127.0.0.1:8000"
LOCAL_ORIGIN = "http://127.0.0.1:8000"
PAIR_TTL = 600


class LocalSecurity:
    def __init__(self, store=None):
        self.store = store or CredentialStore()
        self.lock = threading.RLock()
        self.failures = []

    def initialized(self):
        return bool(self.store._read("local-admin.json"))

    @staticmethod
    def _digest(value, salt):
        return hashlib.scrypt(value.encode("utf-8"), salt=bytes.fromhex(salt),
                              n=2**14, r=8, p=1).hex()

    def initialize(self, reset=False):
        with self.lock:
            if self.initialized() and not reset:
                raise RuntimeError("Admin already initialized; use reset-admin explicitly")
            secret = secrets.token_urlsafe(32)
            salt = secrets.token_hex(16)
            self.store._write("local-admin.json", {"salt": salt, "hash": self._digest(secret, salt)})
            self.store._write("extension-capability.json", {})
            self.store._write("extension-pairing.json", {})
            return secret

    def verify_admin(self, key):
        with self.lock:
            now = time.monotonic()
            self.failures = [v for v in self.failures if v > now - 60]
            if len(self.failures) >= 5:
                return False
            record = self.store._read("local-admin.json")
            if not record or not isinstance(key, str) or len(key) > 512:
                self.failures.append(now)
                return False
            try:
                valid = hmac.compare_digest(self._digest(key, record["salt"]), record["hash"])
            except (ValueError, KeyError, TypeError):
                valid = False
            if valid:
                self.failures.clear()
            else:
                self.failures.append(now)
            return valid

    def issue_pairing(self):
        with self.lock:
            code = secrets.token_urlsafe(32)
            self.store._write("extension-pairing.json", {
                "hash": hashlib.sha256(code.encode()).hexdigest(),
                "expires": time.time() + PAIR_TTL})
            return code

    def redeem(self, code):
        with self.lock:
            now = time.monotonic()
            self.failures = [v for v in self.failures if v > now - 60]
            if len(self.failures) >= 5:
                raise HTTPException(status_code=429, detail="Pairing temporarily locked")
            record = self.store._read("extension-pairing.json") or {}
            valid = (isinstance(code, str) and 30 <= len(code) <= 128
                     and record.get("expires", 0) > time.time()
                     and hmac.compare_digest(hashlib.sha256(code.encode()).hexdigest(),
                                             record.get("hash", "0" * 64)))
            if not valid:
                self.failures.append(now)
                raise HTTPException(status_code=403, detail="Invalid or expired pairing code")
            token = secrets.token_urlsafe(48)
            self.store._write("extension-capability.json", {
                "hash": hashlib.sha256(token.encode()).hexdigest()})
            self.store._write("extension-pairing.json", {})
            self.failures.clear()
            return token

    def verify_capability(self, header):
        if not isinstance(header, str) or not header.startswith("Bearer "):
            return False
        token = header[7:]
        if not 32 <= len(token) <= 256:
            return False
        record = self.store._read("extension-capability.json") or {}
        return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),
                                   record.get("hash", "0" * 64))

    def revoke(self):
        with self.lock:
            self.store._write("extension-capability.json", {})
            self.store._write("extension-pairing.json", {})


security = LocalSecurity()


def check_host(request: Request):
    if request.headers.get("host") != LOCAL_HOST:
        raise HTTPException(status_code=403, detail="Invalid local Host")


def check_extension_origin(request: Request):
    check_host(request)
    origin = request.headers.get("origin")
    # Origin is only defense-in-depth; the capability/pairing code is required.
    if origin and origin != LOCAL_ORIGIN and not (
        origin.startswith("chrome-extension://")
        and len(origin.removeprefix("chrome-extension://")) == 32
        and origin.removeprefix("chrome-extension://").isalpha()
    ):
        raise HTTPException(status_code=403, detail="Request origin not permitted")
    if request.headers.get("sec-fetch-site") == "cross-site" and not (
        origin and origin.startswith("chrome-extension://")
    ):
        raise HTTPException(status_code=403, detail="Cross-site request blocked")


def require_extension(request: Request):
    check_extension_origin(request)
    if not security.verify_capability(request.headers.get("authorization")):
        raise HTTPException(status_code=401, detail="Pair the extension before translating")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in {"init", "reset-admin"}:
        raise SystemExit("Usage: python -m app.local_security init|reset-admin")
    # Never put the key in URLs, environment files, git, or diagnostic logs.
    print("Admin unlock key (shown once): " + security.initialize(reset=action == "reset-admin"))
