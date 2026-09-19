"""End-to-end checks against the HTTP surface."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from pocketmind.main import app
from pocketmind.services.session import session

PASSWORD = "a long enough master pass 9!"


@pytest.fixture
def client():
    """A client with no drive open — the state the wizard starts from."""
    with TestClient(app) as test_client:
        session.unbind()
        yield test_client
        session.unbind()


@pytest.fixture
def open_client(installation):
    """A client with the temporary installation opened."""
    with TestClient(app) as test_client:
        session.bind(installation.root)
        yield test_client
        session.unbind()


# -- unbound behaviour -----------------------------------------------------


def test_health_is_always_available(client):
    assert client.get("/health").json()["status"] == "ok"


def test_state_reports_setup_mode_without_a_drive(client):
    body = client.get("/api/state").json()
    assert body["mode"] == "setup"
    assert body["vault"]["state"] == "absent"
    assert body["network"]["telemetry"] is False


def test_data_endpoints_explain_that_no_drive_is_open(client):
    for path in ("/api/memories", "/api/documents", "/api/conversations", "/api/dashboard", "/api/settings"):
        response = client.get(path)
        assert response.status_code == 409, path
        assert "drive" in response.json()["detail"].lower()


def test_the_drive_list_never_marks_the_system_drive_eligible(client):
    for drive in client.get("/api/setup/drives").json():
        if drive["is_system_drive"]:
            assert drive["is_eligible"] is False


def test_hardware_endpoint_returns_a_usable_profile(client):
    body = client.get("/api/setup/hardware").json()
    assert body["ram_bytes"] > 0
    assert body["cpu_name"]
    assert 1 <= body["performance_stars"] <= 5


def test_recommendations_refuse_an_unknown_drive(client):
    response = client.post("/api/setup/recommendations", json={"drive_id": "Q:", "use_cases": ["assistant"]})
    assert response.status_code == 400


def test_drive_report_refuses_the_system_drive(client):
    system = next((d for d in client.get("/api/setup/drives").json() if d["is_system_drive"]), None)
    if system is None:  # pragma: no cover - every real machine has one
        pytest.skip("No system drive reported")
    response = client.post("/api/setup/drive-report", json={"drive_id": system["id"]})
    assert response.status_code == 400
    assert "starts from" in response.json()["detail"]


def test_install_refuses_an_unusable_drive(client):
    response = client.post(
        "/api/setup/install",
        json={
            "drive_id": "Q:",
            "model_id": "qwen2.5-3b-instruct-q4_k_m",
            "profile": {"display_name": "Alex", "use_cases": ["assistant"]},
            "vault_password": PASSWORD,
            "accept_model_license": True,
        },
    )
    assert response.status_code == 400


def test_password_strength_is_scored_without_being_stored(client):
    body = client.post("/api/setup/password-strength", json={"password": "short"}).json()
    assert body["label"] == "Very weak"
    assert body["long_enough"] is False
    assert body["suggestions"]


# -- security --------------------------------------------------------------


def test_a_cross_origin_write_is_blocked(client):
    response = client.post(
        "/api/setup/password-strength",
        json={"password": "whatever it is"},
        headers={"Origin": "https://not-pocketmind.example"},
    )
    assert response.status_code == 403


def test_a_same_origin_write_is_allowed(client):
    response = client.post(
        "/api/setup/password-strength",
        json={"password": "whatever it is"},
        headers={"Origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 200


# -- opened installation ---------------------------------------------------


def test_state_reports_ready_mode_with_a_drive(open_client):
    body = open_client.get("/api/state").json()
    assert body["mode"] == "ready"
    assert body["installation"]["display_name"] == "Alex"


def test_memories_round_trip(open_client):
    created = open_client.post(
        "/api/memories", json={"content": "I prefer FastAPI.", "category": "preferences", "importance": 4}
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    assert any(item["id"] == memory_id for item in open_client.get("/api/memories").json())
    assert open_client.patch(f"/api/memories/{memory_id}", json={"content": "I prefer Litestar."}).status_code == 200
    assert open_client.get("/api/memories").json()[0]["content"] == "I prefer Litestar."
    assert open_client.delete(f"/api/memories/{memory_id}").status_code == 200
    assert open_client.get("/api/memories").json() == []


def test_deleting_a_missing_memory_says_so(open_client):
    assert open_client.delete("/api/memories/9999").status_code == 404


def test_documents_upload_index_and_delete(open_client):
    response = open_client.post(
        "/api/documents",
        files={"file": ("handbook.md", io.BytesIO(b"Parental leave is six months at full pay."), "text/markdown")},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "indexed"

    documents = open_client.get("/api/documents").json()
    assert documents[0]["filename"] == "handbook.md"
    assert documents[0]["chunk_count"] >= 1

    assert open_client.delete(f"/api/documents/{documents[0]['id']}").status_code == 200
    assert open_client.get("/api/documents").json() == []


def test_unsupported_uploads_are_refused_with_guidance(open_client):
    response = open_client.post(
        "/api/documents", files={"file": ("photo.heic", io.BytesIO(b"\x00\x01"), "image/heic")}
    )
    assert response.status_code == 400
    assert "Supported" in response.json()["detail"]


def test_empty_uploads_are_refused(open_client):
    response = open_client.post("/api/documents", files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")})
    assert response.status_code == 400


def test_knowledge_summary_excludes_vault_contents(open_client):
    open_client.post("/api/memories", json={"content": "I live in Pune.", "category": "personal"})
    body = open_client.get("/api/knowledge").json()
    assert body["display_name"] == "Alex"
    assert "personal" in body["memories_by_category"]
    assert "vault" not in str(body["memories_by_category"]).lower()
    assert "never shown to the assistant" in body["note"]


def test_settings_round_trip(open_client):
    settings = open_client.get("/api/settings").json()
    settings["temperature"] = 0.25
    settings["memory_results"] = 7
    assert open_client.put("/api/settings", json=settings).status_code == 200
    assert open_client.get("/api/settings").json()["temperature"] == 0.25


def test_invalid_settings_are_rejected(open_client):
    settings = open_client.get("/api/settings").json()
    settings["temperature"] = 99
    assert open_client.put("/api/settings", json=settings).status_code == 422


def test_dashboard_reports_local_only_status(open_client):
    body = open_client.get("/api/dashboard").json()
    assert body["network"]["telemetry"] is False
    assert body["storage_total_bytes"] > 0


def test_chat_without_an_engine_fails_with_a_readable_message(open_client):
    response = open_client.post("/api/chat", json={"message": "Hello there"})
    assert response.status_code == 503
    detail = response.json()["detail"].lower()
    assert "model" in detail or "engine" in detail


# -- vault over HTTP -------------------------------------------------------


def test_vault_lifecycle_through_the_api(open_client):
    assert open_client.get("/api/vault/status").json()["state"] == "absent"

    created = open_client.post("/api/vault/create", json={"password": PASSWORD})
    assert created.status_code == 201
    token = created.json()["session_token"]
    headers = {"X-Vault-Session": token}

    assert open_client.post(
        "/api/vault/entries", json={"name": "api key", "value": "sk-secret", "note": "work"}, headers=headers
    ).status_code == 201

    entries = open_client.get("/api/vault/entries", headers=headers).json()
    assert [entry["name"] for entry in entries] == ["api key"]

    revealed = open_client.post("/api/vault/entries/api key/reveal", headers=headers).json()
    assert revealed["value"] == "sk-secret"

    open_client.post("/api/vault/lock")
    assert open_client.get("/api/vault/entries", headers=headers).status_code == 423

    unlocked = open_client.post("/api/vault/unlock", json={"password": PASSWORD})
    assert unlocked.status_code == 200
    assert open_client.get(
        "/api/vault/entries", headers={"X-Vault-Session": unlocked.json()["session_token"]}
    ).status_code == 200


def test_vault_rejects_a_weak_master_password(open_client):
    response = open_client.post("/api/vault/create", json={"password": "aaaaaaaaaaaa"})
    assert response.status_code == 400
    assert "stronger" in response.json()["detail"]


def test_vault_rejects_a_wrong_password(open_client):
    open_client.post("/api/vault/create", json={"password": PASSWORD})
    open_client.post("/api/vault/lock")
    response = open_client.post("/api/vault/unlock", json={"password": "a different one entirely!"})
    assert response.status_code == 401


def test_vault_operations_require_the_session_token(open_client):
    open_client.post("/api/vault/create", json={"password": PASSWORD})
    assert open_client.get("/api/vault/entries").status_code == 401
    assert open_client.get("/api/vault/entries", headers={"X-Vault-Session": "guessed"}).status_code == 401


def test_an_unexpected_error_still_returns_a_readable_json_detail(installation, monkeypatch):
    """A bare 500 renders as 'Request failed (500)' and helps nobody."""

    def explode():
        raise ValueError("something deep broke")

    # raise_server_exceptions=False makes the client behave like a real browser,
    # which sees the response rather than the exception.
    with TestClient(app, raise_server_exceptions=False) as client:
        session.bind(installation.root)
        monkeypatch.setattr(session, "storage_usage", explode)
        response = client.get("/api/dashboard")
        session.unbind()

    assert response.status_code == 500
    body = response.json()
    assert "ValueError" in body["detail"]
    assert "logs" in body["hint"]


def test_the_openapi_schema_builds(client):
    """Catches route/model mismatches across the whole API in one go."""
    schema = client.get("/openapi.json").json()
    assert len(schema["paths"]) > 40
