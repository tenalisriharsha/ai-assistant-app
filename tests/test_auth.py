"""
Regression tests for the optional password gate added for the hosted
deployment (Fly.io). Local/desktop use (no APP_PASSWORD set) must remain
completely untouched — these tests pin that contract down as much as the
"auth actually blocks things when enabled" contract.
"""
import app as app_module


def _client():
    return app_module.app.test_client()


def test_no_password_configured_leaves_app_fully_open(db, monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", None)
    client = _client()

    resp = client.get("/session")
    assert resp.get_json() == {"auth_required": False, "authenticated": True}

    resp = client.post("/query", json={"action": "today"})
    assert resp.status_code == 200


def test_query_blocked_without_login_when_password_set(db, monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "s3cret")
    client = _client()

    resp = client.get("/session")
    assert resp.get_json() == {"auth_required": True, "authenticated": False}

    resp = client.post("/query", json={"action": "today"})
    assert resp.status_code == 401


def test_wrong_password_rejected(db, monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "s3cret")
    client = _client()

    resp = client.post("/login", json={"password": "wrong"})
    assert resp.status_code == 401
    assert resp.get_json()["ok"] is False


def test_correct_password_grants_a_session_until_logout(db, monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "s3cret")
    client = _client()

    resp = client.post("/login", json={"password": "s3cret"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # Same client instance keeps the session cookie across requests.
    resp = client.get("/session")
    assert resp.get_json()["authenticated"] is True

    resp = client.post("/query", json={"action": "today"})
    assert resp.status_code == 200

    resp = client.post("/logout")
    assert resp.status_code == 200

    resp = client.post("/query", json={"action": "today"})
    assert resp.status_code == 401


def test_export_import_endpoints_also_require_auth(db, monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "s3cret")
    client = _client()

    assert client.get("/export").status_code == 401
    assert client.post("/import", json={"appointments": []}).status_code == 401


def test_health_endpoint_never_requires_auth(db, monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "s3cret")
    client = _client()

    assert client.get("/health").status_code == 200
