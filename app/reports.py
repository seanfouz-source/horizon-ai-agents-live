from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings, get_settings


REPORT_TIMEZONE = ZoneInfo("America/Chicago")
METRICOOL_BASE_URL = "https://app.metricool.com/api"
REPORT_PLATFORMS = ("facebook", "instagram", "tiktok", "linkedin")


class MetricoolReportError(RuntimeError):
    pass


async def build_daily_metricool_report(
    report_date: date | None = None,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not settings.metricool_api_token:
        raise MetricoolReportError("METRICOOL_API_TOKEN is not configured.")

    local_date = report_date or (datetime.now(REPORT_TIMEZONE).date() - timedelta(days=1))
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=25)

    try:
        brand = await _resolve_metricool_brand(active_client, settings)
        scheduled_posts, analytics_by_platform = await asyncio.gather(
            _retrieve_scheduled_posts(active_client, settings, brand, local_date),
            _retrieve_analytics(active_client, settings, brand, local_date),
        )
    finally:
        if owns_client:
            await active_client.aclose()

    platform_rows = [
        _platform_report_row(platform, analytics_by_platform.get(platform, []), scheduled_posts)
        for platform in REPORT_PLATFORMS
    ]
    totals = _report_totals(platform_rows, scheduled_posts)
    top_posts = _top_posts(analytics_by_platform)

    return {
        "report_date": local_date.isoformat(),
        "timezone": str(REPORT_TIMEZONE),
        "brand": brand,
        "totals": totals,
        "platforms": platform_rows,
        "scheduled_posts": [_scheduled_post_summary(post) for post in scheduled_posts],
        "top_posts": top_posts,
        "failures": _failed_provider_statuses(scheduled_posts),
        "recommendations": _recommendations(platform_rows, scheduled_posts),
        "notes": [
            "Metricool analytics can lag after a post publishes.",
            "eBay clicks are a traffic proxy from social platforms unless eBay API/order data is connected.",
        ],
    }


def format_daily_report_markdown(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [
        f"# Horizon Wireless AI Marketing Report - {report['report_date']}",
        "",
        f"Brand: {report['brand']['label']} ({report['brand']['blog_id']})",
        f"Timezone: {report['timezone']}",
        "",
        "## Summary",
        "",
        f"- Scheduled/published posts tracked: {totals['scheduled_posts']}",
        f"- Published analytics posts: {totals['analytics_posts']}",
        f"- Pending posts: {totals['pending_posts']}",
        f"- Failed posts: {totals['failed_posts']}",
        f"- Impressions/views: {totals['impressions']}",
        f"- Reach: {totals['reach']}",
        f"- eBay click proxy: {totals['clicks']}",
        f"- Engagement actions: {totals['engagement_actions']}",
        f"- Engagement rate: {totals['engagement_rate']}%",
        "",
        "## Platform Performance",
        "",
        "| Platform | Posts | Impressions/Views | Reach | Clicks | Engagement | Engagement Rate | Pending | Failed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["platforms"]:
        lines.append(
            "| {platform} | {posts} | {impressions} | {reach} | {clicks} | {engagement_actions} | {engagement_rate}% | {pending_posts} | {failed_posts} |".format(
                **row
            )
        )

    lines.extend(["", "## Top Posts", ""])
    if report["top_posts"]:
        for post in report["top_posts"]:
            lines.append(
                f"- {post['platform']}: {post['impressions']} impressions/views, {post['clicks']} clicks, "
                f"{post['engagement_actions']} engagement actions - {post['text']}"
            )
    else:
        lines.append("- No published post analytics returned for this date yet.")

    lines.extend(["", "## Watch List", ""])
    if report["failures"]:
        for failure in report["failures"]:
            lines.append(
                f"- {failure['platform']} post {failure['post_id']}: {failure['status']} - {failure['detail']}"
            )
    else:
        lines.append("- No failed Metricool posts found for this report date.")

    lines.extend(["", "## Recommendations", ""])
    for recommendation in report["recommendations"]:
        lines.append(f"- {recommendation}")

    return "\n".join(lines) + "\n"


def flatten_report_for_zapier(report: dict[str, Any]) -> dict[str, Any]:
    markdown = format_daily_report_markdown(report)
    totals = report["totals"]
    best_platform = max(report["platforms"], key=lambda row: (row["clicks"], row["engagement_actions"]), default=None)
    return {
        "report_date": report["report_date"],
        "subject": f"Horizon Wireless AI Marketing Report - {report['report_date']}",
        "summary_text": markdown,
        "brand_name": report["brand"]["label"],
        "scheduled_posts": totals["scheduled_posts"],
        "analytics_posts": totals["analytics_posts"],
        "pending_posts": totals["pending_posts"],
        "failed_posts": totals["failed_posts"],
        "impressions": totals["impressions"],
        "reach": totals["reach"],
        "clicks": totals["clicks"],
        "engagement_actions": totals["engagement_actions"],
        "engagement_rate": totals["engagement_rate"],
        "best_platform": best_platform["platform"] if best_platform else "",
        "platform_rows": "\n".join(
            f"{row['platform']}: {row['impressions']} impressions/views, {row['clicks']} clicks, "
            f"{row['engagement_actions']} engagements, {row['pending_posts']} pending, {row['failed_posts']} failed"
            for row in report["platforms"]
        ),
        "failures": "\n".join(
            f"{failure['platform']} post {failure['post_id']}: {failure['status']} - {failure['detail']}"
            for failure in report["failures"]
        ),
        "recommendations": "\n".join(report["recommendations"]),
    }


async def _resolve_metricool_brand(client: httpx.AsyncClient, settings: Settings) -> dict[str, Any]:
    if settings.metricool_blog_id and settings.metricool_user_id:
        return {
            "blog_id": settings.metricool_blog_id,
            "user_id": settings.metricool_user_id,
            "label": settings.metricool_brand_label,
        }

    profiles = await _metricool_get(client, settings, "/admin/simpleProfiles")
    if not isinstance(profiles, list) or not profiles:
        raise MetricoolReportError("Metricool returned no brands for this API token.")

    preferred_label = settings.metricool_brand_label.strip().casefold()
    profile = next(
        (
            item
            for item in profiles
            if str(item.get("label") or item.get("title") or "").strip().casefold() == preferred_label
        ),
        profiles[0],
    )
    return {
        "blog_id": int(profile["id"]),
        "user_id": int(profile["userId"]),
        "label": str(profile.get("label") or profile.get("title") or settings.metricool_brand_label),
    }


async def _retrieve_scheduled_posts(
    client: httpx.AsyncClient,
    settings: Settings,
    brand: dict[str, Any],
    report_date: date,
) -> list[dict[str, Any]]:
    payload = await _metricool_get(
        client,
        settings,
        "/v2/scheduler/posts",
        {
            **_brand_params(brand),
            "start": f"{report_date.isoformat()}T00:00:00",
            "end": f"{report_date.isoformat()}T23:59:59",
            "timezone": str(REPORT_TIMEZONE),
        },
    )
    return _data_list(payload)


async def _retrieve_analytics(
    client: httpx.AsyncClient,
    settings: Settings,
    brand: dict[str, Any],
    report_date: date,
) -> dict[str, list[dict[str, Any]]]:
    async def retrieve_platform(platform: str) -> tuple[str, list[dict[str, Any]]]:
        payload = await _metricool_get(
            client,
            settings,
            f"/v2/analytics/posts/{platform}",
            {
                **_brand_params(brand),
                "from": f"{report_date.isoformat()}T00:00:00",
                "to": f"{report_date.isoformat()}T23:59:59",
                "timezone": str(REPORT_TIMEZONE),
            },
        )
        return platform, _data_list(payload)

    results = await asyncio.gather(*(retrieve_platform(platform) for platform in REPORT_PLATFORMS))
    return dict(results)


async def _metricool_get(
    client: httpx.AsyncClient,
    settings: Settings,
    path: str,
    params: dict[str, Any] | None = None,
) -> Any:
    response = await client.get(
        f"{METRICOOL_BASE_URL}{path}",
        params=params,
        headers={
            "X-Mc-Auth": settings.metricool_api_token or "",
            "Content-Type": "application/json",
        },
    )
    if response.status_code >= 400:
        raise MetricoolReportError(f"Metricool {path} returned HTTP {response.status_code}: {response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise MetricoolReportError(f"Metricool {path} did not return JSON.") from exc


def _brand_params(brand: dict[str, Any]) -> dict[str, Any]:
    return {"blogId": brand["blog_id"], "userId": brand["user_id"]}


def _data_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("data", [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _platform_report_row(
    platform: str,
    analytics_posts: list[dict[str, Any]],
    scheduled_posts: list[dict[str, Any]],
) -> dict[str, Any]:
    provider_statuses = _provider_statuses_for_platform(platform, scheduled_posts)
    status_counts = Counter(status["status"] for status in provider_statuses)
    impressions = sum(_impressions(platform, post) for post in analytics_posts)
    reach = sum(_reach(platform, post) for post in analytics_posts)
    clicks = sum(_clicks(platform, post) for post in analytics_posts)
    engagement_actions = sum(_engagement_actions(platform, post) for post in analytics_posts)
    denominator = reach or impressions
    engagement_rate = round((engagement_actions / denominator) * 100, 2) if denominator else 0.0
    return {
        "platform": platform,
        "posts": len(analytics_posts),
        "scheduled_posts": len(provider_statuses),
        "published_posts": status_counts["PUBLISHED"],
        "pending_posts": status_counts["PENDING"],
        "draft_posts": status_counts["DRAFT"],
        "failed_posts": status_counts["ERROR"],
        "impressions": impressions,
        "reach": reach,
        "clicks": clicks,
        "engagement_actions": engagement_actions,
        "engagement_rate": engagement_rate,
    }


def _report_totals(platform_rows: list[dict[str, Any]], scheduled_posts: list[dict[str, Any]]) -> dict[str, Any]:
    impressions = sum(row["impressions"] for row in platform_rows)
    reach = sum(row["reach"] for row in platform_rows)
    engagement_actions = sum(row["engagement_actions"] for row in platform_rows)
    denominator = reach or impressions
    return {
        "scheduled_posts": sum(len(post.get("providers") or []) for post in scheduled_posts),
        "analytics_posts": sum(row["posts"] for row in platform_rows),
        "published_posts": sum(row["published_posts"] for row in platform_rows),
        "pending_posts": sum(row["pending_posts"] for row in platform_rows),
        "draft_posts": sum(row["draft_posts"] for row in platform_rows),
        "failed_posts": sum(row["failed_posts"] for row in platform_rows),
        "impressions": impressions,
        "reach": reach,
        "clicks": sum(row["clicks"] for row in platform_rows),
        "engagement_actions": engagement_actions,
        "engagement_rate": round((engagement_actions / denominator) * 100, 2) if denominator else 0.0,
    }


def _scheduled_post_summary(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": post.get("id"),
        "uuid": post.get("uuid"),
        "publication_date": post.get("publicationDate"),
        "draft": post.get("draft"),
        "auto_publish": post.get("autoPublish"),
        "media_count": len(post.get("media") or []),
        "providers": [
            {
                "platform": provider.get("network"),
                "status": provider.get("status"),
                "detail": provider.get("detailedStatus"),
                "public_url": provider.get("publicUrl"),
            }
            for provider in post.get("providers") or []
        ],
        "text": str(post.get("text") or "")[:180],
    }


def _failed_provider_statuses(scheduled_posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for post in scheduled_posts:
        for provider in post.get("providers") or []:
            if provider.get("status") == "ERROR":
                failures.append(
                    {
                        "post_id": post.get("id"),
                        "platform": provider.get("network"),
                        "status": provider.get("status"),
                        "detail": provider.get("detailedStatus") or "No detail returned by Metricool.",
                    }
                )
    return failures


def _provider_statuses_for_platform(platform: str, scheduled_posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    statuses = []
    for post in scheduled_posts:
        for provider in post.get("providers") or []:
            if str(provider.get("network") or "").lower() == platform:
                statuses.append(provider)
    return statuses


def _top_posts(analytics_by_platform: dict[str, list[dict[str, Any]]], limit: int = 5) -> list[dict[str, Any]]:
    posts = []
    for platform, platform_posts in analytics_by_platform.items():
        for post in platform_posts:
            posts.append(
                {
                    "platform": platform,
                    "impressions": _impressions(platform, post),
                    "reach": _reach(platform, post),
                    "clicks": _clicks(platform, post),
                    "engagement_actions": _engagement_actions(platform, post),
                    "text": _post_text(platform, post)[:140],
                    "url": _post_url(platform, post),
                }
            )
    posts.sort(key=lambda item: (item["clicks"], item["engagement_actions"], item["impressions"]), reverse=True)
    return posts[:limit]


def _recommendations(platform_rows: list[dict[str, Any]], scheduled_posts: list[dict[str, Any]]) -> list[str]:
    recommendations = []
    failures = _failed_provider_statuses(scheduled_posts)
    if failures:
        recommendations.append("Fix failed Metricool posts first so the schedule does not silently lose inventory promotions.")

    if any(row["posts"] for row in platform_rows):
        best_clicks = max(platform_rows, key=lambda row: (row["clicks"], row["engagement_actions"]))
        best_engagement = max(platform_rows, key=lambda row: (row["engagement_rate"], row["engagement_actions"]))
        recommendations.append(
            f"Prioritize {best_clicks['platform']} for eBay traffic if the click lead holds over several days."
        )
        if best_engagement["engagement_actions"] > 0:
            recommendations.append(
                f"Use {best_engagement['platform']} style captions as the model for the next product batch."
            )
    else:
        recommendations.append("Wait for published posts to collect analytics, then compare clicks and engagement by platform.")

    if not any(row["clicks"] for row in platform_rows):
        recommendations.append("Add UTM links or eBay campaign tracking next so click-to-sale attribution is cleaner.")

    return recommendations


def _number(post: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = post.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _impressions(platform: str, post: dict[str, Any]) -> int:
    if platform == "tiktok":
        return _number(post, "viewCount", "reach")
    if platform == "instagram":
        return _number(post, "impressions", "impressionsTotal", "views")
    return _number(post, "impressions", "impressionsUnique", "uniqueImpressions", "videoViews")


def _reach(platform: str, post: dict[str, Any]) -> int:
    if platform == "facebook":
        return _number(post, "impressionsUnique", "reach")
    if platform == "linkedin":
        return _number(post, "uniqueImpressions", "impressions")
    return _number(post, "reach", "viewCount")


def _clicks(platform: str, post: dict[str, Any]) -> int:
    if platform == "facebook":
        return _number(post, "linkclicks", "clicks")
    return _number(post, "clicks", "postClicksPaid")


def _engagement_actions(platform: str, post: dict[str, Any]) -> int:
    if platform == "facebook":
        return sum(_number(post, key) for key in ("reactions", "comments", "shares"))
    if platform == "instagram":
        return sum(_number(post, key) for key in ("likes", "comments", "shares", "saved")) or _number(post, "interactions")
    if platform == "tiktok":
        return sum(_number(post, key) for key in ("likeCount", "commentCount", "shareCount"))
    if platform == "linkedin":
        return sum(_number(post, key) for key in ("likes", "comments", "shares"))
    return 0


def _post_text(platform: str, post: dict[str, Any]) -> str:
    if platform == "instagram":
        return str(post.get("content") or "")
    if platform == "tiktok":
        return str(post.get("videoDescription") or post.get("title") or "")
    if platform == "linkedin":
        return str(post.get("comment") or post.get("description") or post.get("title") or "")
    return str(post.get("text") or "")


def _post_url(platform: str, post: dict[str, Any]) -> str | None:
    if platform == "instagram":
        return post.get("url")
    if platform == "tiktok":
        return post.get("shareUrl")
    if platform == "linkedin":
        return post.get("url")
    return post.get("link")
