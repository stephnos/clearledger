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
