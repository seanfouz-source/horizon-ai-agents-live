from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.report_email import build_message, env_bool, send_message, split_addresses


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


if __name__ == "__main__":
    raise SystemExit(main())
