"""Authenticated localhost Settings, CSRF, OAuth callbacks and extension pairing."""
import html
import secrets
import time
from string import Template
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from .siwc import auth, AuthError
from .local_security import security, check_host, check_extension_origin, require_extension, LOCAL_ORIGIN

router = APIRouter()
_sessions = {}
SESSION_TTL = 1800
HEADERS = {
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://auth.openai.com; base-uri 'none'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
}


def _loopback(request):
    check_host(request)
    origin = request.headers.get("origin")
    if origin and origin != LOCAL_ORIGIN:
        raise HTTPException(status_code=403, detail="Cross-origin request blocked")
    referer = request.headers.get("referer")
    if referer and not referer.startswith(LOCAL_ORIGIN + "/"):
        raise HTTPException(status_code=403, detail="Cross-site referer blocked")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site request blocked")


def _record(request, csrf=None, admin=True):
    _loopback(request)
    record = _sessions.get(request.cookies.get("manga_session"))
    if not record or record["expires"] < time.monotonic():
        raise HTTPException(status_code=403, detail="Open /settings to create a local session")
    if csrf is not None and not secrets.compare_digest(csrf, record["csrf"]):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    if admin and not record["admin"]:
        raise HTTPException(status_code=403, detail="Unlock local Settings first")
    return record


def _new_session():
    now = time.monotonic()
    for sid, rec in list(_sessions.items()):
        if rec["expires"] < now:
            _sessions.pop(sid, None)
    if len(_sessions) >= 128:
        oldest = min(_sessions, key=lambda sid: _sessions[sid]["expires"])
        _sessions.pop(oldest, None)
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = {"csrf": secrets.token_urlsafe(32), "expires": now + SESSION_TTL, "admin": False}
    return sid, _sessions[sid]


def _page(record):
    csrf = html.escape(record["csrf"], quote=True)
    header = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Manga Translator Settings</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font:16px/1.5 system-ui;max-width:740px;margin:32px auto;padding:0 20px;background:#101218;color:#eee}
a{color:#9bd1ff}button{padding:9px 15px;margin:6px;cursor:pointer}
input{padding:9px;width:80%;max-width:470px}section{padding:15px;background:#222733;border-radius:12px;margin:12px 0}
code{overflow-wrap:anywhere}</style></head><body><h1>Manga Translator / ChatGPT</h1>"""
    if not record["admin"]:
        instruction = ("Run <code>docker compose exec api python -m app.local_security init</code> once to provision the admin key. "
                       "If already provisioned, enter the key printed at initialization. "
                       "Reset with <code>reset-admin</code> from the container CLI (invalidates extension pairing).")
        return header + "<section><p>Settings locked. " + instruction + "</p></section>" + (
            '<form method="post" action="/auth/unlock"><input type="hidden" name="csrf" value="' + csrf +
            '"><label>Local admin key <input type="password" name="key" autocomplete="off" required></label>' +
            '<button type="submit">Unlock</button></form></body></html>')
    status = auth.status()
    values = {"csrf": csrf,
              "state": "Connected" if status.get("connected") else "Not connected",
              "email": html.escape(status.get("email") or "Not connected", quote=True),
              "model": html.escape(status.get("model") or "(none)", quote=True),
              "consent": "Yes" if status.get("plan_usage_enabled") else "No"}
    template = Template("""
<section><p>Session: <b>$state</b></p><p>Account: $email</p>
<p>ChatGPT plan permission: $consent</p><p>Selected model: $model</p></section>
<form method="post" action="/auth/start"><input type="hidden" name="csrf" value="$csrf">
<button type="submit">Continue with ChatGPT</button></form>
<form method="post" action="/auth/reconnect"><input type="hidden" name="csrf" value="$csrf">
<button type="submit">Reconnect saved account</button></form>
<form method="post" action="/auth/model"><input type="hidden" name="csrf" value="$csrf">
<label>Model slug from /auth/models <input name="slug" placeholder="Available model slug" required></label>
<button type="submit">Save model</button></form>
<p><a href="/auth/models">Available account models (JSON)</a></p>
<section><p>Extension Pairing — create a one-time pairing code, then enter it in extension Options.</p>
<form method="post" action="/auth/pair"><input type="hidden" name="csrf" value="$csrf">
<button type="submit">Generate pairing code</button></form>
<form method="post" action="/auth/pair/revoke"><input type="hidden" name="csrf" value="$csrf">
<button type="submit">Revoke paired extension</button></form></section>
<form method="post" action="/auth/logout"><input type="hidden" name="csrf" value="$csrf">
<button type="submit">Disconnect ChatGPT</button></form>
<p>OAuth tokens stay in the local backend, never in extension storage.</p>
</body></html>""")
    return header + template.substitute(**values)


@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    _loopback(request)
    sid = request.cookies.get("manga_session")
    rec = _sessions.get(sid)
    if not rec or rec["expires"] < time.monotonic():
        sid, rec = _new_session()
    # HTML form POSTs need a usable Origin; no-referrer may cause Origin: null.
    # Keep the stricter no-referrer policy on OAuth callbacks and sensitive responses.
    response = HTMLResponse(_page(rec), headers={**HEADERS, "Referrer-Policy": "same-origin"})
    # Lax permits the authorization server's top-level GET callback to carry the session.
    response.set_cookie("manga_session", sid, httponly=True, samesite="lax",
                        secure=False, path="/", max_age=SESSION_TTL)
    return response


@router.post("/auth/unlock")
async def unlock(request: Request):
    data = await request.form()
    rec = _record(request, str(data.get("csrf", "")), admin=False)
    if not security.verify_admin(str(data.get("key", ""))):
        raise HTTPException(status_code=403, detail="Invalid admin key or rate limit")
    rec["admin"] = True
    return RedirectResponse("/settings", status_code=303, headers={"Cache-Control": "no-store"})


@router.post("/auth/start")
async def auth_start(request: Request):
    data = await request.form()
    _record(request, str(data.get("csrf", "")))
    return RedirectResponse(auth.start(session_id=request.cookies["manga_session"]),
                            status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.post("/auth/reconnect")
async def auth_reconnect(request: Request):
    data = await request.form()
    _record(request, str(data.get("csrf", "")))
    try:
        url = auth.start(reconnect=True, session_id=request.cookies["manga_session"])
        return RedirectResponse(url, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/auth/callback")
async def auth_callback(request: Request, code: str | None = None, state: str | None = None,
                        client_id: str | None = None, error: str | None = None):
    # OAuth top-level GET is cross-site; authenticate via state AND the Lax session cookie.
    check_host(request)
    sid = request.cookies.get("manga_session")
    rec = _sessions.get(sid)
    if not rec or not rec["admin"] or rec["expires"] < time.monotonic():
        return HTMLResponse("<h2>Settings session expired; reconnect from Settings.</h2>",
                            status_code=403, headers=HEADERS)
    try:
        await auth.callback(code, state, client_id, error, session_id=sid)
    except AuthError as exc:
        return HTMLResponse("<h2>ChatGPT connection failed</h2><p>" +
                            html.escape(str(exc)) + '</p><a href="/settings">Back</a>',
                            status_code=400, headers=HEADERS)
    return RedirectResponse("/settings", status_code=303, headers=HEADERS)


@router.get("/auth/models")
async def auth_models(request: Request):
    _record(request)
    try:
        return {"models": await auth.models()}
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/auth/model")
async def auth_model(request: Request):
    data = await request.form()
    _record(request, str(data.get("csrf", "")))
    try:
        await auth.select_model(str(data.get("slug", "")))
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse("/settings", status_code=303)


@router.post("/auth/logout")
async def auth_logout(request: Request):
    data = await request.form()
    _record(request, str(data.get("csrf", "")))
    result = await auth.logout()
    msg = ("Disconnected." if result["remote_revocation_confirmed"] else
           "Disconnected locally. Remote revocation unconfirmed; revoke in ChatGPT Settings.")
    return HTMLResponse("<p>" + html.escape(msg) + '</p><a href="/settings">Back</a>', headers=HEADERS)


@router.post("/auth/pair")
async def issue_pair(request: Request):
    data = await request.form()
    _record(request, str(data.get("csrf", "")))
    code = security.issue_pairing()
    return HTMLResponse("<h2>One-time extension pairing code (valid 10 minutes)</h2><code>" +
                        html.escape(code) + '</code><p>Paste into Extension Options. Do not share.</p><a href="/settings">Back</a>',
                        headers=HEADERS)


@router.post("/auth/pair/revoke")
async def revoke_pair(request: Request):
    data = await request.form()
    _record(request, str(data.get("csrf", "")))
    security.revoke()
    return RedirectResponse("/settings", status_code=303)


class PairBody(BaseModel):
    code: str


@router.post("/api/v1/pair/redeem")
async def redeem_pair(request: Request, payload: PairBody):
    check_extension_origin(request)
    token = security.redeem(payload.code)
    return HTMLSafePairResponse(token=token)


from fastapi.responses import JSONResponse

def HTMLSafePairResponse(token):
    return JSONResponse({"token": token}, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


class ExtensionAuthStatus(BaseModel):
    connected: bool
    plan_usage_enabled: bool
    model: str | None


@router.get("/api/v1/provider/status", response_model=ExtensionAuthStatus)
async def provider_status(request: Request, gate=Depends(require_extension)):
    result = auth.status()
    return {key: result[key] for key in ("connected", "plan_usage_enabled", "model")}
