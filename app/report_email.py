from __future__ import annotations

import os
import smtplib
import ssl
import base64
import json
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ReportEmailError(RuntimeError):
    pass


class EmailSettings(Protocol):
    report_email_to: str
    report_email_provider: str
    report_email_from: str | None
    report_email_from_name: str
    smtp_host: str | None
    smtp_port: int
    smtp_security: str
    smtp_username: str | None
    smtp_password: str | None
    gmail_sender: str | None
    gmail_client_id: str | None
    gmail_client_secret: str | None
    gmail_refresh_token: str | None


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str = ""


def build_message(
    report: dict[str, object],
    pdf_bytes: bytes,
    *,
    recipients: str | None = None,
    from_address: str | None = None,
    from_name: str | None = None,
    smtp_username: str | None = None,
) -> EmailMessage:
    to_addresses = split_addresses(recipients or required_env("REPORT_EMAIL_TO"))
    sender = from_address or os.getenv("REPORT_EMAIL_FROM") or smtp_username or os.getenv("SMTP_USERNAME")
    if not sender:
        raise ReportEmailError("REPORT_EMAIL_FROM or SMTP_USERNAME is required")

    subject = require_report_field(report, "subject")
    body = require_report_field(report, "email_body")
    filename = require_report_field(report, "attachment_filename")

    message = EmailMessage()
    message["To"] = ", ".join(to_addresses)
    message["From"] = formataddr((from_name or os.getenv("REPORT_EMAIL_FROM_NAME", "Horizon AI Agents"), sender))
    message["Subject"] = subject
    message.set_content(body)
    message.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
    return message


def build_message_from_settings(report: dict[str, object], pdf_bytes: bytes, settings: EmailSettings) -> EmailMessage:
    return build_message(
        report,
        pdf_bytes,
        recipients=settings.report_email_to,
        from_address=_from_address_from_settings(settings),
        from_name=settings.report_email_from_name,
        smtp_username=settings.smtp_username,
    )


def send_message(
    message: EmailMessage,
    *,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    security: str | None = None,
) -> None:
    config = smtp_config(host=host, port=port, username=username, password=password, security=security)

    if config.security == "ssl":
        with smtplib.SMTP_SSL(config.host, config.port, context=ssl.create_default_context(), timeout=60) as smtp:
            smtp_login(smtp, config.username, config.password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(config.host, config.port, timeout=60) as smtp:
        if config.security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        smtp_login(smtp, config.username, config.password)
        smtp.send_message(message)


def send_message_from_settings(message: EmailMessage, settings: EmailSettings) -> None:
    provider = settings.report_email_provider.strip().lower()
    if provider == "gmail":
        send_gmail_message(
            message,
            client_id=settings.gmail_client_id,
            client_secret=settings.gmail_client_secret,
            refresh_token=settings.gmail_refresh_token,
            sender=settings.gmail_sender or settings.report_email_from,
        )
        return
    if provider != "smtp":
        raise ReportEmailError("REPORT_EMAIL_PROVIDER must be smtp or gmail")

    send_message(
        message,
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        security=settings.smtp_security,
    )


def send_gmail_message(
    message: EmailMessage,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    refresh_token: str | None = None,
    sender: str | None = None,
) -> None:
    sender_address = (sender or "").strip()
    if not sender_address:
        raise ReportEmailError("GMAIL_SENDER or REPORT_EMAIL_FROM is required")
    message.replace_header("From", formataddr((_from_display_name(message), sender_address)))
    access_token = gmail_access_token(client_id=client_id, client_secret=client_secret, refresh_token=refresh_token)
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
    request = Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        data=json.dumps({"raw": raw_message}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            response.read()
    except Exception as exc:
        raise ReportEmailError(f"Gmail API send failed: {exc}") from exc


def gmail_access_token(
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    refresh_token: str | None = None,
) -> str:
    resolved_client_id = (client_id or os.getenv("GMAIL_CLIENT_ID", "")).strip()
    resolved_client_secret = (client_secret or os.getenv("GMAIL_CLIENT_SECRET", "")).strip()
    resolved_refresh_token = (refresh_token or os.getenv("GMAIL_REFRESH_TOKEN", "")).strip()
    if not resolved_client_id:
        raise ReportEmailError("GMAIL_CLIENT_ID is required")
    if not resolved_client_secret:
        raise ReportEmailError("GMAIL_CLIENT_SECRET is required")
    if not resolved_refresh_token:
        raise ReportEmailError("GMAIL_REFRESH_TOKEN is required")

    request = Request(
        "https://oauth2.googleapis.com/token",
        data=urlencode(
            {
                "client_id": resolved_client_id,
                "client_secret": resolved_client_secret,
                "refresh_token": resolved_refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise ReportEmailError(f"Gmail OAuth token refresh failed: {exc}") from exc

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ReportEmailError("Gmail OAuth response did not include an access token")
    return access_token


def _from_address_from_settings(settings: EmailSettings) -> str | None:
    if settings.report_email_provider.strip().lower() == "gmail":
        return settings.gmail_sender or settings.report_email_from or "sean.fouz@gmail.com"
    return settings.report_email_from


def _from_display_name(message: EmailMessage) -> str:
    from_header = message.get("From", "")
    if "<" in from_header:
        return from_header.split("<", 1)[0].strip().strip('"')
    return "Horizon AI Agents"


def smtp_config(
    *,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    security: str | None = None,
) -> SmtpConfig:
    resolved_host = (host or os.getenv("SMTP_HOST", "")).strip()
    if not resolved_host:
        raise ReportEmailError("SMTP_HOST is required")

    resolved_username = username if username is not None else os.getenv("SMTP_USERNAME", "")
    resolved_password = password if password is not None else os.getenv("SMTP_PASSWORD", "")
    resolved_security = (security or os.getenv("SMTP_SECURITY", "starttls")).strip().lower()

    try:
        resolved_port = port if port is not None else int(os.getenv("SMTP_PORT", "587"))
    except ValueError as exc:
        raise ReportEmailError("SMTP_PORT must be a number") from exc

    if resolved_security not in {"starttls", "ssl", "none"}:
        raise ReportEmailError("SMTP_SECURITY must be starttls, ssl, or none")

    return SmtpConfig(
        host=resolved_host,
        port=resolved_port,
        security=resolved_security,
        username=(resolved_username or "").strip(),
        password=(resolved_password or "").strip(),
    )


def smtp_login(smtp: smtplib.SMTP, username: str, password: str) -> None:
    if username or password:
        if not username or not password:
            raise ReportEmailError("SMTP_USERNAME and SMTP_PASSWORD must be set together")
        smtp.login(username, password)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ReportEmailError(f"{name} is required")
    return value


def require_report_field(report: dict[str, object], name: str) -> str:
    value = report.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ReportEmailError(f"report field {name!r} is required")
    return value


def split_addresses(value: str) -> list[str]:
    addresses = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    if not addresses:
        raise ReportEmailError("REPORT_EMAIL_TO must include at least one recipient")
    return addresses


def env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}
