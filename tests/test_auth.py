import asyncio
import time

import httpx
from fastapi import HTTPException

from app.services.auth import _verify_introspection_token


def test_introspection_maps_provider_claims(monkeypatch) -> None:
    monkeypatch.setenv("IDENTITY_INTROSPECTION_URL", "https://identity.example.test/introspect")

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"token=provider-token" in request.content
        return httpx.Response(
            200,
            json={
                "active": True,
                "sub": "provider-user",
                "workspace_id": "provider-workspace",
                "exp": int(time.time()) + 300,
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _verify_introspection_token("provider-token", client)

    identity = asyncio.run(run())
    assert identity.user_id == "provider-user"
    assert identity.workspace_id == "provider-workspace"


def test_introspection_rejects_inactive_token(monkeypatch) -> None:
    monkeypatch.setenv("IDENTITY_INTROSPECTION_URL", "https://identity.example.test/introspect")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"active": False})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _verify_introspection_token("inactive", client)

    try:
        asyncio.run(run())
        assert False, "Expected inactive token to be rejected"
    except HTTPException as exc:
        assert exc.status_code == 401
