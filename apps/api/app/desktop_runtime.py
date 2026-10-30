"""Local desktop lifecycle; no provider calls, browser automation or token export."""
from __future__ import annotations

import os
import asyncio
import shutil
import socket
import sys
import threading
from pathlib import Path

from .siwc_store import CredentialStore

PROVIDERS = ("mock", "chatgpt_oauth")


def data_directory() -> Path:
    if override := os.getenv("MANGA_DESKTOP_DATA_DIR"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / "MangaThaiReader"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MangaThaiReader"
    return Path.home() / ".local" / "share" / "MangaThaiReader"


def configure_desktop(directory: Path) -> CredentialStore:
    """Set the desktop's separate credential location BEFORE importing the API."""
    preferences = CredentialStore(directory)
    os.environ["MANGA_AUTH_DIR"] = str(directory / "auth")
    return preferences


def saved_provider(preferences: CredentialStore) -> str:
    try:
        value = (preferences._read("desktop.json") or {}).get("provider")
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError):
        return "mock"
    return value if value in PROVIDERS else "mock"


def extension_source() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "bundled_extension"
    return Path(__file__).resolve().parents[2] / "extension"


def extension_files(source: Path) -> list[Path]:
    """An allowlist shared by the bundler and export; never copy user profiles."""
    files = [source / "manifest.json"]
    for pattern in ("*.js", "*.html", "*.css", "icons/*.png"):
        files.extend(sorted(source.glob(pattern)))
    if not all(path.is_file() and not path.is_symlink() for path in files):
        raise RuntimeError("Extension resources are incomplete")
    return files


def export_extension(source: Path, destination: Path) -> Path:
    # A stable path prevents Chrome's unpacked extension ID changing when an
    # archive is moved or a macOS .app is installed in Applications.
    destination.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise RuntimeError("Extension destination must not be a symlink")
    for source_file in extension_files(source):
        target = destination / source_file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.parent.is_symlink():
            raise RuntimeError("Extension destination must not contain symlinks")
        shutil.copyfile(source_file, target)
    return destination


class LocalGateway:
    """Own exactly one loopback listener; never attach to an unknown existing API."""

    def __init__(self, provider: str, *, port: int = 8000):
        if provider not in PROVIDERS:
            raise ValueError("Unsupported desktop provider")
        self.provider = provider
        self.port = port
        self.error: str | None = None
        self._server = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def state(self) -> str:
        if self.error:
            return "failed"
        if not self._thread or not self._thread.is_alive():
            return "stopped"
        if self._stop.is_set():
            return "stopping"
        return "running" if self._server and self._server.started else "starting"

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Create a new gateway to restart")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform == "win32":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                # Allow immediate restart after this process closes an active
                # connection. An existing listening socket still blocks bind.
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.port))
            self.port = listener.getsockname()[1]
            listener.listen(128)
            listener.setblocking(False)
        except OSError:
            listener.close()
            self.error = "port_unavailable"
            return
        os.environ["TRANSLATOR_PROVIDER"] = self.provider
        self._thread = threading.Thread(target=self._serve, args=(listener,), daemon=True)
        self._thread.start()

    def _serve(self, listener: socket.socket) -> None:
        try:
            import uvicorn
            from .main import app
            from .siwc import auth

            # A desktop stop/start creates a new asyncio loop. A refresh lock
            # that had waiters belongs to the old loop; credentials and account
            # generations stay intact, but this in-memory primitive must reset.
            auth.lock = asyncio.Lock()

            self._server = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=self.port, workers=1,
                loop="asyncio", http="h11", ws="none", lifespan="on",
                access_log=False, log_config=None, log_level="critical",
                timeout_graceful_shutdown=3,
            ))
            if not self._stop.is_set():
                self._server.run(sockets=[listener])
                if not self._stop.is_set():
                    self.error = "start_failed"
        except BaseException:
            # Windowed bundles have no console; never expose provider/account
            # exceptions, file contents or credentials in an error dialog/log.
            self.error = "start_failed"
        finally:
            listener.close()

    def request_stop(self) -> None:
        self._stop.set()
        if self._server:
            self._server.should_exit = True

    def wait_stopped(self, timeout: float = 8) -> bool:
        if self._thread:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return True

    def issue_pairing(self) -> str:
        if self.state != "running":
            raise RuntimeError("Start the local gateway before pairing")
        from .local_security import security

        return security.issue_pairing(manage_settings=True)
