from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

import bcrypt
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings


COOKIE_NAME = "pdf_epub_local_session"
SESSION_MAX_AGE_SECONDS = int(timedelta(days=30).total_seconds())


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    if not settings.session_secret:
        # Keep startup forgiving, but authentication will still fail without a
        # configured secret. This makes tests and health checks easier to run.
        secret = "missing-local-session-secret"
    else:
        secret = settings.session_secret
    return URLSafeTimedSerializer(secret_key=secret, salt="pdf-epub-local")


def verify_pin(pin: str, settings: Settings) -> bool:
    if not pin or not settings.app_pin_hash:
        return False

    if settings.app_pin_hash.startswith("$2"):
        try:
            return bcrypt.checkpw(pin.encode("utf-8"), settings.app_pin_hash.encode("utf-8"))
        except ValueError:
            return False

    # Development fallback for manually supplied fixed tokens. The documented
    # setup path uses bcrypt hashes, but this keeps local experiments simple.
    return secrets.compare_digest(pin, settings.app_pin_hash)


def sign_session(settings: Settings) -> str:
    return _serializer(settings).dumps({"authenticated": True})


def read_session(request: Request, settings: Settings) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    try:
        payload = _serializer(settings).loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None

    if not isinstance(payload, dict) or payload.get("authenticated") is not True:
        return None
    return payload


def set_session_cookie(response: Response, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        sign_session(settings),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def require_api_session(request: Request, settings: Settings) -> None:
    if read_session(request, settings) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
