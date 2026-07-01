from __future__ import annotations

import os
import smtplib
import ssl
import base64
import json
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_RENDER_GMAIL_CREDENTIALS_FILE = Path(
    "/etc/secrets/client_secret_225009040001-55c5hksat2o9pf35emqvprb3kkti746j.apps.googleusercontent.com.json"
)


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
    gmail_client_credentials_file: Path | str | None
    gmail_refresh_token_current: str | None


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str = ""


@dataclass(frozen=True)
class GmailOAuthCredentials:
    client_id: str
    client_secret: str


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
        credentials = gmail_oauth_credentials(settings=settings)
        send_gmail_message(
            message,
            client_id=credentials.client_id,
            client_secret=credentials.client_secret,
            refresh_token=settings.gmail_refresh_token_current,
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
    except HTTPError as exc:
        raise ReportEmailError(f"Gmail API send failed: {_http_error_detail(exc)}") from exc
    except Exception as exc:
        raise ReportEmailError(f"Gmail API send failed: {exc}") from exc


def gmail_access_token(
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    refresh_token: str | None = None,
) -> str:
    credentials = gmail_oauth_credentials(client_id=client_id, client_secret=client_secret)
    resolved_refresh_token = (refresh_token or os.getenv("GMAIL_REFRESH_TOKEN_CURRENT", "")).strip()
    if not resolved_refresh_token:
        raise ReportEmailError("GMAIL_REFRESH_TOKEN_CURRENT is required")

    request = Request(
        "https://oauth2.googleapis.com/token",
        data=urlencode(
            {
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
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
    except HTTPError as exc:
        raise ReportEmailError(f"Gmail OAuth token refresh failed: {_http_error_detail(exc)}") from exc
    except Exception as exc:
        raise ReportEmailError(f"Gmail OAuth token refresh failed: {exc}") from exc

    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ReportEmailError("Gmail OAuth response did not include an access token")
    return access_token


def exchange_gmail_authorization_code(
    *,
    code: str,
    redirect_uri: str,
    settings: EmailSettings | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, object]:
    credentials = gmail_oauth_credentials(settings=settings, client_id=client_id, client_secret=client_secret)
    request = Request(
        "https://oauth2.googleapis.com/token",
        data=urlencode(
            {
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ReportEmailError(f"Gmail OAuth code exchange failed: {_http_error_detail(exc)}") from exc
    except Exception as exc:
        raise ReportEmailError(f"Gmail OAuth code exchange failed: {exc}") from exc


def gmail_oauth_credentials(
    *,
    settings: EmailSettings | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    credentials_file: Path | str | None = None,
    client_secret_file: Path | str | None = None,
) -> GmailOAuthCredentials:
    resolved_client_id = _coalesce(client_id)
    resolved_client_secret = _coalesce(client_secret)

    resolved_credentials_file = _coalesce(
        credentials_file,
        _setting_value(settings, "gmail_client_credentials_file"),
        os.getenv("GMAIL_CLIENT_CREDENTIALS_FILE"),
        _default_render_gmail_credentials_file(),
    )
    if resolved_credentials_file:
        file_client_id, file_client_secret = _load_google_oauth_credentials_file(Path(resolved_credentials_file))
        resolved_client_id = resolved_client_id or file_client_id
        resolved_client_secret = resolved_client_secret or file_client_secret

    resolved_client_secret_file = _coalesce(client_secret_file)
    if resolved_client_secret_file and not resolved_client_secret:
        resolved_client_secret = _read_secret_file(Path(resolved_client_secret_file))

    if not resolved_credentials_file and (not resolved_client_id or not resolved_client_secret):
        discovered_file = _discover_google_oauth_credentials_file()
        if discovered_file:
            file_client_id, file_client_secret = _load_google_oauth_credentials_file(discovered_file)
            resolved_client_id = resolved_client_id or file_client_id
            resolved_client_secret = resolved_client_secret or file_client_secret

    if not resolved_client_id:
        raise ReportEmailError("GMAIL_CLIENT_CREDENTIALS_FILE is required")
    if not resolved_client_secret:
        raise ReportEmailError("GMAIL_CLIENT_CREDENTIALS_FILE is required")
    return GmailOAuthCredentials(client_id=resolved_client_id, client_secret=resolved_client_secret)


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


def _coalesce(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _setting_value(settings: EmailSettings | None, name: str) -> object:
    if settings is None:
        return None
    return getattr(settings, name, None)


def _load_google_oauth_credentials_file(path: Path) -> tuple[str, str]:
    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError as exc:
        raise ReportEmailError(f"Google OAuth credentials file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ReportEmailError(f"Google OAuth credentials file is not valid JSON: {path}") from exc

    credentials = payload.get("web") or payload.get("installed") or payload
    if not isinstance(credentials, dict):
        raise ReportEmailError(f"Google OAuth credentials file has an unexpected format: {path}")
    return _coalesce(credentials.get("client_id")), _coalesce(credentials.get("client_secret"))


def _read_secret_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ReportEmailError(f"Gmail client secret file does not exist: {path}") from exc


def _default_render_gmail_credentials_file() -> str:
    try:
        if DEFAULT_RENDER_GMAIL_CREDENTIALS_FILE.is_file():
            return str(DEFAULT_RENDER_GMAIL_CREDENTIALS_FILE)
    except OSError:
        return ""
    return ""


def _discover_google_oauth_credentials_file() -> Path | None:
    matches = []
    for base_path in (Path("/etc/secrets"), Path.cwd()):
        try:
            candidates = list(base_path.glob("*.json"))
        except OSError:
            continue
        for path in candidates:
            name = path.name.lower()
            if not any(marker in name for marker in ("gmail", "google", "oauth", "client_secret")):
                continue
            try:
                client_id, client_secret = _load_google_oauth_credentials_file(path)
            except ReportEmailError:
                continue
            if client_id and client_secret:
                matches.append(path)

    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) > 1:
        raise ReportEmailError("Multiple Google OAuth credential JSON files were found; set GMAIL_CLIENT_CREDENTIALS_FILE")
    return unique_matches[0] if unique_matches else None


def _http_error_detail(exc: HTTPError) -> str:
    parts = [f"HTTP {exc.code} {exc.reason}"]
    body = _read_http_error_body(exc)
    if body:
        parts.append(_summarize_http_error_body(body))
    return ": ".join(parts)


def _read_http_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _summarize_http_error_body(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]

    error = payload.get("error")
    if isinstance(error, dict):
        values = [
            error.get("status"),
            error.get("message"),
            error.get("error_description"),
        ]
        summary = " - ".join(str(value) for value in values if value)
        return summary or body[:500]
    if isinstance(error, str):
        description = payload.get("error_description")
        if description:
            return f"{error} - {description}"
        return error
    return body[:500]


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
