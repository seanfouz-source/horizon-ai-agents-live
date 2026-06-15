from email.message import EmailMessage
import json

import pytest

import app.report_email as report_email
from app.report_email import send_gmail_message
from scripts.send_daily_report_email import build_message, build_report_url, split_addresses


def test_build_report_url_uses_default_endpoint_without_date(monkeypatch):
    monkeypatch.delenv("REPORT_BASE_URL", raising=False)
    monkeypatch.delenv("REPORT_DATE", raising=False)

    assert build_report_url() == "https://horizon-ai-agents.onrender.com/webhooks/zapier/daily-report"


def test_build_report_url_adds_optional_date(monkeypatch):
    monkeypatch.setenv("REPORT_BASE_URL", "https://example.com/")
    monkeypatch.setenv("REPORT_DATE", "2026-06-14")

    assert build_report_url() == "https://example.com/webhooks/zapier/daily-report?date=2026-06-14"


def test_build_message_attaches_pdf(monkeypatch):
    monkeypatch.setenv("REPORT_EMAIL_TO", "sean.fouz@gmail.com; horizonwirelesstx@gmail.com")
    monkeypatch.setenv("REPORT_EMAIL_FROM", "reports@example.com")

    message = build_message(
        {
            "subject": "Daily report",
            "email_body": "Report body",
            "attachment_filename": "report.pdf",
        },
        b"%PDF-1.4",
    )

    assert isinstance(message, EmailMessage)
    assert message["To"] == "sean.fouz@gmail.com, horizonwirelesstx@gmail.com"
    assert message["Subject"] == "Daily report"
    assert message["From"] == "Horizon AI Agents <reports@example.com>"
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "report.pdf"
    assert attachments[0].get_content_type() == "application/pdf"


def test_split_addresses_requires_value():
    with pytest.raises(RuntimeError, match="at least one recipient"):
        split_addresses(" , ; ")


def test_send_gmail_message_refreshes_token_and_sends_raw_message(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload: bytes = b"{}"):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout=60):
        calls.append(request)
        if request.full_url == "https://oauth2.googleapis.com/token":
            return FakeResponse(json.dumps({"access_token": "ya29.test"}).encode("utf-8"))
        if request.full_url == "https://gmail.googleapis.com/gmail/v1/users/me/messages/send":
            return FakeResponse()
        raise AssertionError(request.full_url)

    monkeypatch.setattr(report_email, "urlopen", fake_urlopen)

    message = EmailMessage()
    message["To"] = "owner@example.com"
    message["From"] = "Horizon AI Agents <old@example.com>"
    message["Subject"] = "Daily report"
    message.set_content("Report body")

    send_gmail_message(
        message,
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        sender="sean.fouz@gmail.com",
    )

    assert len(calls) == 2
    token_request, gmail_request = calls
    assert b"grant_type=refresh_token" in token_request.data
    assert gmail_request.headers["Authorization"] == "Bearer ya29.test"
    body = json.loads(gmail_request.data.decode("utf-8"))
    assert body["raw"]
    assert message["From"] == "Horizon AI Agents <sean.fouz@gmail.com>"
