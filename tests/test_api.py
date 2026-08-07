from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import Identity, issue_token
from app.services.store import SQLiteStore
from datetime import datetime, timedelta, timezone
import pytest


client = TestClient(app)
AUTH_HEADERS = {"Authorization": f"Bearer {issue_token(Identity('test-user', 'workspace-1'))}"}
OTHER_AUTH_HEADERS = {"Authorization": f"Bearer {issue_token(Identity('other-user', 'workspace-2'))}"}


def tyche_context(version: str = "resume-v1") -> dict:
    return {
        "product": "tyche",
        "page": {"type": "resume", "id": "resume-1", "label": "Product résumé"},
        "selection": {
            "type": "resume_bullet",
            "ids": ["bullet-1"],
            "label": "Selected résumé bullet",
            "excerpt": "Managed the product roadmap.",
        },
        "authorised_resources": [{"id": "resume-1", "type": "resume", "label": "Product résumé"}],
        "snapshot_version": version,
    }


def create_conversation(product: str = "tyche") -> str:
    response = client.post("/api/conversations", json={"product": product}, headers=AUTH_HEADERS)
    assert response.status_code == 201
    return response.json()["id"]


def parse_ndjson(response) -> list[dict]:
    return [__import__("json").loads(line) for line in response.text.splitlines() if line]


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_checks_the_store() -> None:
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_streamed_message_includes_evidence_and_proposal() -> None:
    conversation_id = create_conversation()
    response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "Make this more senior", "context": tyche_context()},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    events = parse_ndjson(response)
    completed = next(event for event in events if event["type"] == "complete")
    message = completed["message"]
    assert message["evidence"]
    assert message["proposals"][0]["diff"]["original"] == "Managed the product roadmap."


def test_context_product_must_match_conversation() -> None:
    conversation_id = create_conversation("plutus")
    response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "Explain this", "context": tyche_context()},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 409


def test_proposal_rejects_stale_source_version() -> None:
    conversation_id = create_conversation()
    message_response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "Rewrite this", "context": tyche_context()},
        headers=AUTH_HEADERS,
    )
    completed = next(event for event in parse_ndjson(message_response) if event["type"] == "complete")
    proposal_id = completed["message"]["proposals"][0]["id"]
    response = client.post(
        f"/api/proposals/{proposal_id}",
        json={"action": "apply", "source_version": "stale-version"},
        headers={**AUTH_HEADERS, "Idempotency-Key": "stale-apply"},
    )
    assert response.status_code == 409


def test_proposal_apply_is_audited() -> None:
    conversation_id = create_conversation()
    message_response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "Rewrite this", "context": tyche_context()},
        headers=AUTH_HEADERS,
    )
    completed = next(event for event in parse_ndjson(message_response) if event["type"] == "complete")
    proposal = completed["message"]["proposals"][0]
    apply_response = client.post(
        f"/api/proposals/{proposal['id']}",
        json={"action": "apply", "source_version": proposal["source_version"]},
        headers={**AUTH_HEADERS, "Idempotency-Key": "apply-1"},
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["proposal"]["status"] == "applied"
    audit = client.get(
        f"/api/conversations/{conversation_id}/audit", headers=AUTH_HEADERS
    ).json()["events"]
    assert any(event["event_type"] == "proposal.apply" for event in audit)


def test_authentication_is_required() -> None:
    response = client.post("/api/conversations", json={"product": "tyche"})
    assert response.status_code == 401


def test_conversation_is_hidden_from_other_workspace() -> None:
    conversation_id = create_conversation()
    response = client.get(
        f"/api/conversations/{conversation_id}", headers=OTHER_AUTH_HEADERS
    )
    assert response.status_code == 404


def test_apply_is_idempotent() -> None:
    conversation_id = create_conversation()
    message_response = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"content": "Rewrite this", "context": tyche_context()},
        headers=AUTH_HEADERS,
    )
    completed = next(event for event in parse_ndjson(message_response) if event["type"] == "complete")
    proposal = completed["message"]["proposals"][0]
    payload = {"action": "apply", "source_version": proposal["source_version"]}
    headers = {**AUTH_HEADERS, "Idempotency-Key": "same-operation"}
    first = client.post(f"/api/proposals/{proposal['id']}", json=payload, headers=headers)
    second = client.post(f"/api/proposals/{proposal['id']}", json=payload, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent_replay"] is True


def test_sqlite_store_survives_reopen(tmp_path) -> None:
    database = tmp_path / "copilots.db"
    first_store = SQLiteStore(database)
    from app.domain.models import Conversation, Product

    original = Conversation(
        product=Product.TYCHE,
        workspace_id="workspace-1",
        owner_user_id="test-user",
        title="Persistent conversation",
    )
    first_store.save_conversation(original)
    first_store.close()

    reopened_store = SQLiteStore(database)
    restored = reopened_store.get_conversation(original.id)
    reopened_store.close()
    assert restored is not None
    assert restored.title == "Persistent conversation"


def test_expired_guest_cleanup_deletes_owned_data(tmp_path) -> None:
    database = tmp_path / "retention.db"
    retention_store = SQLiteStore(database)
    from app.domain.models import Conversation, Product

    expired = Conversation(product=Product.TYCHE, workspace_id="guest-expired", owner_user_id="guest-expired")
    active = Conversation(product=Product.TYCHE, workspace_id="guest-active", owner_user_id="guest-active")
    retention_store.save_conversation(expired)
    retention_store.save_conversation(active)
    now = datetime.now(timezone.utc)
    retention_store.register_guest_workspace("guest-expired", now - timedelta(minutes=1))
    retention_store.register_guest_workspace("guest-active", now + timedelta(hours=1))

    assert retention_store.delete_expired_guest_workspaces(now) == 1
    assert retention_store.get_conversation(expired.id) is None
    assert retention_store.get_conversation(active.id) is not None
    retention_store.close()


def test_readiness_requires_current_schema(tmp_path) -> None:
    database = tmp_path / "unmigrated.db"
    unmigrated = SQLiteStore(database, migrate_on_startup=False)
    with pytest.raises(Exception):
        unmigrated.ping()
    unmigrated.migrate()
    unmigrated.ping()
    unmigrated.close()
