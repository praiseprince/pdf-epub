from __future__ import annotations

import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any

import bcrypt
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings


COOKIE_NAME = "pdf_epub_local_session"
MIN_LOCAL_PIN_LENGTH = 4
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


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def write_local_secrets(path: Path, *, pin_hash: str, session_secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    preserved: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("APP_PIN_HASH=") or line.startswith("SESSION_SECRET="):
                continue
            preserved.append(line)
    content = "\n".join([f"APP_PIN_HASH={pin_hash}", f"SESSION_SECRET={session_secret}", *preserved]).rstrip()
    path.write_text(f"{content}\n", encoding="utf-8")


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
