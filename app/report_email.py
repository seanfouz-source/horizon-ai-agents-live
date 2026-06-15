from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol


class ReportEmailError(RuntimeError):
    pass


class EmailSettings(Protocol):
    report_email_to: str
    report_email_from: str | None
    report_email_from_name: str
    smtp_host: str | None
    smtp_port: int
    smtp_security: str
    smtp_username: str | None
    smtp_password: str | None


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
        from_address=settings.report_email_from,
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
    send_message(
        message,
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        security=settings.smtp_security,
    )


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
