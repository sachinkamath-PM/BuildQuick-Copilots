import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth import Identity, issue_token


client = TestClient(app)


def identity_headers() -> dict[str, str]:
    suffix = str(uuid4())
    token = issue_token(Identity(user_id=f"plutus-user-{suffix}", workspace_id=f"plutus-space-{suffix}"))
    return {"Authorization": f"Bearer {token}"}


def conversation(headers: dict[str, str]) -> dict:
    response = client.post("/api/conversations", headers=headers, json={"product": "plutus"})
    assert response.status_code == 201
    return response.json()


def complete_message(response) -> dict:
    events = [json.loads(line) for line in response.text.splitlines() if line]
    return next(event["message"] for event in events if event["type"] == "complete")


def grounded_context() -> dict:
    return {
        "product": "plutus",
        "page": {"type": "financial_dashboard", "id": "client-supplied"},
        "filters": {"grounded_workspace": True},
        "date_range": {"start": "2000-01-01", "end": "2000-01-02"},
        "snapshot_version": "untrusted-client-version",
    }


def accounts_csv() -> bytes:
    return (
        "id,name,account_type,owner,balance,previous_balance,currency\n"
        "cash-main,Main Bank,bank,Family,725000,680000,INR\n"
        "home-loan,Home Loan,loan,Family,-1250000,-1320000,INR\n"
    ).encode()


def transactions_csv() -> bytes:
    return (
        "id,account_id,date,merchant,category,amount\n"
        "tx-apr,cash-main,2026-04-05,Stream Box,Subscriptions,799\n"
        "tx-may,cash-main,2026-05-05,Stream Box,Subscriptions,799\n"
        "tx-jun,cash-main,2026-06-05,Stream Box,Subscriptions,799\n"
        "tx-jul,cash-main,2026-07-05,Stream Box,Subscriptions,799\n"
        "tx-aug,cash-main,2026-08-05,Stream Box,Subscriptions,799\n"
        "tx-food,cash-main,2026-08-10,Fresh Basket,Groceries,9500\n"
        "tx-metro-jul,cash-main,2026-07-12,Metro Rail,Travel,1800\n"
        "tx-metro-aug,cash-main,2026-08-12,Metro Rail,Travel,2100\n"
        "tx-flight,cash-main,2026-09-02,International Air,Travel,75000\n"
    ).encode()


def test_analysis_reconciles_accounts_and_classifies_findings() -> None:
    headers = identity_headers()
    response = client.get("/api/plutus/workspace", headers=headers)
    assert response.status_code == 200
    workspace = response.json()["workspace"]
    analysis = workspace["analysis"]
    assert analysis["net_worth"] == sum(account["balance"] for account in workspace["accounts"])
    assert analysis["previous_net_worth"] == sum(
        account["previous_balance"] for account in workspace["accounts"]
    )
    assert analysis["net_worth_change"] == -290_000
    assert {item["merchant"] for item in analysis["subscriptions"]} == {"Adobe", "Netflix"}
    assert [item["transaction_id"] for item in analysis["anomalies"]] == ["tx-tr-jun"]
    statuses = {item["status"] for item in analysis["coverage_gaps"]}
    assert statuses == {"confirmed_missing", "data_incomplete"}


def test_csv_import_atomically_replaces_records_and_selects_latest_quarter() -> None:
    headers = identity_headers()
    imported = client.post(
        "/api/plutus/import",
        headers=headers,
        files={
            "accounts_file": ("accounts.csv", accounts_csv(), "text/csv"),
            "transactions_file": ("transactions.csv", transactions_csv(), "text/csv"),
        },
    )
    assert imported.status_code == 200
    workspace = imported.json()["workspace"]
    assert workspace["data_source"] == "csv"
    assert workspace["version"] == 2
    assert workspace["last_import"]["account_rows"] == 2
    assert workspace["last_import"]["transaction_rows"] == 9
    assert workspace["analysis"]["period_start"] == "2026-07-01"
    assert workspace["analysis"]["period_end"] == "2026-09-30"
    assert workspace["analysis"]["previous_period_start"] == "2026-04-01"
    assert workspace["analysis"]["net_worth"] == -525_000
    assert workspace["analysis"]["previous_net_worth"] == -640_000
    assert {item["merchant"] for item in workspace["analysis"]["subscriptions"]} == {"Stream Box"}
    assert any(item["transaction_id"] == "tx-flight" for item in workspace["analysis"]["anomalies"])


def test_rejected_csv_import_leaves_existing_workspace_untouched() -> None:
    headers = identity_headers()
    before = client.get("/api/plutus/workspace", headers=headers).json()["workspace"]
    invalid_transactions = (
        "id,account_id,date,merchant,category,amount\n"
        "tx-1,missing-account,2026-08-01,Merchant,Household,500\n"
    ).encode()
    rejected = client.post(
        "/api/plutus/import",
        headers=headers,
        files={
            "accounts_file": ("accounts.csv", accounts_csv(), "text/csv"),
            "transactions_file": ("transactions.csv", invalid_transactions, "text/csv"),
        },
    )
    assert rejected.status_code == 422
    assert "unknown account ids" in rejected.json()["detail"]
    after = client.get("/api/plutus/workspace", headers=headers).json()["workspace"]
    assert after["version"] == before["version"]
    assert after["accounts"] == before["accounts"]
    assert after["transactions"] == before["transactions"]


def test_csv_validation_reports_row_and_template_downloads_require_auth() -> None:
    headers = identity_headers()
    positive_loan = (
        "id,name,account_type,owner,balance,previous_balance,currency\n"
        "loan,Loan,loan,Family,1000,-2000,INR\n"
    ).encode()
    rejected = client.post(
        "/api/plutus/import",
        headers=headers,
        files={"accounts_file": ("accounts.csv", positive_loan, "text/csv")},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"].startswith("CSV row 2:")

    template = client.get("/api/plutus/import/templates/accounts.csv", headers=headers)
    assert template.status_code == 200
    assert template.headers["content-type"].startswith("text/csv")
    assert template.text.startswith("id,name,account_type")
    assert client.get("/api/plutus/import/templates/accounts.csv").status_code == 401


def test_chat_separates_facts_calculations_assumptions_and_guidance() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    response = client.post(
        f"/api/conversations/{convo['id']}/messages",
        headers=headers,
        json={"content": "Why did our net worth fall?", "context": grounded_context()},
    )
    assert response.status_code == 200
    message = complete_message(response)
    for heading in ("Recorded facts:", "Calculated projections:", "Assumptions:", "General guidance:"):
        assert heading in message["content"]
    assert any(item["resource_type"] == "calculation" for item in message["evidence"])
    assert message["proposals"] == []


def test_subscription_and_anomaly_answers_link_underlying_transactions() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    subscriptions = complete_message(
        client.post(
            f"/api/conversations/{convo['id']}/messages",
            headers=headers,
            json={"content": "Find subscriptions", "context": grounded_context()},
        )
    )
    assert "Netflix" in subscriptions["content"]
    assert all(item["resource_type"] == "recorded_transaction" for item in subscriptions["evidence"])

    anomaly = complete_message(
        client.post(
            f"/api/conversations/{convo['id']}/messages",
            headers=headers,
            json={"content": "Show unusual transactions", "context": grounded_context()},
        )
    )
    assert "International Air" in anomaly["content"]
    assert any(item["resource_id"] == "tx-tr-jun" for item in anomaly["evidence"])


def test_goal_scenario_is_deterministic_and_requires_apply() -> None:
    headers = identity_headers()
    convo = conversation(headers)
    request = {
        "conversation_id": convo["id"],
        "name": "Education fund",
        "target_amount": 5_000_000,
        "current_amount": 500_000,
        "target_date": "2031-08-01",
        "annual_return_rate": 0.08,
        "annual_inflation_rate": 0.05,
    }
    scenario_response = client.post("/api/plutus/scenarios", headers=headers, json=request)
    assert scenario_response.status_code == 200
    body = scenario_response.json()
    assert body["scenario"]["calculation_version"] == "goal-scenario-v1"
    assert body["scenario"]["inflation_adjusted_target"] > request["target_amount"]
    assert body["scenario"]["required_monthly_contribution"] > 0
    assert body["proposal"]["status"] == "presented"
    before = client.get("/api/plutus/workspace", headers=headers).json()["workspace"]
    assert before["goals"] == []

    proposal = body["proposal"]
    applied = client.post(
        f"/api/proposals/{proposal['id']}",
        headers={**headers, "Idempotency-Key": "create-education-goal"},
        json={"action": "apply", "source_version": proposal["source_version"]},
    )
    assert applied.status_code == 200
    workspace = applied.json()["workspace"]
    assert len(workspace["goals"]) == 1
    assert workspace["goals"][0]["name"] == "Education fund"
    assert workspace["goals"][0]["monthly_contribution"] == body["scenario"]["required_monthly_contribution"]


def test_stale_goal_proposal_cannot_mutate_workspace() -> None:
    headers = identity_headers()
    convo = conversation(headers)

    def scenario(name: str) -> dict:
        return client.post(
            "/api/plutus/scenarios",
            headers=headers,
            json={
                "conversation_id": convo["id"],
                "name": name,
                "target_amount": 1_000_000,
                "current_amount": 100_000,
                "target_date": "2030-08-01",
                "annual_return_rate": 0.06,
                "annual_inflation_rate": 0.04,
            },
        ).json()["proposal"]

    first = scenario("First")
    stale = scenario("Stale")
    first_apply = client.post(
        f"/api/proposals/{first['id']}",
        headers={**headers, "Idempotency-Key": "first-goal"},
        json={"action": "apply", "source_version": first["source_version"]},
    )
    assert first_apply.status_code == 200
    stale_apply = client.post(
        f"/api/proposals/{stale['id']}",
        headers={**headers, "Idempotency-Key": "stale-goal"},
        json={"action": "apply", "source_version": stale["source_version"]},
    )
    assert stale_apply.status_code == 409
