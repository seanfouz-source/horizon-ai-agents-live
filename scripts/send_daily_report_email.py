from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://horizon-ai-agents.onrender.com"


def main() -> int:
    try:
        report = fetch_report()
        pdf_bytes = fetch_bytes(report["attachment_url"])
        message = build_message(report, pdf_bytes)
        if env_bool("DRY_RUN"):
            print(f"Prepared report email: {message['Subject']} -> {message['To']}")
            return 0
        send_message(message)
        print(f"Sent report email: {message['Subject']} -> {message['To']}")
        return 0
    except Exception as exc:
        print(f"Failed to send report email: {exc}", file=sys.stderr)
        return 1


def fetch_report() -> dict[str, object]:
    request = Request(build_report_url(), headers=request_headers())
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def build_report_url() -> str:
    base_url = os.getenv("REPORT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    report_date = os.getenv("REPORT_DATE", "").strip()
    query = f"?{urlencode({'date': report_date})}" if report_date else ""
    return f"{base_url}/webhooks/zapier/daily-report{query}"


def request_headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    secret = os.getenv("WEBHOOK_SHARED_SECRET", "").strip()
    if secret:
        headers["x-horizon-secret"] = secret
    return headers


def fetch_bytes(url: str) -> bytes:
    request = Request(url, headers={"Accept": "application/pdf"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def build_message(report: dict[str, object], pdf_bytes: bytes) -> EmailMessage:
    recipients = split_addresses(required_env("REPORT_EMAIL_TO"))
    from_address = os.getenv("REPORT_EMAIL_FROM") or os.getenv("SMTP_USERNAME")
    if not from_address:
        raise RuntimeError("REPORT_EMAIL_FROM or SMTP_USERNAME is required")

    subject = require_report_field(report, "subject")
    body = require_report_field(report, "email_body")
    filename = require_report_field(report, "attachment_filename")

    message = EmailMessage()
    message["To"] = ", ".join(recipients)
    message["From"] = formataddr((os.getenv("REPORT_EMAIL_FROM_NAME", "Horizon AI Agents"), from_address))
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
    return message


def send_message(message: EmailMessage) -> None:
    host = required_env("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    security_mode = os.getenv("SMTP_SECURITY", "starttls").lower()

    if security_mode == "ssl":
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=60) as smtp:
            smtp_login(smtp, username, password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=60) as smtp:
        if security_mode == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        smtp_login(smtp, username, password)
        smtp.send_message(message)


def smtp_login(smtp: smtplib.SMTP, username: str, password: str) -> None:
    if username or password:
        if not username or not password:
            raise RuntimeError("SMTP_USERNAME and SMTP_PASSWORD must be set together")
        smtp.login(username, password)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def require_report_field(report: dict[str, object], name: str) -> str:
    value = report.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"report field {name!r} is required")
    return value


def split_addresses(value: str) -> list[str]:
    addresses = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    if not addresses:
        raise RuntimeError("REPORT_EMAIL_TO must include at least one recipient")
    return addresses


def env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
