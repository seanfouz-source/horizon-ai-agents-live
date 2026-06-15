from __future__ import annotations

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.inventory import InventoryRepository
from app.inventory_seed import seed_inventory_if_empty
from app.report_email import (
    ReportEmailError,
    build_message_from_settings,
    env_bool,
    send_message_from_settings,
)
from app.reports import (
    MetricoolReportError,
    build_daily_metricool_report,
    flatten_report_for_zapier,
    format_daily_report_pdf,
)


async def main() -> int:
    settings = get_settings()
    try:
        report = await build_daily_metricool_report(_parse_report_date(os.getenv("REPORT_DATE")))
        repository = InventoryRepository(settings.resolved_database_path)
        seed_inventory_if_empty(repository, settings.seed_inventory_csv)
        report["inventory"] = {
            "total_items": repository.count(),
            "store_sync": {"status": "not_run", "source": "render_cron"},
        }
        report_fields = flatten_report_for_zapier(report, settings.public_base_url)
        message = build_message_from_settings(report_fields, format_daily_report_pdf(report), settings)
        if env_bool("DRY_RUN"):
            print(f"Prepared report email: {message['Subject']} -> {message['To']}")
            return 0
        send_message_from_settings(message, settings)
        print(f"Sent report email: {message['Subject']} -> {message['To']}")
        return 0
    except (MetricoolReportError, ReportEmailError, ValueError) as exc:
        print(f"Failed to send report email: {exc}", file=sys.stderr)
        return 1


def _parse_report_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
