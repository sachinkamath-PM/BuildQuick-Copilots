from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import Identity, issue_token


client = TestClient(app)


def identity_headers() -> dict[str, str]:
    suffix = str(uuid4())
    token = issue_token(Identity(user_id=f"nous-user-{suffix}", workspace_id=f"nous-space-{suffix}"))
    return {"Authorization": f"Bearer {token}"}


def conversation(headers: dict[str, str]) -> dict:
    response = client.post("/api/conversations", headers=headers, json={"product": "nous"})
    assert response.status_code == 201
    return response.json()


def create_plan(headers: dict[str, str], conversation_id: str) -> dict:
    response = client.post(
        "/api/nous/plans",
        headers=headers,
        json={
            "conversation_id": conversation_id,
            "objective": "Analyse last quarter customer feedback and recommend three priorities.",
        },
    )
    assert response.status_code == 201
    return response.json()


def run_to_review(headers: dict[str, str], plan_id: str) -> dict:
    started = client.post(f"/api/nous/plans/{plan_id}/start", headers=headers)
    assert started.status_code == 200
    workspace = started.json()["workspace"]
    assert workspace["plans"][-1]["steps"][0]["status"] == "running"
    for _ in range(3):
        advanced = client.post(f"/api/nous/plans/{plan_id}/advance", headers=headers)
        assert advanced.status_code == 200
        workspace = advanced.json()["workspace"]
    return workspace


def test_plan_exposes_agents_inputs_and_live_state_transitions() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    created = create_plan(headers, convo["id"])
    plan = created["plan"]
    assert plan["status"] == "draft"
    assert plan["required_inputs"] == []
    assert [step["agent_id"] for step in plan["steps"]] == [
        "agent-research",
        "agent-analysis",
        "agent-editor",
    ]

    workspace = run_to_review(headers, plan["id"])
    finished = next(item for item in workspace["plans"] if item["id"] == plan["id"])
    assert finished["status"] == "reviewable"
    assert all(step["status"] == "completed" for step in finished["steps"])
    outputs = [item for item in workspace["outputs"] if item["plan_id"] == plan["id"]]
    assert len(outputs) == 3
    assert {item["agent_id"] for item in outputs} == {
        "agent-research",
        "agent-analysis",
        "agent-editor",
    }
    assert all(item["source_ids"] for item in outputs)


def test_source_import_is_atomic_and_preserves_structured_metadata() -> None:
    headers = identity_headers()
    before = client.get("/api/nous/workspace", headers=headers).json()["workspace"]
    imported = client.post(
        "/api/nous/sources/import",
        headers=headers,
        files=[
            ("files", ("feedback.csv", b"comment,segment\nSlow reports,Enterprise\nNeed API integration,SMB\n", "text/csv")),
            ("files", ("notes.json", b'[{"theme":"pricing","count":4}]', "application/json")),
            ("files", ("interviews.txt", b"Onboarding takes too long.\nPermissions are unclear.", "text/plain")),
        ],
    )
    assert imported.status_code == 201
    body = imported.json()
    assert len(body["sources"]) == 3
    assert body["workspace"]["version"] == before["version"] + 1
    by_filename = {item["filename"]: item for item in body["sources"]}
    assert by_filename["feedback.csv"]["source_type"] == "csv_dataset"
    assert by_filename["feedback.csv"]["record_count"] == 2
    assert by_filename["notes.json"]["record_count"] == 1
    assert by_filename["interviews.txt"]["record_count"] == 2
    assert all(item["byte_size"] > 0 for item in body["sources"])


def test_plan_locks_selected_source_and_outputs_keep_exact_provenance() -> None:
    headers = identity_headers()
    imported = client.post(
        "/api/nous/sources/import",
        headers=headers,
        files=[
            (
                "files",
                (
                    "product-feedback.csv",
                    b"comment\nPerformance is slow\nAPI integration is missing\nAnother performance issue\n",
                    "text/csv",
                ),
            )
        ],
    ).json()["sources"][0]
    convo = conversation(headers)
    created = client.post(
        "/api/nous/plans",
        headers=headers,
        json={
            "conversation_id": convo["id"],
            "objective": "Analyse the selected product feedback and prepare three priorities.",
            "source_ids": [imported["id"]],
        },
    )
    assert created.status_code == 201
    plan = created.json()["plan"]
    assert plan["source_ids"] == [imported["id"]]
    workspace = run_to_review(headers, plan["id"])
    outputs = [item for item in workspace["outputs"] if item["plan_id"] == plan["id"]]
    assert all(item["source_ids"] == [imported["id"]] for item in outputs)
    analysis = next(item for item in outputs if item["agent_id"] == "agent-analysis")
    assert "performance" in analysis["content"]
    assert "integrations" in analysis["content"]


def test_invalid_source_batch_and_duplicate_leave_workspace_unchanged() -> None:
    headers = identity_headers()
    before = client.get("/api/nous/workspace", headers=headers).json()["workspace"]
    rejected = client.post(
        "/api/nous/sources/import",
        headers=headers,
        files=[
            ("files", ("valid.txt", b"Useful feedback", "text/plain")),
            ("files", ("broken.json", b'{"missing":', "application/json")),
        ],
    )
    assert rejected.status_code == 422
    unchanged = client.get("/api/nous/workspace", headers=headers).json()["workspace"]
    assert unchanged["version"] == before["version"]
    assert unchanged["sources"] == before["sources"]

    first = client.post(
        "/api/nous/sources/import",
        headers=headers,
        files=[("files", ("first.txt", b"Same source content", "text/plain"))],
    )
    assert first.status_code == 201
    duplicate = client.post(
        "/api/nous/sources/import",
        headers=headers,
        files=[("files", ("renamed.txt", b"Same source content", "text/plain"))],
    )
    assert duplicate.status_code == 409
    after = client.get("/api/nous/workspace", headers=headers).json()["workspace"]
    assert len(after["sources"]) == len(before["sources"]) + 1


def test_plan_with_explicitly_empty_source_selection_cannot_start() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    created = client.post(
        "/api/nous/plans",
        headers=headers,
        json={
            "conversation_id": convo["id"],
            "objective": "Prepare a source-grounded brief.",
            "source_ids": [],
        },
    )
    assert created.status_code == 201
    plan = created.json()["plan"]
    assert plan["required_inputs"] == ["At least one authorised source"]
    assert client.post(f"/api/nous/plans/{plan['id']}/start", headers=headers).status_code == 409


def test_external_action_cannot_be_proposed_before_review() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    plan = create_plan(headers, convo["id"])["plan"]
    response = client.post(
        f"/api/nous/plans/{plan['id']}/external-actions",
        headers=headers,
        json={
            "conversation_id": convo["id"],
            "kind": "publish",
            "destination": "Strategy review workspace",
        },
    )
    assert response.status_code == 409


def test_external_action_preview_requires_explicit_apply_and_does_not_execute_connector() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    plan = create_plan(headers, convo["id"])["plan"]
    workspace = run_to_review(headers, plan["id"])
    action_response = client.post(
        f"/api/nous/plans/{plan['id']}/external-actions",
        headers=headers,
        json={
            "conversation_id": convo["id"],
            "kind": "publish",
            "destination": "Strategy review workspace",
        },
    )
    assert action_response.status_code == 201
    action_body = action_response.json()
    assert action_body["action"]["status"] == "proposed"
    assert action_body["proposal"]["payload"]["destination"] == "Strategy review workspace"
    assert "Recommended priorities" in action_body["proposal"]["payload"]["content_preview"]

    before = client.get("/api/nous/workspace", headers=headers).json()["workspace"]
    assert before["external_actions"][-1]["status"] == "proposed"
    assert next(item for item in before["plans"] if item["id"] == plan["id"])["status"] == "reviewable"

    proposal = action_body["proposal"]
    applied = client.post(
        f"/api/proposals/{proposal['id']}",
        headers={**headers, "Idempotency-Key": "approve-publish"},
        json={"action": "apply", "source_version": proposal["source_version"]},
    )
    assert applied.status_code == 200
    approved = applied.json()["workspace"]
    assert approved["external_actions"][-1]["status"] == "approved"
    assert next(item for item in approved["plans"] if item["id"] == plan["id"])["status"] == "completed"
    assert all(action["status"] != "executed" for action in approved["external_actions"])


def test_cancelled_action_remains_unexecuted() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    plan = create_plan(headers, convo["id"])["plan"]
    run_to_review(headers, plan["id"])
    action_body = client.post(
        f"/api/nous/plans/{plan['id']}/external-actions",
        headers=headers,
        json={
            "conversation_id": convo["id"],
            "kind": "send",
            "destination": "Product leadership email list",
        },
    ).json()
    proposal = action_body["proposal"]
    cancelled = client.post(
        f"/api/proposals/{proposal['id']}",
        headers=headers,
        json={"action": "cancel", "source_version": proposal["source_version"]},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["workspace"]["external_actions"][-1]["status"] == "cancelled"


def test_plan_progress_and_approval_are_audited() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    plan = create_plan(headers, convo["id"])["plan"]
    run_to_review(headers, plan["id"])
    audit = client.get(f"/api/conversations/{convo['id']}/audit", headers=headers).json()["events"]
    event_types = [event["event_type"] for event in audit]
    assert "nous.plan.created" in event_types
    assert "nous.plan.started" in event_types
    assert event_types.count("nous.plan.progressed") == 3
