import logging
from datetime import date, datetime, timedelta

import httpx

from app.config import Settings, get_settings
from app.integrations import METRICOOL_PUBLICATION_FORMAT, POSTING_TIMEZONE
from app.reports import MetricoolReportError, _resolve_metricool_brand, _retrieve_scheduled_posts


logger = logging.getLogger(__name__)


async def scheduled_post_counts_by_day(
    *,
    start_at: str | None,
    days: int,
    settings: Settings | None = None,
) -> dict[str, int]:
    resolved_settings = settings or get_settings()
    if not resolved_settings.metricool_api_token:
        return {}

    start_date = _start_date(start_at)
    day_count = max(1, min(days, 60))

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            brand = await _resolve_metricool_brand(client, resolved_settings)
            counts: dict[str, int] = {}
            for offset in range(day_count):
                report_date = start_date + timedelta(days=offset)
                posts = await _retrieve_scheduled_posts(client, resolved_settings, brand, report_date)
                counts[report_date.isoformat()] = len(posts)
            return counts
    except (httpx.HTTPError, MetricoolReportError, ValueError, KeyError) as exc:
        logger.warning("Could not check existing Metricool scheduled posts: %s", exc)
        return {}


def _start_date(start_at: str | None) -> date:
    if start_at:
        try:
            return datetime.strptime(start_at, METRICOOL_PUBLICATION_FORMAT).date()
        except ValueError:
            pass
    return datetime.now(POSTING_TIMEZONE).date()
