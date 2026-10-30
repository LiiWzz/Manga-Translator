"""Desktop lifecycle and distribution boundaries, without real provider requests."""
import asyncio
import os
import socket
import sys
import time
from pathlib import Path

import httpx
import pytest

from app.desktop_runtime import (
    LocalGateway, configure_desktop, data_directory, export_extension,
    extension_source, saved_provider,
)


def wait_for(gateway, state):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if gateway.state == state:
            return
        if gateway.state == "failed":
            pytest.fail("Local gateway failed")
        time.sleep(0.01)
    pytest.fail(f"Local gateway did not enter {state}")


def test_desktop_storage_is_separate_and_provider_defaults_to_mock(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_AUTH_DIR", "docker-only-data")
    preferences = configure_desktop(tmp_path)
    assert os.environ["MANGA_AUTH_DIR"] == str(tmp_path / "auth")
    assert saved_provider(preferences) == "mock"
    preferences._write("desktop.json", {"provider": "chatgpt_oauth"})
    assert saved_provider(preferences) == "chatgpt_oauth"
    preferences._write("desktop.json", {"provider": "untrusted"})
    assert saved_provider(preferences) == "mock"
    preferences._write("desktop.json", ["malformed"])
    assert saved_provider(preferences) == "mock"
    if os.name == "posix":
        assert tmp_path.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("system", ["win32", "darwin"])
def test_platform_data_locations(tmp_path, monkeypatch, system):
    monkeypatch.delenv("MANGA_DESKTOP_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    directory = data_directory()
    assert directory.name == "MangaThaiReader"
    assert directory.parent == (tmp_path / "local" if system == "win32"
                                else tmp_path / "Library" / "Application Support")


def test_extension_export_has_no_profiles_tests_or_environment_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
    (source / "background.js").write_text("// bundled", encoding="utf-8")
    for name in (".env", "credentials.json", "test-settings.cjs", "settings.local"):
        (source / name).write_text("excluded", encoding="utf-8")
    (source / "icons").mkdir()
    (source / "icons" / "icon-16.png").write_bytes(b"icon")
    destination = export_extension(source, tmp_path / "export")
    assert sorted(str(p.relative_to(destination)) for p in destination.rglob("*") if p.is_file()) == [
        "background.js", "icons/icon-16.png", "manifest.json",
    ]


@pytest.mark.skipif(os.name != "posix", reason="Symlink creation requires extra Windows authority")
def test_extension_export_rejects_symlinks(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError):
        export_extension(extension_source(), linked)
    assert not list(outside.iterdir())


def test_occupied_port_is_never_reused_or_probed(monkeypatch):
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "mock")
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        gateway = LocalGateway("chatgpt_oauth", port=occupied.getsockname()[1])
        gateway.start()
        assert gateway.state == "failed"
        assert gateway.error == "port_unavailable"
        assert gateway._thread is None
        assert os.environ["TRANSLATOR_PROVIDER"] == "mock"


def test_provider_validation_and_pairing_require_running_server():
    with pytest.raises(ValueError):
        LocalGateway("arbitrary")
    with pytest.raises(RuntimeError):
        LocalGateway("mock").issue_pairing()


def test_real_loopback_lifecycle_keeps_pairing_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_AUTH_DIR", str(tmp_path))
    from app import local_security, siwc
    from app.siwc_store import CredentialStore

    store = CredentialStore(tmp_path)
    monkeypatch.setattr(local_security.security, "store", store)
    monkeypatch.setattr(siwc.auth, "store", store)
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "mock")
    first = LocalGateway("mock", port=0)
    first.start()
    try:
        wait_for(first, "running")
        code = first.issue_pairing()
        with httpx.Client(base_url=f"http://127.0.0.1:{first.port}", trust_env=False,
                          headers={"Host": "127.0.0.1:8000"}) as client:
            assert client.get("/health").json()["provider"] == "mock"
            assert client.get("/api/v1/reader/profile").status_code == 401
            response = client.post("/api/v1/pair/redeem", json={"code": code, "allow_settings": True})
            assert response.status_code == 200
            credentials = response.json()
            assert credentials.get("settings_token")
    finally:
        first.request_stop()
        assert first.wait_stopped()
    assert first.state == "stopped"
    # The real app must be able to stop and immediately rebind its own port.
    second = LocalGateway("mock", port=first.port)
    second.start()
    try:
        wait_for(second, "running")
        with httpx.Client(base_url=f"http://127.0.0.1:{second.port}", trust_env=False,
                          headers={"Host": "127.0.0.1:8000", "Authorization": "Bearer " + credentials["token"]}) as client:
            assert client.get("/api/v1/reader/profile").status_code == 200
    finally:
        second.request_stop()
        assert second.wait_stopped()


def test_concurrent_account_refresh_survives_desktop_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGA_AUTH_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSLATOR_PROVIDER", "mock")
    from app import local_security, siwc
    from app.siwc_store import CredentialStore

    store = CredentialStore(tmp_path)
    monkeypatch.setattr(local_security.security, "store", store)
    monkeypatch.setattr(siwc.auth, "store", store)
    monkeypatch.setattr(siwc.auth, "lock", asyncio.Lock())
    refreshes = []

    async def provider(request):
        if request.url.path.endswith("/token"):
            refreshes.append(1)
            await asyncio.sleep(0.05)  # Make overlapping requests wait on refresh.
            return httpx.Response(200, json={"access_token": "generated-access", "refresh_token": "generated-refresh", "expires_in": 3600})
        return httpx.Response(200, json={"models": [{"slug": "generated-model", "visibility": "list"}]})

    monkeypatch.setattr(siwc.auth, "transport", httpx.MockTransport(provider))

    async def model_requests(port, token):
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False,
                                    headers={"Host": "127.0.0.1:8000", "Authorization": "Bearer " + token}) as client:
            replies = await asyncio.gather(*(client.get("/api/v1/settings/models") for _ in range(2)))
            assert [reply.status_code for reply in replies] == [200, 200]

    for _ in range(2):
        store.save({"client_id": "generated-client", "access_token": "generated-access",
                    "refresh_token": "generated-refresh", "scopes": [siwc.PERMISSION], "expires_at": 0})
        gateway = LocalGateway("mock", port=0)
        gateway.start()
        try:
            wait_for(gateway, "running")
            code = gateway.issue_pairing()
            credentials = local_security.security.redeem_credentials(code, allow_settings=True)
            asyncio.run(model_requests(gateway.port, credentials["settings_token"]))
        finally:
            gateway.request_stop()
            assert gateway.wait_stopped()
    assert len(refreshes) == 2


@pytest.fixture
def qt_application(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    application = widgets.QApplication.instance() or widgets.QApplication([])
    yield application
    application.processEvents()


def test_desktop_pair_code_expires_and_close_waits_for_shutdown(tmp_path, monkeypatch, qt_application):
    from app.desktop_ui import CompanionWindow
    from app.siwc_store import CredentialStore

    class Gateway:
        state = "running"
        error = None

        def request_stop(self):
            self.state = "stopping"

    window = CompanionWindow(tmp_path, CredentialStore(tmp_path), autostart=False)
    try:
        window.gateway = Gateway()
        window.code.setText("temporary-display")
        window.pair_expires = time.monotonic() - 1
        window.refresh()
        assert window.code.text() == ""
        assert not window.copy.isEnabled()
        window.show()
        window.close()
        assert window.closing
        assert window.isVisible()
        assert not window.mode.isEnabled()
        assert not window.toggle.isEnabled()
        window.gateway.state = "stopped"
        window.refresh()
        assert not window.isVisible()
    finally:
        window.gateway = None
        window.close()


def test_desktop_mode_is_persisted_only_when_starting(tmp_path, monkeypatch, qt_application):
    from app import desktop_ui
    from app.siwc_store import CredentialStore

    class Gateway:
        state = "stopped"
        error = None

        def __init__(self, provider):
            self.provider = provider

        def start(self):
            pass

    monkeypatch.setattr(desktop_ui, "LocalGateway", Gateway)
    store = CredentialStore(tmp_path)
    window = desktop_ui.CompanionWindow(tmp_path, store, autostart=False)
    try:
        assert window.mode.currentData() == "mock"
        window.mode.setCurrentIndex(1)
        assert saved_provider(store) == "mock"
        window.start_gateway()
        assert window.gateway.provider == "chatgpt_oauth"
        assert saved_provider(store) == "chatgpt_oauth"
    finally:
        window.close()
