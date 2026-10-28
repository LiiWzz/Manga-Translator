"""Single-user local gate: owner-issued pairing, legacy recovery and usage caps.

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
        self.requests = []
        self.inflight = 0

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

    def issue_pairing(self, *, manage_settings=False):
        with self.lock:
            if manage_settings:
                # 80 bits before formatting; readable and case-insensitive.
                raw = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(16))
                code = "-".join(raw[i:i + 4] for i in range(0, 16, 4))
            else:
                code = secrets.token_urlsafe(32)
            self.store._write("extension-pairing.json", {
                "hash": hashlib.sha256((raw if manage_settings else code).encode()).hexdigest(),
                "manage_settings": manage_settings,
                "expires": time.time() + PAIR_TTL})
            return code

    def redeem(self, code):
        """Compatibility for reader-only pairing callers."""
        return self.redeem_credentials(code)["token"]

    def redeem_credentials(self, code, *, allow_settings=False):
        with self.lock:
            now = time.monotonic()
            self.failures = [v for v in self.failures if v > now - 60]
            if len(self.failures) >= 5:
                raise HTTPException(status_code=429, detail="Pairing temporarily locked")
            record = self.store._read("extension-pairing.json") or {}
            bounded = isinstance(code, str) and 1 <= len(code) <= 128
            candidate = "".join(code.upper().replace("-", "").split()) if bounded and record.get("manage_settings") else code
            valid = (bounded
                     and record.get("expires", 0) > time.time()
                     and hmac.compare_digest(hashlib.sha256(candidate.encode()).hexdigest(),
                                             record.get("hash", "0" * 64)))
            if not valid:
                self.failures.append(now)
                raise HTTPException(status_code=403, detail="Invalid or expired pairing code")
            if record.get("manage_settings") and not allow_settings:
                raise HTTPException(status_code=409, detail="Settings management consent required")
            token = secrets.token_urlsafe(48)
            credentials = {"token": token}
            capability = {"hash": hashlib.sha256(token.encode()).hexdigest()}
            if record.get("manage_settings"):
                settings_token = secrets.token_urlsafe(48)
                credentials["settings_token"] = settings_token
                capability.update(settings_hash=hashlib.sha256(settings_token.encode()).hexdigest(),
                                  generation=secrets.token_urlsafe(24))
            self.store._write("extension-capability.json", capability)
            self.store._write("extension-pairing.json", {})
            self.failures.clear()
            return credentials

    def verify_capability(self, header):
        return self._verify_token(header, "hash")

    def settings_generation(self, header):
        record = self.store._read("extension-capability.json") or {}
        if self._verify_token(header, "settings_hash", record):
            return record.get("generation")
        return None

    def current_generation(self):
        return (self.store._read("extension-capability.json") or {}).get("generation")

    def _verify_token(self, header, field, record=None):
        if not isinstance(header, str) or not header.startswith("Bearer "):
            return False
        token = header[7:]
        if not 32 <= len(token) <= 256:
            return False
        if record is None:
            record = self.store._read("extension-capability.json") or {}
        return hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(),
                                   record.get(field, "0" * 64))

    def revoke(self):
        with self.lock:
            self.store._write("extension-capability.json", {})
            self.store._write("extension-pairing.json", {})


security = LocalSecurity()


def check_host(request: Request):
    if request.headers.get("host") != LOCAL_HOST:
        raise HTTPException(status_code=403, detail="Invalid local Host")



def check_local_browser_request(request: Request, *, allow_navigation=False):
    """One policy for browser-only owner routes; never used for OAuth callbacks.

    Only explicitly read-only endpoints may opt into cross-site *top-level*
    navigation. Mutation/form endpoints always require same-origin context
    and are separately protected by authenticated session + CSRF.
    """
    check_host(request)
    if (allow_navigation and request.method == "GET"
            and request.headers.get("sec-fetch-mode") == "navigate"
            and request.headers.get("sec-fetch-dest") == "document"):
        return
    origin = request.headers.get("origin")
    if origin and origin != LOCAL_ORIGIN:
        raise HTTPException(status_code=403, detail="Cross-origin request blocked")
    referer = request.headers.get("referer")
    if referer and not referer.startswith(LOCAL_ORIGIN + "/"):
        raise HTTPException(status_code=403, detail="Cross-site referer blocked")
    # 'same-site' is NOT same-origin (e.g. another local port).
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        raise HTTPException(status_code=403, detail="Cross-site request blocked")


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


def require_extension_identity(request: Request):
    check_extension_origin(request)
    if not security.verify_capability(request.headers.get("authorization")):
        raise HTTPException(status_code=401, detail="Pair the extension before translating")


def require_extension(request: Request):
    require_extension_identity(request)
    with security.lock:
        now = time.monotonic()
        security.requests = [t for t in security.requests if now - t < 60]
        if len(security.requests) >= 12 or security.inflight >= 2:
            raise HTTPException(status_code=429, detail="Local translation budget exceeded")
        security.requests.append(now)
        security.inflight += 1
    try:
        yield
    finally:
        with security.lock:
            security.inflight -= 1


def main(args=None):
    args = sys.argv[1:] if args is None else args
    action = args[0] if len(args) == 1 else ""
    if action == "pair":
        print("One-time pairing code (10 minutes): " + security.issue_pairing(manage_settings=True))
        print("Enter in Extension Settings. Grants translation and Settings management after your consent.")
        print("Do not share or save this code. A completed pairing replaces the previous extension.")
        return
    if action not in {"init", "reset-admin"}:
        raise SystemExit("Usage: python -m app.local_security pair|init|reset-admin")
    # Never put the key in URLs, environment files, git, or diagnostic logs.
    print("Admin unlock key (shown once): " + security.initialize(reset=action == "reset-admin"))


if __name__ == "__main__":
    main()
