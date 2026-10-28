"""Authenticated localhost Settings, CSRF, OAuth callbacks and extension pairing."""
import hashlib
import html
import secrets
import time
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from .siwc import auth, AuthError
from .settings_ui import settings_page, shell
from .local_security import security, check_host, check_extension_origin, require_extension_identity, check_local_browser_request

router = APIRouter()
_sessions = {}
_settings_tickets = {}
SESSION_TTL = 1800
TICKET_TTL = 60
HEADERS = {
    "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://auth.openai.com; base-uri 'none'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
}


def _loopback(request):
    check_local_browser_request(request)


def _settings_page_access(request: Request):
    check_local_browser_request(request, allow_navigation=True)


def _record(request, csrf=None, admin=True):
    _loopback(request)
    record = _sessions.get(request.cookies.get("manga_session"))
    if not record or record["expires"] < time.monotonic():
        raise HTTPException(status_code=403, detail="Open /settings to create a local session")
    if csrf is not None and not secrets.compare_digest(csrf, record["csrf"]):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    if admin and not _authorized(record):
        raise HTTPException(status_code=403, detail="Unlock local Settings first")
    return record


def _record_session_only(request):
    """Read-only browser navigation: session auth, not mutating CSRF validation."""
    record = _sessions.get(request.cookies.get("manga_session"))
    if not _authorized(record):
        raise HTTPException(status_code=403, detail="Unlock local Settings first")
    return record


def _authorized(record):
    if not record or record["expires"] < time.monotonic() or not record["admin"]:
        return False
    generation = record.get("generation")
    return generation is None or generation == security.current_generation()


def _extension_browser_origin(request):
    check_extension_origin(request)
    origin = request.headers.get("origin", "")
    identifier = origin.removeprefix("chrome-extension://")
    if not origin.startswith("chrome-extension://") or len(identifier) != 32 or any(c not in "abcdefghijklmnop" for c in identifier):
        raise HTTPException(status_code=403, detail="Open Settings from the extension")
    return origin


def _management_generation(request):
    origin = _extension_browser_origin(request)
    generation = security.settings_generation(request.headers.get("authorization"))
    if not generation:
        raise HTTPException(status_code=401, detail="Pair with Settings management permission")
    return origin, generation


def _session_response(sid):
    response = RedirectResponse("/settings", status_code=303, headers={**HEADERS, "Referrer-Policy": "same-origin"})
    response.set_cookie("manga_session", sid, httponly=True, samesite="lax",
                        secure=False, path="/", max_age=SESSION_TTL)
    return response


def _friendly_error(title, message, status_code=400):
    content = (f'<h1>{html.escape(title)}</h1><section class="card"><p role="alert">{html.escape(message)}</p>'
               '<a class="button" href="/settings">กลับไป Settings</a></section>')
    return HTMLResponse(shell(content), status_code=status_code,
                        headers=HEADERS)


@router.get("/api/v1/settings/status")
def settings_status(request: Request):
    _management_generation(request)
    return JSONResponse({"authorized": True}, headers=HEADERS)


@router.post("/api/v1/settings/ticket")
async def settings_ticket(request: Request):
    origin, generation = _management_generation(request)
    now = time.monotonic()
    for key, value in list(_settings_tickets.items()):
        if value["expires"] <= now:
            _settings_tickets.pop(key, None)
    if len(_settings_tickets) >= 32:
        raise HTTPException(status_code=429, detail="Too many pending Settings openings")
    ticket = secrets.token_urlsafe(32)
    _settings_tickets[hashlib.sha256(ticket.encode()).hexdigest()] = {
        "origin": origin, "generation": generation, "expires": now + TICKET_TTL}
    return JSONResponse({"ticket": ticket}, headers=HEADERS)


@router.post("/auth/extension-session")
async def extension_session(request: Request):
    origin = _extension_browser_origin(request)
    data = await request.form()
    ticket = str(data.get("ticket", ""))
    if not 32 <= len(ticket) <= 128:
        raise HTTPException(status_code=403, detail="Settings link expired; reopen from extension")
    key = hashlib.sha256(ticket.encode()).hexdigest()
    # No await between validation and consumption: one API worker owns tickets.
    record = _settings_tickets.get(key)
    if (not record or record["expires"] <= time.monotonic() or record["origin"] != origin
            or record["generation"] != security.current_generation()):
        raise HTTPException(status_code=403, detail="Settings link expired; reopen from extension")
    _settings_tickets.pop(key)
    sid, session = _new_session()
    session.update(admin=True, generation=record["generation"])
    old_sid = request.cookies.get("manga_session")
    if old_sid:
        _sessions.pop(old_sid, None)
    return _session_response(sid)


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


@router.get("/settings", response_class=HTMLResponse)
async def settings(request: Request):
    _settings_page_access(request)
    sid = request.cookies.get("manga_session")
    rec = _sessions.get(sid)
    if not rec or rec["expires"] < time.monotonic() or (rec["admin"] and not _authorized(rec)):
        sid, rec = _new_session()
    # HTML form POSTs need a usable Origin; no-referrer may cause Origin: null.
    # Keep the stricter no-referrer policy on OAuth callbacks and sensitive responses.
    catalog, catalog_error = [], False
    state = auth.status() if rec["admin"] else {}
    if state.get("connected") and state.get("plan_usage_enabled"):
        try:
            catalog = await auth.models()
        except AuthError:
            catalog_error = True
    response = HTMLResponse(settings_page(rec, state, catalog, catalog_error),
                            headers={**HEADERS, "Referrer-Policy": "same-origin"})
    # Lax permits the authorization server's top-level GET callback to carry the session.
    response.set_cookie("manga_session", sid, httponly=True, samesite="lax",
                        secure=False, path="/", max_age=SESSION_TTL)
    return response


@router.post("/auth/unlock")
async def unlock(request: Request):
    data = await request.form()
    rec = _record(request, str(data.get("csrf", "")), admin=False)
    if not security.verify_admin(str(data.get("key", ""))):
        return HTMLResponse(settings_page(rec, {}, message="key ไม่ถูกต้องหรือมีการลองหลายครั้งเกินไป ลองใหม่ภายหลัง หรือใช้การจับคู่จากส่วนขยาย"),
                            status_code=403, headers={**HEADERS, "Referrer-Policy": "same-origin"})
    rec["admin"] = True
    rec.pop("generation", None)
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
    except AuthError:
        return _friendly_error("เชื่อมต่อบัญชีเดิมไม่ได้", "กลับไป Settings แล้วเลือกเชื่อมต่อ ChatGPT เพื่อลงชื่อเข้าใช้อีกครั้ง")


@router.get("/auth/callback")
async def auth_callback(request: Request, code: str | None = None, state: str | None = None,
                        client_id: str | None = None, error: str | None = None):
    # OAuth top-level GET is cross-site; authenticate via state AND the Lax session cookie.
    check_host(request)
    sid = request.cookies.get("manga_session")
    rec = _sessions.get(sid)
    if not _authorized(rec):
        return _friendly_error("สิทธิ์เปิด Settings หมดอายุ", "เปิดจัดการการเชื่อมต่อจากส่วนขยายอีกครั้ง แล้วเริ่มเข้าสู่ระบบใหม่", 403)
    try:
        await auth.callback(code, state, client_id, error, session_id=sid)
    except AuthError:
        return _friendly_error("เชื่อมต่อ ChatGPT ไม่สำเร็จ", "การเข้าสู่ระบบอาจถูกยกเลิกหรือหมดเวลา กลับไป Settings แล้วลองเชื่อมต่ออีกครั้ง")
    return RedirectResponse("/settings", status_code=303, headers=HEADERS)


@router.get("/auth/models")
async def auth_models(request: Request):
    # Authenticated read-only top-level navigation may originate from a link.
    _settings_page_access(request)
    _record_session_only(request)
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
    except AuthError:
        return _friendly_error("บันทึกโมเดลไม่สำเร็จ", "รายการโมเดลอาจเปลี่ยนหรือการเชื่อมต่อขัดข้อง โมเดลเดิมยังไม่ถูกเปลี่ยน กลับไปโหลดรายการใหม่แล้วเลือกอีกครั้ง")
    return RedirectResponse("/settings", status_code=303)


@router.post("/auth/logout")
async def auth_logout(request: Request):
    data = await request.form()
    _record(request, str(data.get("csrf", "")))
    result = await auth.logout()
    msg = ("ออกจากบัญชี ChatGPT แล้ว" if result["remote_revocation_confirmed"] else
           "ออกจากบัญชีในระบบนี้แล้ว แต่ยังยืนยันการถอนสิทธิ์ฝั่ง ChatGPT ไม่ได้ คุณตรวจและถอนสิทธิ์เพิ่มเติมใน ChatGPT Settings ได้")
    return HTMLResponse(shell('<h1>ออกจากบัญชี</h1><section class="card"><p role="status">' + msg + '</p><a class="button" href="/settings">กลับไป Settings</a></section>'), headers=HEADERS)


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
    allow_settings: bool = False


@router.post("/api/v1/pair/redeem")
async def redeem_pair(request: Request, payload: PairBody):
    check_extension_origin(request)
    credentials = security.redeem_credentials(payload.code, allow_settings=payload.allow_settings)
    return JSONResponse(credentials, headers=HEADERS)


@router.post("/api/v1/pair/revoke")
def revoke_extension_pair(request: Request):
    check_extension_origin(request)
    with security.lock:
        header = request.headers.get("authorization")
        if not security.verify_capability(header) and not security.settings_generation(header):
            raise HTTPException(status_code=401, detail="Extension pairing is no longer valid")
        security.revoke()
    return JSONResponse({"revoked": True}, headers=HEADERS)


class ExtensionAuthStatus(BaseModel):
    connected: bool
    plan_usage_enabled: bool
    model: str | None


@router.get("/api/v1/provider/status", response_model=ExtensionAuthStatus)
async def provider_status(request: Request, gate=Depends(require_extension_identity)):
    result = auth.status()
    return JSONResponse({key: result[key] for key in ("connected", "plan_usage_enabled", "model")}, headers=HEADERS)
