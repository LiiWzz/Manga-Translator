"""Frozen-app acceptance: local mock translation, pairing, Qt and TLS resources.

No real account, provider calls, persistent credentials or secret output.
"""
import io
import json
import os
import tempfile
import time
from pathlib import Path


def self_test(result_path: Path) -> int:
    outcome = {"status": "failed", "check": "startup"}
    gateway = None
    try:
        with tempfile.TemporaryDirectory(prefix="manga-desktop-check-") as temporary:
            from .desktop_runtime import (
                LocalGateway, configure_desktop, export_extension, extension_source,
            )

            root = Path(temporary)
            preferences = configure_desktop(root)
            os.environ["QT_QPA_PLATFORM"] = "offscreen"
            outcome["check"] = "qt"
            from PySide6.QtWidgets import QApplication
            from .desktop_ui import CompanionWindow

            application = QApplication.instance() or QApplication([])
            window = CompanionWindow(root, preferences, autostart=False)
            window.show()
            application.processEvents()
            if window.mode.currentData() != "mock":
                raise RuntimeError("Default provider must be mock")
            outcome["check"] = "extension"
            extension = export_extension(extension_source(), root / "extension")
            manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
            if manifest["manifest_version"] != 3:
                raise RuntimeError("Invalid extension bundle")

            # An ephemeral port permits checks beside a real installed API;
            # Host remains the production Host expected by the security gate.
            gateway = LocalGateway("mock", port=0)
            outcome["check"] = "gateway"
            gateway.start()
            deadline = time.monotonic() + 30
            while gateway.state == "starting" and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(0.02)
            if gateway.state != "running":
                raise RuntimeError("Local startup failed")

            import certifi
            import httpx
            from PIL import Image
            from pythainlp.tokenize import word_tokenize

            outcome["check"] = "bundled-data"
            if not Path(certifi.where()).is_file() or not word_tokenize("สวัสดีครับ"):
                raise RuntimeError("Required data not bundled")
            with httpx.Client(base_url=f"http://127.0.0.1:{gateway.port}", trust_env=False,
                              headers={"Host": "127.0.0.1:8000"}) as client:
                health = client.get("/health")
                assert health.json() == {"status": "ok", "provider": "mock"}
                assert client.get("/api/v1/reader/profile").status_code == 401
                outcome["check"] = "pairing"
                code = gateway.issue_pairing()
                paired = client.post("/api/v1/pair/redeem", json={"code": code, "allow_settings": True})
                paired.raise_for_status()
                credentials = paired.json()
                client.headers["Authorization"] = "Bearer " + credentials["token"]
                assert client.get("/api/v1/reader/profile").status_code == 200
                image = io.BytesIO()
                outcome["check"] = "mock-reader"
                Image.new("RGB", (32, 32), "white").save(image, "PNG")
                translated = client.post("/api/v1/reader/translate",
                                         files={"file": ("demo.png", image.getvalue(), "image/png")})
                translated.raise_for_status()
                assert translated.json()["provider"] == "mock"
                assert translated.json()["model"] == "mock-demo"
                client.headers["Authorization"] = "Bearer " + credentials["settings_token"]
                outcome["check"] = "settings-authority"
                assert client.get("/api/v1/settings/status").status_code == 200
                assert client.post("/api/v1/pair/redeem", json={"code": code, "allow_settings": True}).status_code == 403
            gateway.request_stop()
            outcome["check"] = "shutdown"
            if not gateway.wait_stopped():
                raise RuntimeError("Local shutdown failed")
            window.close()
            application.processEvents()
        outcome = {"status": "ok", "checks": ["qt", "extension", "tls-data", "thai-data", "mock-reader", "pairing", "shutdown"]}
    except BaseException as exc:
        # A windowed executable can have no stdout/stderr. This result file is
        # also safe for CI artifacts and deliberately contains no exceptions.
        if gateway:
            gateway.request_stop()
            gateway.wait_stopped()
            outcome["gateway_error"] = gateway.failure_kind
        outcome["error_type"] = type(exc).__name__
    result_path.write_text(json.dumps(outcome), encoding="utf-8")
    return 0 if outcome["status"] == "ok" else 1
