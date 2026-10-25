"""Loopback-only OAuth settings endpoints with CSRF for mutations."""
import html
import secrets
import time

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .siwc import auth, AuthError

router = APIRouter()
_sessions = {}
SESSION_TTL = 1800


def _host(request: Request):
    if request.headers.get("host") != "127.0.0.1:8000":
        raise HTTPException(status_code=403, detail="Expected local host")


def _loopback(request: Request):
    _host(request)
    origin = request.headers.get("origin")
    if origin and origin != "http://127.0.0.1:8000":
        raise HTTPException(status_code=403, detail="Cross-origin request blocked")
    referer = request.headers.get("referer")
    if referer and not referer.startswith("http://127.0.0.1:8000/"):
        raise HTTPException(status_code=403, detail="Cross-site referer blocked")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site request blocked")


def _session(request: Request, csrf: str | None = None):
    _loopback(request)
    record = _sessions.get(request.cookies.get("manga_session"))
    if not record or record[1] < time.monotonic():
        raise HTTPException(status_code=403, detail="Open /settings to create a local session")
    if csrf is not None and not secrets.compare_digest(csrf, record[0]):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return record[0]


def _new_session():
    sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    _sessions[sid] = (csrf, time.monotonic() + SESSION_TTL)
    return sid, csrf


def _page(csrf, status):
    """Render a simple localhost settings form with an escaped CSRF token."""
    from string import Template

    email = html.escape(status.get("email") or "Not connected", quote=True)
    model = html.escape(status.get("model") or "(none)", quote=True)
    state = "Connected" if status.get("connected") else "Not connected"
    consent = "Yes" if status.get("plan_usage_enabled") else "No"
    csrf_value = html.escape(csrf, quote=True)

    template = Template("""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><title>Manga Translator - ChatGPT</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font:16px/1.5 system-ui;max-width:740px;margin:32px auto;padding:0 20px;background:#101218;color:#eee}
a{color:#9bd1ff}button{padding:9px 15px;margin:6px;cursor:pointer}
input{padding:9px;width:80%;max-width:470px}
section{padding:15px;background:#222733;border-radius:12px;margin:12px 0}
</style></head><body>
<h1>Manga Translator / ChatGPT</h1>
<section><p>Session: <b>$state</b></p><p>Account: $email</p>
<p>ChatGPT plan permission: $consent</p><p>Selected model: $model</p></section>
<form method="post" action="/auth/start">
<input type="hidden" name="csrf" value="$csrf">
<button type="submit">Continue with ChatGPT</button></form>
<form method="post" action="/auth/reconnect">
<input type="hidden" name="csrf" value="$csrf">
<button type="submit">Reconnect saved account</button></form>
<form method="post" action="/auth/model">
<input type="hidden" name="csrf" value="$csrf">
<label>Model slug from /auth/models
<input name="slug" placeholder="Choose available model slug" required></label>
<button type="submit">Save model</button></form>
<p><a href="/auth/models">Available account models (JSON)</a></p>
<form method="post" action="/auth/logout">
<input type="hidden" name="csrf" value="$csrf">
<button type="submit">Disconnect locally and request token revocation</button></form>
<p>These settings run on your own computer. Never paste tokens into this UI.</p>
</body></html>""")
    return template.substitute(state=state, email=email, consent=consent,
                               model=model, csrf=csrf_value)


@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    _loopback(request)
    sid = request.cookies.get("manga_session")
    record = _sessions.get(sid)
    if record and record[1] >= time.monotonic():
        csrf = record[0]
    else:
        sid, csrf = _new_session()
    response = HTMLResponse(_page(csrf, auth.status()),
        headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'", "X-Frame-Options": "DENY"})
    response.set_cookie("manga_session", sid, httponly=True, samesite="strict", secure=False, path="/")
    return response


@router.post("/auth/start")
async def auth_start(request: Request):
    data = await request.form()
    _session(request, str(data.get("csrf", "")))
    return RedirectResponse(auth.start(), status_code=303)


@router.post("/auth/reconnect")
async def auth_reconnect(request: Request):
    data = await request.form()
    _session(request, str(data.get("csrf", "")))
    try:
        return RedirectResponse(auth.start(reconnect=True), status_code=303)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/auth/callback")
async def auth_callback(request: Request, code: str | None = None,
                        state: str | None = None, client_id: str | None = None,
                        error: str | None = None):
    # Authorization server redirects from another origin; do not reject Sec-Fetch-Site.
    # State, PKCE and the nonce-verified ID token authenticate this callback.
    _host(request)
    try:
        await auth.callback(code, state, client_id, error)
    except AuthError as exc:
        return HTMLResponse("<h2>ChatGPT connection failed</h2><p>" + html.escape(str(exc)) +
                            '</p><a href="/settings">Back to settings</a>', status_code=400,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return RedirectResponse("/settings", status_code=303,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/auth/models")
async def auth_models(request: Request):
    _session(request)
    try:
        return {"models": await auth.models()}
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auth/model")
async def auth_model(request: Request):
    data = await request.form()
    _session(request, str(data.get("csrf", "")))
    try:
        await auth.select_model(str(data.get("slug", "")))
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse("/settings", status_code=303)


@router.post("/auth/logout")
async def auth_logout(request: Request):
    data = await request.form()
    _session(request, str(data.get("csrf", "")))
    result = await auth.logout()
    msg = "Disconnected." if result["remote_revocation_confirmed"] else (
        "Disconnected locally. Remote revocation was NOT confirmed; revoke access in ChatGPT Settings."
    )
    return HTMLResponse("<p>" + html.escape(msg) + '</p><a href="/settings">Back</a>',
                        headers={"Cache-Control": "no-store"})


class ExtensionAuthStatus(BaseModel):
    connected: bool
    plan_usage_enabled: bool
    model: str | None


@router.get("/api/v1/provider/status", response_model=ExtensionAuthStatus)
async def provider_status(request: Request):
    _host(request)
    result = auth.status()
    return {key: result[key] for key in ("connected", "plan_usage_enabled", "model")}
