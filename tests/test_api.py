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
def test_api_rejects_non_integer_or_out_of_range_money(client, amount):
    response = client.post(
        "/api/transfers",
        json={**PAYLOAD, "amount_minor": amount},
        headers={"Idempotency-Key": "invalid"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("key", [None, "", "space in key", "x" * 129])
def test_api_requires_valid_idempotency_header(client, key):
    headers = {} if key is None else {"Idempotency-Key": key}
    assert client.post("/api/transfers", json=PAYLOAD, headers=headers).status_code == 422


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


