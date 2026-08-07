import json
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Product
from app.main import app
from app.services.auth import Identity, issue_token
from app.services.runtime import SlidingWindowRateLimiter
from app.services.settings import Settings


client = TestClient(app)


def headers() -> dict[str, str]:
    suffix = str(uuid4())
    token = issue_token(Identity(user_id=f"hardening-{suffix}", workspace_id=f"space-{suffix}"))
    return {"Authorization": f"Bearer {token}"}


def test_security_headers_and_request_id_are_applied() -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "test-request-1234"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-1234"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_invalid_request_id_is_replaced() -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "bad id"})
    assert response.headers["X-Request-ID"] != "bad id"
    assert len(response.headers["X-Request-ID"]) == 36


def test_rate_limiter_has_deterministic_retry_window() -> None:
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    assert limiter.allow("user", now=100) == (True, 0)
    assert limiter.allow("user", now=101) == (True, 0)
    allowed, retry_after = limiter.allow("user", now=102)
    assert allowed is False
    assert retry_after == 58
    assert limiter.allow("user", now=161) == (True, 0)


def test_production_configuration_fails_closed() -> None:
    unsafe = replace(
        Settings.from_env(),
        app_env="production",
        database_url="sqlite:///work/copilots.db",
        auth_mode="local",
        identity_introspection_url="http://identity.example.test/introspect",
        assistant_provider="openai",
        openai_api_key="",
    )
    with pytest.raises(RuntimeError) as exc:
        unsafe.validate()
    message = str(exc.value)
    assert "PostgreSQL" in message
    assert "introspection" in message
    assert "OPENAI_API_KEY" in message


def test_public_demo_configuration_requires_isolated_guest_auth_and_explicit_hosts() -> None:
    unsafe = replace(
        Settings.from_env(),
        app_env="demo",
        auth_mode="local",
        app_secret="local-development-secret-change-me",
        allowed_hosts=("*",),
    )
    with pytest.raises(RuntimeError) as exc:
        unsafe.validate()
    message = str(exc.value)
    assert "AUTH_MODE must be guest" in message
    assert "APP_SECRET" in message
    assert "ALLOWED_HOSTS" in message

    safe = replace(
        unsafe,
        auth_mode="guest",
        app_secret="a-long-random-deployment-secret",
        allowed_hosts=("buildquick.co.in", "www.buildquick.co.in"),
    )
    safe.validate()
    assert safe.browser_auth_mode() == "guest"


def test_feature_settings_are_product_specific() -> None:
    configured = replace(
        Settings.from_env(), feature_tyche=True, feature_plutus=False, feature_nous=True
    )
    assert configured.feature_enabled(Product.TYCHE) is True
    assert configured.feature_enabled(Product.PLUTUS) is False
    assert configured.public_features() == {"tyche": True, "plutus": False, "nous": True}


def test_user_can_delete_only_their_conversation() -> None:
    owner_headers = headers()
    other_headers = headers()
    created = client.post(
        "/api/conversations", headers=owner_headers, json={"product": "tyche"}
    ).json()
    hidden = client.delete(f"/api/conversations/{created['id']}", headers=other_headers)
    assert hidden.status_code == 404
    deleted = client.delete(f"/api/conversations/{created['id']}", headers=owner_headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/conversations/{created['id']}", headers=owner_headers).status_code == 404


def test_assistant_audit_contains_safe_provider_trace() -> None:
    auth_headers = headers()
    created = client.post(
        "/api/conversations", headers=auth_headers, json={"product": "tyche"}
    ).json()
    response = client.post(
        f"/api/conversations/{created['id']}/messages",
        headers={**auth_headers, "X-Request-ID": "trace-request-123"},
        json={
            "content": "Improve this",
            "context": {
                "product": "tyche",
                "page": {"type": "resume", "id": "resume-1"},
                "selection": {
                    "type": "resume_bullet",
                    "ids": ["bullet-1"],
                    "excerpt": "Managed the product roadmap.",
                },
                "snapshot_version": "resume-v1",
            },
        },
    )
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert any(event["type"] == "complete" for event in events)
    audit = client.get(f"/api/conversations/{created['id']}/audit", headers=auth_headers).json()["events"]
    completed = next(event for event in audit if event["event_type"] == "message.completed")
    assert completed["data"]["provider"] == "mock"
    assert completed["data"]["model"] == "deterministic-v1"
    assert completed["data"]["prompt_version"] == "contextual-copilot-v1"
    assert completed["data"]["request_id"] == "trace-request-123"
    assert "Improve this" not in json.dumps(completed["data"])
