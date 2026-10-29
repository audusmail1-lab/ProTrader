"""Oracle session preparation; private loopback preview by default.

Remote use is denied unless explicitly configured AND the existing signed-in
account is individually entitled. No provider tokens or transcript bodies are
stored. Quotas and conversation ownership use the account database.
"""
import os
import time
import asyncio
import threading
import ipaddress
import re
import hashlib
import sqlite3
from collections import deque, OrderedDict
from urllib.parse import parse_qs, urlsplit

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect
import accounts

router = APIRouter()
# Private Oracle conversation preparation. No API keys, signed URLs or
# conversation contents are stored here. Configure the server environment;
# browser code receives only a short-lived, one-use signed WebSocket URL.
# Official contract: elevenlabs.io/docs/eleven-agents/customization/authentication
_ORACLE_SESSION_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}
_ORACLE_SESSION_REQUESTS: deque = deque(maxlen=6)  # timestamps only; no tokens
_ORACLE_SESSION_LOCK = threading.Lock()
_ORACLE_SIGNED_URL_ENDPOINT = "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url"
_ORACLE_IMAGE_MAX_BYTES = 5 * 1024 * 1024
_ORACLE_IMAGE_READ_SECONDS = 15
_ORACLE_IMAGE_REQUESTS: deque = deque(maxlen=6)
_ORACLE_IMAGE_COUNTS: OrderedDict = OrderedDict()
_ORACLE_IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def _oracle_configuration() -> tuple[str, str]:
    """Read configuration at request time without exposing any credential."""
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    agent = (os.environ.get("ORACLE_ELEVENLABS_AGENT_ID", "").strip()
             or os.environ.get("ELEVENLABS_AGENT_ID", "").strip())
    return key, agent


def _require_loopback(request: Request, *, session: bool = False) -> None:
    """Local preview authorization plus Host/Origin checks against rebinding/CSRF.

    This is intentionally not a public authentication system. Remote clients
    remain forbidden even if they supply a forged loopback Host or Origin.
    """
    def loopback(value: str) -> bool:
        if value.lower() == "localhost":
            return True
        try:
            address = ipaddress.ip_address(value)
            return address.is_loopback or bool(getattr(address, "ipv4_mapped", None)
                                               and address.ipv4_mapped.is_loopback)
        except ValueError:
            return False

    def reject() -> None:
        raise HTTPException(403, "Oracle conversation access is restricted to this local preview.",
                            headers=_ORACLE_SESSION_HEADERS)

    if not request.client or not loopback(request.client.host):
        reject()
    try:
        target = urlsplit(str(request.url))
        if (not target.hostname or not loopback(target.hostname)
                or target.username is not None or target.password is not None):
            reject()
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site", "")
        if fetch_site and fetch_site not in ("same-origin", "none"):
            reject()
        # Modern browser POST fetches supply Origin. Require it for token
        # issuance; local command-line clients must deliberately supply it too.
        if session and not origin:
            reject()
        if origin:
            source = urlsplit(origin)
            def authority(url):
                return (url.scheme.lower(), (url.hostname or "").lower(),
                        url.port or (443 if url.scheme.lower() == "https" else 80))
            if (source.scheme not in ("http", "https") or source.path or source.query
                    or source.fragment or source.username is not None or source.password is not None
                    or authority(source) != authority(target)):
                reject()
    except ValueError:
        reject()


def _oracle_local_request(request: Request, *, session: bool = False):
    """Authorize loopback preview or an explicitly entitled account, never a guest.

    Remote mode cannot be enabled by a browser parameter, owner role or API key.
    It needs all deployment switches, the configured HTTPS origin, a current
    accepted account session and that account's numeric ID on the allowlist.
    """
    try:
        if os.getenv("PROTRADER_LOCAL_PREVIEW") != "1":
            raise HTTPException(403, "Oracle conversation access is restricted to this local preview.", headers=_ORACLE_SESSION_HEADERS)
        _require_loopback(request, session=session)
        principal = {"local": True}
    except HTTPException:
        if (os.getenv("PROTRADER_LOCAL_PREVIEW") == "1"
                or os.getenv("ORACLE_REMOTE_ENABLED") != "1"):
            raise
        expected = os.getenv("ORACLE_PUBLIC_ORIGIN", "").rstrip("/")
        target = urlsplit(expected)
        actual = urlsplit(str(request.url))
        if (target.scheme != "https" or not target.hostname or target.path
                or target.username or target.password or target.query or target.fragment
                or actual.scheme != "https" or actual.netloc != target.netloc):
            raise HTTPException(403, "Oracle remote access is not configured for this origin.", headers=_ORACLE_SESSION_HEADERS)
        source = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site", "")
        if ((session and source != expected) or (source and source != expected)
                or fetch_site and fetch_site not in ("same-origin", "none")):
            raise HTTPException(403, "Oracle requires a same-origin request.", headers=_ORACLE_SESSION_HEADERS)
        try:
            user = accounts._need_user(request)
        except HTTPException as error:
            raise HTTPException(error.status_code, error.detail, headers=_ORACLE_SESSION_HEADERS) from None
        permitted = {v.strip() for v in os.getenv("ORACLE_ALLOWED_USER_IDS", "").split(",")
                     if re.fullmatch(r"[1-9][0-9]{0,15}", v.strip())}
        if str(user["id"]) not in permitted:
            raise HTTPException(403, "Oracle conversation access has not been enabled for this account.", headers=_ORACLE_SESSION_HEADERS)
        principal = {"local": False, "user_id": user["id"],
                     "session_hash": accounts._digest(request.cookies.get(accounts.SESSION_COOKIE, ""))}
    request.state.oracle_principal = principal
    return principal


def _remote_schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS oracle_attempts(user_id INTEGER NOT NULL, kind TEXT NOT NULL, created REAL NOT NULL)")
    db.execute("CREATE INDEX IF NOT EXISTS oracle_attempts_user ON oracle_attempts(user_id,kind,created)")
    db.execute("CREATE TABLE IF NOT EXISTS oracle_ownership(conversation_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, session_hash TEXT NOT NULL, created REAL NOT NULL, image_attempts INTEGER NOT NULL DEFAULT 0)")


def _remote_quota(principal, kind, *, conversation_id=None):
    """Durable per-account attempt limits; reserve before a paid provider call.

    Failed upstream calls count. A restart cannot reset the daily budget.
    Image authorization is tied to the account AND the issuing login session.
    """
    if principal["local"]:
        return
    now = time.time()
    with accounts._db() as db:
        _remote_schema(db)
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM oracle_attempts WHERE created < ?", (now - 86400,))
        db.execute("DELETE FROM oracle_ownership WHERE created < ?", (now - 7200,))
        if conversation_id:
            row = db.execute("SELECT * FROM oracle_ownership WHERE conversation_id=? AND user_id=? AND session_hash=? AND created>?",
                             (conversation_id, principal["user_id"], principal["session_hash"], now - 7200)).fetchone()
            if not row:
                raise HTTPException(403, "This Oracle conversation was not issued to this signed-in session.", headers=_ORACLE_SESSION_HEADERS)
            if row["image_attempts"] >= 10:
                raise HTTPException(429, "This conversation has reached its 10 image-upload attempts.", headers=_ORACLE_SESSION_HEADERS)
        used = db.execute("SELECT COUNT(*) AS daily, COALESCE(SUM(created > ?),0) AS minute FROM oracle_attempts WHERE user_id=? AND kind=?",
                          (now - 60, principal["user_id"], kind)).fetchone()
        if used["minute"] >= 6 or used["daily"] >= (30 if kind == "session" else 60):
            raise HTTPException(429, "This account has reached its Oracle request allowance. Try again later.",
                                headers={**_ORACLE_SESSION_HEADERS, "Retry-After": "60" if used["minute"] >= 6 else "86400"})
        db.execute("INSERT INTO oracle_attempts VALUES(?,?,?)", (principal["user_id"], kind, now))
        if conversation_id:
            db.execute("UPDATE oracle_ownership SET image_attempts=image_attempts+1 WHERE conversation_id=?", (conversation_id,))


def _remember_remote_conversation(principal, parsed):
    if principal["local"]:
        return
    # include_conversation_id=true must yield a verifiable ID. Fail closed if
    # the provider contract changes; never claim an arbitrary client-chosen ID.
    values = parse_qs(parsed.query).get("conversation_id", [])
    if len(values) != 1 or not re.fullmatch(r"conv_[A-Za-z0-9]{1,128}", values[0]):
        raise HTTPException(502, "The provider did not return a conversation ownership reference. Remote Oracle remains unavailable.", headers=_ORACLE_SESSION_HEADERS)
    with accounts._db() as db:
        _remote_schema(db)
        # Never reassign an already-issued conversation to another account.
        db.execute("INSERT INTO oracle_ownership(conversation_id,user_id,session_hash,created) VALUES(?,?,?,?)",
                   (values[0], principal["user_id"], principal["session_hash"], time.time()))


@router.get("/api/oracle/conversation/status")
def oracle_conversation_status(request: Request):
    """Presence flags only. Presence does not validate agent access/privacy."""
    principal = _oracle_local_request(request)
    key, agent = _oracle_configuration()
    configured = bool(key and agent)
    return JSONResponse({
        "provider": "ElevenLabs", "configured": configured,
        "api_key_configured": bool(key), "agent_configured": bool(agent),
        "local_preview_only": principal["local"], "access_mode": "local-preview" if principal["local"] else "entitled-account", "transport": "websocket", "image_upload_supported": True,
        "provider_access_verified": False, "agent_privacy_verified": False,
        "message": ("Server configuration is present; provider access and agent privacy have not been verified."
                    if configured else "Private conversation is not configured. Set the server API key and agent reference.")
    }, headers=_ORACLE_SESSION_HEADERS)


def _oracle_provider_scope(detail, *, required_only=False) -> str:
    """Return a fixed label for one explicit scope, never provider prose."""
    scopes = {"convai_read": "ElevenAgents Read", "convai_write": "ElevenAgents Write"}
    fields = ("required_permission", "required_scope") if required_only else ("permission", "required_permission", "required_scope", "scope", "param")
    identified = {value for field in fields
                  if isinstance(value := detail.get(field), str) and value in scopes}
    prose = detail.get("message")
    if isinstance(prose, str):
        prefix = r"\b(?i:missing|requires?|required|needs?)\s+(?:(?:the|a)\s+)?" if required_only else r"\b"
        identified.update(re.findall(prefix + r"(?:permission|scope)\s*[:=]?\s*['\"]?(convai_read|convai_write)(?![\w/-])", prose))
        identified.update(re.findall(prefix + r"['\"]?(convai_read|convai_write)['\"]?\s+(?:permission|scope)\b", prose))
    return (" Provider-identified scope: " + scopes[identified.pop()] + ".") if len(identified) == 1 else ""


def _oracle_provider_error(upstream) -> str:
    """Classify provider failures using fixed text; never echo or log its body.

    Current detail.code and legacy detail.status are described at
    https://elevenlabs.io/docs/eleven-api/resources/errors.
    Only explicitly identified, allowlisted permission names can be displayed.
    """
    try:
        body = upstream.json()
        body_shape = "JSON object" if isinstance(body, dict) else "JSON list" if isinstance(body, list) else "JSON scalar"
    except (ValueError, TypeError):
        body, body_shape = None, "not JSON"
    detail = body.get("detail") if isinstance(body, dict) else None
    detail_shape = ("missing" if not isinstance(body, dict) or "detail" not in body else
                    "object" if isinstance(detail, dict) else "string" if isinstance(detail, str) else "other")
    scope_detail = detail if isinstance(detail, dict) else {"message": detail}
    detail = detail if isinstance(detail, dict) else {}
    code = detail.get("code")
    if not isinstance(code, str) or not code:
        code = detail.get("status")
    code = code if isinstance(code, str) else None
    messages = {
        "invalid_api_key": "ElevenLabs rejected the server API key as invalid (invalid_api_key).",
        "missing_api_key": "ElevenLabs reported a missing server API key (missing_api_key).",
        "invalid_authorization_header": "ElevenLabs reported an invalid authorization header (invalid_authorization_header).",
        "unauthorized": "ElevenLabs requires valid authentication (unauthorized).",
        "sign_in_required": "ElevenLabs reported that sign-in is required (sign_in_required).",
        "forbidden": "ElevenLabs denied access to this operation (forbidden).",
        "workspace_access_denied": "ElevenLabs denied access to the configured workspace (workspace_access_denied).",
        "feature_not_available": "ElevenLabs reported that this feature is unavailable on the account plan (feature_not_available).",
        "subscription_required": "ElevenLabs reported that this feature requires a subscription (subscription_required).",
        "missing_permissions": "ElevenLabs reported missing API-key permissions (missing_permissions).",
        "insufficient_permissions": "ElevenLabs reported insufficient permissions (insufficient_permissions).",
        "quota_exceeded": "ElevenLabs reported exhausted account quota (quota_exceeded).",
        "insufficient_credits": "ElevenLabs reported insufficient account credits (insufficient_credits).",
    }
    if code in messages:
        message = messages[code]
        if code in ("missing_permissions", "insufficient_permissions"):
            message += _oracle_provider_scope(scope_detail)
        elif upstream.status_code in (401, 403):
            message += _oracle_provider_scope(scope_detail, required_only=True)
        return message
    # These diagnostics contain fixed shape labels only, never provider values.
    code_state = "unrecognized" if "code" in detail or "status" in detail else "missing"
    diagnostic = f" Response shape: {body_shape}; detail {detail_shape}; code {code_state}."
    scope = _oracle_provider_scope(scope_detail, required_only=True) if upstream.status_code in (401, 403) else ""
    diagnostic += scope
    type_messages = {
        "validation_error": "ElevenLabs rejected request parameters (validation_error).",
        "invalid_request": "ElevenLabs rejected the request structure (invalid_request).",
        "authentication_error": "ElevenLabs reported an authentication failure (authentication_error).",
        "payment_required": "ElevenLabs reported insufficient credits or a payment requirement (payment_required).",
        "authorization_error": "ElevenLabs reported insufficient authorization for this operation (authorization_error).",
        "not_found": "ElevenLabs could not find the requested resource (not_found).",
        "conflict": "ElevenLabs reported a resource-state conflict (conflict).",
        "rate_limit_error": "ElevenLabs reported a rate or concurrency limit (rate_limit_error).",
        "internal_error": "ElevenLabs reported a provider service error (internal_error).",
        "service_unavailable": "ElevenLabs reported that its service is temporarily unavailable (service_unavailable).",
    }
    error_type = detail.get("type")
    if isinstance(error_type, str) and error_type in type_messages:
        return type_messages[error_type] + diagnostic
    status = upstream.status_code
    if status == 401:
        return "ElevenLabs rejected session authorization (HTTP 401). No recognized provider error code was supplied; check the key and agent access." + diagnostic
    if status == 403:
        return "ElevenLabs denied access (HTTP 403)." + ("" if scope else " No specific permission was identified.") + diagnostic
    if status == 402:
        return "ElevenLabs requires available account credits or payment (HTTP 402)." + diagnostic
    if status == 429:
        return "ElevenLabs rate or concurrency limit reached (HTTP 429). Try again later." + diagnostic
    if 500 <= status <= 599:
        return "ElevenLabs is temporarily unavailable because of a provider service error. Try again later." + diagnostic
    if 300 <= status <= 399:
        return "ElevenLabs returned an unexpected redirect. The request was not followed." + diagnostic
    return "ElevenLabs could not prepare this private conversation session. Check provider availability and configuration." + diagnostic

@router.post("/api/oracle/conversation/session")
def oracle_conversation_session(request: Request):
    """Request ephemeral private-agent authorization; never starts a conversation.

    No prompt, market evidence or account data is sent by this endpoint. The
    client must deliberately start a separate conversation with the returned
    URL. Missing setup and provider failures remain explicit and sanitized.
    """
    principal = _oracle_local_request(request, session=True)
    key, agent = _oracle_configuration()
    if not key or not agent:
        raise HTTPException(503, "Private Oracle conversation is not configured on this server.",
                            headers=_ORACLE_SESSION_HEADERS)
    _remote_quota(principal, "session")
    now = time.monotonic()
    if principal["local"]:
        with _ORACLE_SESSION_LOCK:
            while _ORACLE_SESSION_REQUESTS and now - _ORACLE_SESSION_REQUESTS[0] >= 60:
                _ORACLE_SESSION_REQUESTS.popleft()
            if len(_ORACLE_SESSION_REQUESTS) >= 6:
                raise HTTPException(429, "Too many preview session requests. Try again in a minute.",
                                    headers={**_ORACLE_SESSION_HEADERS, "Retry-After": "60"})
            _ORACLE_SESSION_REQUESTS.append(now)
    try:
        # Fixed host; no caller URLs or credential-bearing redirects. Including
        # a conversation ID makes the returned authorization single-use.
        upstream = requests.get(
            _ORACLE_SIGNED_URL_ENDPOINT,
            params={"agent_id": agent, "include_conversation_id": "true"},
            headers={"xi-api-key": key}, timeout=(5, 10), allow_redirects=False)
        if upstream.status_code != 200:
            raise HTTPException(502, _oracle_provider_error(upstream),
                                headers=_ORACLE_SESSION_HEADERS) from None
        data = upstream.json()
        signed_url = data.get("signed_url") if isinstance(data, dict) else None
        parsed = urlsplit(signed_url) if isinstance(signed_url, str) and len(signed_url) <= 8192 else None
        if (not parsed or parsed.scheme != "wss" or parsed.hostname != "api.elevenlabs.io"
                or parsed.port not in (None, 443) or parsed.username or parsed.password
                or parsed.path != "/v1/convai/conversation" or parsed.fragment
                or not parse_qs(parsed.query).get("conversation_signature", [""])[0]):
            raise ValueError("Invalid provider authorization")
    except requests.Timeout:
        raise HTTPException(504, "ElevenLabs authorization timed out. Try again later.",
                            headers=_ORACLE_SESSION_HEADERS) from None
    except (requests.RequestException, ValueError, TypeError):
        # Do not include provider exception/body text: either may contain a
        # credential or signed URL. No provider response is logged or cached.
        raise HTTPException(502, "ElevenLabs authorization is temporarily unavailable.",
                            headers=_ORACLE_SESSION_HEADERS) from None
    try:
        _remember_remote_conversation(principal, parsed)
    except sqlite3.IntegrityError:
        raise HTTPException(502, "The provider reused a conversation reference. No authorization was issued.", headers=_ORACLE_SESSION_HEADERS) from None
    return JSONResponse({"provider": "ElevenLabs", "transport": "websocket", "signed_url": signed_url,
                         "expires_in_seconds": 900, "single_use": True}, headers=_ORACLE_SESSION_HEADERS)


def _oracle_upload_image(conversation_id: str, content_type: str, image: bytes,
                         key: str, agent: str) -> dict[str, str]:
    """Verify the private conversation, then upload in memory with server auth.

    The browser SDK's uploadFile uses an unauthenticated HTTP request, separate
    from its signed WebSocket. Private agents require this server-side hop.
    Provider transcripts, credentials and responses are never logged or saved.
    """
    url = "https://api.elevenlabs.io/v1/convai/conversations/" + conversation_id
    headers = {"xi-api-key": key}
    try:
        details = requests.get(url, headers=headers, timeout=(5, 10), allow_redirects=False)
        if details.status_code != 200:
            raise HTTPException(502, "Could not verify the private Oracle conversation. "
                                + _oracle_provider_error(details), headers=_ORACLE_SESSION_HEADERS)
        identity = details.json()
        if (not isinstance(identity, dict) or identity.get("agent_id") != agent
                or identity.get("conversation_id") != conversation_id):
            raise HTTPException(403, "This conversation does not belong to the configured Oracle agent.",
                                headers=_ORACLE_SESSION_HEADERS)
        if identity.get("status") not in ("initiated", "in-progress"):
            raise HTTPException(409, "This conversation is no longer active. Connect again before sending an image.",
                                headers=_ORACLE_SESSION_HEADERS)
        # Counts contain a one-way conversation reference, count and timestamps
        # only. Bound both lifetime and retained entries for this local preview.
        count_key = hashlib.sha256((agent + ":" + conversation_id).encode()).hexdigest()
        now = time.monotonic()
        with _ORACLE_SESSION_LOCK:
            for old in [item for item, value in _ORACLE_IMAGE_COUNTS.items()
                        if now - value[1] >= 86400]:
                del _ORACLE_IMAGE_COUNTS[old]
            count, first = _ORACLE_IMAGE_COUNTS.get(count_key, (0, now))
            if count >= 10:
                raise HTTPException(429, "This conversation has reached its 10 image-upload attempts. Start a new conversation.",
                                    headers=_ORACLE_SESSION_HEADERS)
            _ORACLE_IMAGE_COUNTS[count_key] = (count + 1, first)
            _ORACLE_IMAGE_COUNTS.move_to_end(count_key)
            while len(_ORACLE_IMAGE_COUNTS) > 128:
                _ORACLE_IMAGE_COUNTS.popitem(last=False)
        uploaded = requests.post(
            url + "/files", headers=headers,
            files={"file": ("chart." + _ORACLE_IMAGE_TYPES[content_type], image, content_type)},
            timeout=(5, 20), allow_redirects=False)
        if uploaded.status_code != 200:
            raise HTTPException(502, "The image was not uploaded. " + _oracle_provider_error(uploaded),
                                headers=_ORACLE_SESSION_HEADERS)
        receipt = uploaded.json()
        file_id = receipt.get("file_id") if isinstance(receipt, dict) else None
        if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", file_id):
            raise ValueError("Invalid image receipt")
        return {"file_id": file_id}
    except requests.Timeout:
        raise HTTPException(504, "The private image service timed out. Check the conversation before retrying.",
                            headers=_ORACLE_SESSION_HEADERS) from None
    except (requests.RequestException, ValueError, TypeError):
        raise HTTPException(502, "The private image service is temporarily unavailable. No image question was submitted.",
                            headers=_ORACLE_SESSION_HEADERS) from None


@router.post("/api/oracle/conversation/{conversation_id}/image")
async def oracle_conversation_image(conversation_id: str, request: Request):
    """Accept a bounded raw image; no multipart parser or disk files are needed."""
    principal = await asyncio.to_thread(_oracle_local_request, request, session=True)
    if not re.fullmatch(r"conv_[A-Za-z0-9]{1,128}", conversation_id):
        raise HTTPException(400, "The active Oracle conversation reference is invalid. Connect again.",
                            headers=_ORACLE_SESSION_HEADERS)
    key, agent = _oracle_configuration()
    if not key or not agent:
        raise HTTPException(503, "Private Oracle image upload is not configured on this server.",
                            headers=_ORACLE_SESSION_HEADERS)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in _ORACLE_IMAGE_TYPES or request.headers.get("content-encoding", "identity") != "identity":
        raise HTTPException(415, "Choose a PNG, JPEG or WebP chart image.", headers=_ORACLE_SESSION_HEADERS)
    length = request.headers.get("content-length")
    if length is not None:
        if not re.fullmatch(r"[0-9]{1,12}", length):
            raise HTTPException(400, "The image request length is invalid.", headers=_ORACLE_SESSION_HEADERS)
        if int(length) > _ORACLE_IMAGE_MAX_BYTES:
            raise HTTPException(413, "Choose a chart image no larger than 5 MiB.", headers=_ORACLE_SESSION_HEADERS)
    now = time.monotonic()
    await asyncio.to_thread(_remote_quota, principal, "image", conversation_id=conversation_id)
    if principal["local"]:
        with _ORACLE_SESSION_LOCK:
            while _ORACLE_IMAGE_REQUESTS and now - _ORACLE_IMAGE_REQUESTS[0] >= 60:
                _ORACLE_IMAGE_REQUESTS.popleft()
            if len(_ORACLE_IMAGE_REQUESTS) >= 6:
                raise HTTPException(429, "Too many image-upload requests. Try again in a minute.",
                                    headers={**_ORACLE_SESSION_HEADERS, "Retry-After": "60"})
            _ORACLE_IMAGE_REQUESTS.append(now)
    image = bytearray()
    try:
        async with asyncio.timeout(_ORACLE_IMAGE_READ_SECONDS):
            async for chunk in request.stream():
                if len(image) + len(chunk) > _ORACLE_IMAGE_MAX_BYTES:
                    raise HTTPException(413, "Choose a chart image no larger than 5 MiB.",
                                        headers=_ORACLE_SESSION_HEADERS)
                image.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "The image took too long to arrive. Choose the file again.",
                            headers=_ORACLE_SESSION_HEADERS) from None
    except ClientDisconnect:
        raise HTTPException(400, "The image upload was interrupted before it reached the server.",
                            headers=_ORACLE_SESSION_HEADERS) from None
    signatures = {
        "image/png": image.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": image.startswith(b"\xff\xd8\xff"),
        "image/webp": len(image) >= 12 and image[:4] == b"RIFF" and image[8:12] == b"WEBP",
    }
    if not image or not signatures[content_type]:
        raise HTTPException(400, "The file does not match its PNG, JPEG or WebP image type.",
                            headers=_ORACLE_SESSION_HEADERS)
    if length is not None and int(length) != len(image):
        raise HTTPException(400, "The image request was incomplete. Choose the file again.",
                            headers=_ORACLE_SESSION_HEADERS)
    # Revalidate the login after body receipt, then check durable ownership before
    # making any provider request. Local preview keeps its existing bounded path.
    principal = await asyncio.to_thread(_oracle_local_request, request, session=True)
    receipt = await asyncio.to_thread(_oracle_upload_image, conversation_id, content_type, bytes(image), key, agent)
    return JSONResponse(receipt, headers=_ORACLE_SESSION_HEADERS)

