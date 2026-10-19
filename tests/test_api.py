import pytest

PAYLOAD = {
    "source_account_id": "demo-operating",
    "destination_account_id": "demo-payments",
    "amount_minor": 1250,
    "reference": "API settlement",
}


def test_api_transfer_and_replay_contract(client):
    first = client.post("/api/transfers", json=PAYLOAD, headers={"Idempotency-Key": "api-key"})
    second = client.post("/api/transfers", json=PAYLOAD, headers={"Idempotency-Key": "api-key"})
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.headers["Idempotent-Replayed"] == "false"
    assert second.headers["Idempotent-Replayed"] == "true"


def test_conflicting_key_returns_structured_error(client):
    client.post("/api/transfers", json=PAYLOAD, headers={"Idempotency-Key": "conflict"})
    response = client.post(
        "/api/transfers",
        json={**PAYLOAD, "amount_minor": 1},
        headers={"Idempotency-Key": "conflict"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "idempotency_conflict"


@pytest.mark.parametrize("amount", [0, -10, 1.5, True, "100", 1_000_000_000_001])
def test_account_creation_and_statement(client):
    response = client.post("/api/accounts", json={"name": "New reserve", "currency": "GBP"})
    assert response.status_code == 201
    account = response.json()
    assert account["balance_minor"] == 0
    entries = client.get(f"/api/accounts/{account['id']}/entries").json()
    assert entries == {"items": [], "balance_minor": 0}
    assert client.get("/api/accounts/missing/entries").status_code == 404


def test_no_public_funding_endpoint_or_implicit_extra_fields(client):
    response = client.post("/api/accounts", json={"name": "Bad", "initial_balance_minor": 10000})
    assert response.status_code == 422


def test_serves_dashboard_and_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200 and "ClearLedger" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/api/summary").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_pagination_is_bounded(client, query):
    assert client.get(f"/api/transfers?{query}").status_code == 422
