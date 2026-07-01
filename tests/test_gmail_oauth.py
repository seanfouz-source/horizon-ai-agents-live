from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient


def test_gmail_oauth_start_redirects_to_google_with_render_callback(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", "shared-secret")
    monkeypatch.setattr(main_module.settings, "gmail_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "gmail_client_secret", "client-secret")
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


def test_gmail_oauth_callback_exchanges_code_and_returns_refresh_token(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", "shared-secret")
    monkeypatch.setattr(main_module.settings, "gmail_client_id", "client-id")
    monkeypatch.setattr(main_module.settings, "gmail_client_secret", "client-secret")
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
    assert "GMAIL_REFRESH_TOKEN=refresh-token" in response.text
    assert calls == [("auth-code", "https://horizon-ai-agents.onrender.com/oauth2callback", main_module.settings)]
