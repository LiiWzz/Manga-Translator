"""Safe application errors; upstream text and credentials never enter the UI."""
import re


MESSAGES = {
    "reconnect_required": ("การเชื่อมต่อ ChatGPT หมดอายุ กรุณาเชื่อมต่อบัญชีเดิมอีกครั้ง", "reconnect", True),
    "permission_required": ("บัญชียังไม่อนุญาตให้ใช้แผน ChatGPT เปิด Settings เพื่อตรวจสิทธิ์", "settings", True),
    "usage_limit": ("ถึงขีดจำกัดการใช้งานแล้ว ตรวจการใช้งานบัญชีและลองใหม่ภายหลัง", "usage", True),
    "unsupported_capability": ("โมเดลหรือรูปแบบคำขอนี้ไม่รองรับการทำงานที่ขอ เปิด Settings เพื่อตรวจโมเดล", "model", True),
    "provider_unavailable": ("ผู้ให้บริการยังไม่พร้อมหรือเครือข่ายขัดข้อง กรุณาลองใหม่ภายหลัง", "retry", False),
    "account_changed": ("บัญชีหรือการตั้งค่าเปลี่ยนแล้ว กรุณาตรวจสถานะและเริ่มแปลใหม่", "reload", True),
    "invalid_response": ("ข้อมูลคำแปลไม่สมบูรณ์ กรุณาลองใหม่", "retry", False),
}


class AuthError(Exception):
    """Messages are app-owned. Never construct one with upstream/user text."""
    def __init__(self, message=None, *, code="invalid_response", status=502,
                 upstream_status=None, upstream_code=None, request_id=None):
        self.code = code if code in MESSAGES else "invalid_response"
        self.action = MESSAGES[self.code][1]
        self.stop_queue = MESSAGES[self.code][2]
        self.status = status
        self.upstream_status = upstream_status
        self.upstream_code = upstream_code
        self.request_id = request_id if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id) else None
        super().__init__(message or MESSAGES[self.code][0])

    def public(self):
        return {"code": self.code, "message": str(self), "action": self.action,
                "stop_queue": self.stop_queue,
                "upstream_status": self.upstream_status, "upstream_code": self.upstream_code,
                "request_id": self.request_id}


TERMINAL_REFRESH_ERRORS = {"invalid_grant", "invalid_refresh_token", "token_expired",
                           "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused"}
PROVIDER_CODES = {
    "subscription_sharing_user_not_eligible": "permission_required",
    "subscription_sharing_usage_limit_exceeded": "usage_limit",
    "subscription_sharing_usage_unavailable": "provider_unavailable",
    "subscription_sharing_unsupported_capability": "unsupported_capability",
    "subscription_sharing_route_not_supported": "permission_required",
    "subscription_sharing_invalid_user": "reconnect_required",
    "chatpass_v2_scope_not_authorized": "permission_required",
    "chatpass_v2_invalid_authorization_context": "permission_required",
    "subscription_sharing_user_unavailable": "provider_unavailable",
}


def provider_error(response=None, *, payload=None, refresh=False):
    if payload is None:
        try:
            payload = response.json() if response is not None else {}
        except ValueError:
            payload = {}
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code") if isinstance(error, dict) else error if isinstance(error, str) else None
    if not isinstance(code, str):
        code = None
    category = PROVIDER_CODES.get(code, "invalid_response")
    upstream_status = response.status_code if response is not None else None
    if refresh and code in TERMINAL_REFRESH_ERRORS:
        category = "reconnect_required"
    elif code not in PROVIDER_CODES:
        category = {401: "reconnect_required", 403: "permission_required", 429: "usage_limit",
                    500: "provider_unavailable", 502: "provider_unavailable", 503: "provider_unavailable",
                    504: "provider_unavailable"}.get(upstream_status, "invalid_response")
    status = {"reconnect_required": 503, "permission_required": 403, "usage_limit": 429,
              "unsupported_capability": 422, "provider_unavailable": 503}.get(category, 502)
    return AuthError(code=category, status=status, upstream_status=upstream_status,
                     upstream_code=code if code in PROVIDER_CODES or code in TERMINAL_REFRESH_ERRORS else None,
                     request_id=response.headers.get("x-request-id") if response is not None else None)
