from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException
import httpx


@dataclass(frozen=True)
class Identity:
    user_id: str
    workspace_id: str


def _secret() -> bytes:
    return os.getenv("APP_SECRET", "local-development-secret-change-me").encode()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(identity: Identity, ttl_seconds: int = 3600) -> str:
    payload = {
        "sub": identity.user_id,
        "workspace_id": identity.workspace_id,
        "exp": int(time.time()) + ttl_seconds,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = _encode(hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_token(token: str) -> Identity:
    try:
        encoded, provided_signature = token.split(".", 1)
        expected_signature = _encode(hmac.new(_secret(), encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(provided_signature, expected_signature):
            raise ValueError("signature")
        payload = json.loads(_decode(encoded))
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError("expired")
        return Identity(user_id=str(payload["sub"]), workspace_id=str(payload["workspace_id"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from None


async def _verify_introspection_token(
    token: str, client: httpx.AsyncClient | None = None
) -> Identity:
    url = os.getenv("IDENTITY_INTROSPECTION_URL", "")
    if not url:
        raise HTTPException(status_code=503, detail="Identity provider is not configured")
    if os.getenv("APP_ENV", "development") == "production" and not url.startswith("https://"):
        raise HTTPException(status_code=503, detail="Identity provider must use HTTPS")
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=8.0)
    try:
        response = await http_client.post(
            url,
            data={"token": token},
            auth=(
                os.getenv("IDENTITY_CLIENT_ID", ""),
                os.getenv("IDENTITY_CLIENT_SECRET", ""),
            ),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("active") or not payload.get("sub") or not payload.get("workspace_id"):
            raise ValueError("inactive or incomplete token")
        if payload.get("exp") and int(payload["exp"]) <= int(time.time()):
            raise ValueError("expired token")
        return Identity(user_id=str(payload["sub"]), workspace_id=str(payload["workspace_id"]))
    except (httpx.HTTPError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from None
    finally:
        if owns_client:
            await http_client.aclose()


async def require_identity(authorization: str | None = Header(default=None)) -> Identity:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.removeprefix("Bearer ").strip()
    auth_mode = os.getenv("AUTH_MODE", "local").lower()
    if auth_mode in {"local", "guest"}:
        return verify_token(token)
    if auth_mode == "introspection":
        return await _verify_introspection_token(token)
    raise HTTPException(status_code=503, detail="Unsupported authentication mode")


def require_conversation_access(identity: Identity, workspace_id: str, owner_user_id: str) -> None:
    # Return 404 to avoid revealing that another user's conversation exists.
    if identity.workspace_id != workspace_id or identity.user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
