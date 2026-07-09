from urllib.parse import parse_qs, urlparse
import json

from fastapi.testclient import TestClient


def test_gmail_oauth_start_redirects_to_google_with_render_callback(monkeypatch, tmp_path):
    import app.main as main_module

    credentials_file = tmp_path / "client_secret_google.json"
    credentials_file.write_text(
        json.dumps({"web": {"client_id": "client-id", "client_secret": "client-secret"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", "shared-secret")
    monkeypatch.setattr(main_module.settings, "gmail_client_credentials_file", credentials_file)
    monkeypatch.setattr(main_module.settings, "gmail_sender", "sean.fouz@gmail.com")
    monkeypatch.setattr(main_module.settings, "public_base_url", "https://horizon-ai-agents.onrender.com")

    client = TestClient(main_module.app)
    response = client.get("/gmail/oauth/start?secret=shared-secret", follow_redirects=False)

    assert response.status_code == 302
    redirect_url = urlparse(response.headers["location"])
    query = parse_qs(redirect_url.query)
    assert redirect_url.netloc == "accounts.google.com"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://horizon-ai-agents.onrender.com/oauth2callback"]
    assert query["scope"] == ["https://www.googleapis.com/auth/gmail.send"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["login_hint"] == ["sean.fouz@gmail.com"]
    assert main_module._verify_gmail_oauth_state(query["state"][0]) is True


def test_gmail_oauth_callback_exchanges_code_and_returns_refresh_token(monkeypatch, tmp_path):
    import app.main as main_module

    credentials_file = tmp_path / "client_secret_google.json"
    credentials_file.write_text(
        json.dumps({"web": {"client_id": "client-id", "client_secret": "client-secret"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", "shared-secret")
    monkeypatch.setattr(main_module.settings, "gmail_client_credentials_file", credentials_file)
    monkeypatch.setattr(main_module.settings, "public_base_url", "https://horizon-ai-agents.onrender.com")

    calls = []

    def fake_exchange_gmail_authorization_code(*, code, redirect_uri, settings):
        calls.append((code, redirect_uri, settings))
        return {"refresh_token": "refresh-token"}

    monkeypatch.setattr(main_module, "exchange_gmail_authorization_code", fake_exchange_gmail_authorization_code)

    state = main_module._sign_gmail_oauth_state()
    client = TestClient(main_module.app)
    response = client.get("/oauth2callback", params={"code": "auth-code", "state": state})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "GMAIL_REFRESH_TOKEN_CURRENT=refresh-token" in response.text
    assert calls == [("auth-code", "https://horizon-ai-agents.onrender.com/oauth2callback", main_module.settings)]


def test_gmail_oauth_status_reports_safe_diagnostics(monkeypatch, tmp_path):
    import app.main as main_module

    client_id = "225009040001-abcdef.apps.googleusercontent.com"
    credentials_file = tmp_path / "client_secret_google.json"
    credentials_file.write_text(
        json.dumps({"web": {"client_id": client_id, "client_secret": "client-secret"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", "shared-secret")
    monkeypatch.setattr(main_module.settings, "gmail_client_credentials_file", credentials_file)
    monkeypatch.setattr(main_module.settings, "gmail_sender", "sean.fouz@gmail.com")
    monkeypatch.setattr(main_module.settings, "report_email_provider", "gmail")
    monkeypatch.setattr(main_module.settings, "public_base_url", "https://horizon-ai-agents.onrender.com")
    monkeypatch.setattr(main_module.settings, "gmail_refresh_token_current", "GMAIL_REFRESH_TOKEN_CURRENT=fresh-token")

    calls = []

    def fake_gmail_access_token(*, client_id, client_secret, refresh_token):
        calls.append((client_id, client_secret, refresh_token))
        return "ya29.test"

    monkeypatch.setattr(main_module, "gmail_access_token", fake_gmail_access_token)

    client = TestClient(main_module.app)
    response = client.get("/gmail/oauth/status?secret=shared-secret&test_refresh=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_email_provider"] == "gmail"
    assert payload["gmail_sender"] == "sean.fouz@gmail.com"
    assert payload["gmail_client_id_hint"] == "225009...nt.com"
    assert payload["gmail_client_id_sha256"] == main_module._diagnostic_sha256(client_id)
    assert payload["gmail_refresh_token_current_present"] is True
    assert payload["gmail_refresh_token_current_length"] == len("fresh-token")
    assert payload["gmail_refresh_token_current_sha256"] == main_module._diagnostic_sha256("fresh-token")
    assert payload["gmail_refresh_token_current_has_assignment_prefix"] is True
    assert payload["refresh_test"] == {"status": "ok"}
    assert "fresh-token" not in response.text
    assert "client-secret" not in response.text
    assert calls == [(client_id, "client-secret", "GMAIL_REFRESH_TOKEN_CURRENT=fresh-token")]
