from email.message import EmailMessage

import pytest

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
