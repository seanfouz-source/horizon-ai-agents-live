import asyncio
from datetime import date

import httpx

from app.config import Settings
from app.reports import (
    build_daily_metricool_report,
    flatten_report_for_zapier,
    format_daily_report_markdown,
    format_daily_report_pdf,
)


def test_daily_metricool_report_aggregates_platform_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/admin/simpleProfiles"):
            return httpx.Response(
                200,
                json=[
                    {"id": 6278196, "userId": 4838974, "label": "Horizon Wireless"},
                ],
            )
        if path.endswith("/v2/scheduler/posts"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": 1,
                            "publicationDate": {"dateTime": "2026-05-29T16:30:00", "timezone": "America/Chicago"},
                            "text": "Facebook post",
                            "media": ["https://example.com/phone.jpg"],
                            "autoPublish": True,
                            "draft": False,
                            "providers": [{"network": "facebook", "status": "PUBLISHED", "detailedStatus": "Published"}],
                        },
                        {
                            "id": 2,
                            "publicationDate": {"dateTime": "2026-05-29T18:00:00", "timezone": "America/Chicago"},
                            "text": "Instagram post",
                            "media": ["https://example.com/phone.jpg"],
                            "autoPublish": True,
                            "draft": False,
                            "providers": [{"network": "instagram", "status": "PENDING", "detailedStatus": "Pending"}],
                        },
                        {
                            "id": 3,
                            "publicationDate": {"dateTime": "2026-05-29T19:30:00", "timezone": "America/Chicago"},
                            "text": "TikTok post",
                            "media": ["https://example.com/phone.jpg"],
                            "autoPublish": True,
                            "draft": False,
                            "providers": [{"network": "tiktok", "status": "ERROR", "detailedStatus": "Bad media"}],
                        },
                    ]
                },
            )
        if path.endswith("/v2/analytics/posts/facebook"):
            return httpx.Response(200, json={"data": [{"text": "Shop this phone", "impressions": 100, "impressionsUnique": 80, "linkclicks": 7, "reactions": 3, "comments": 1, "shares": 2}]})
        if path.endswith("/v2/analytics/posts/instagram"):
            return httpx.Response(200, json={"data": [{"content": "IG phone", "impressions": 50, "reach": 40, "clicks": 2, "likes": 6, "comments": 1, "shares": 1, "saved": 1}]})
        if path.endswith("/v2/analytics/posts/tiktok"):
            return httpx.Response(200, json={"data": [{"videoDescription": "TikTok phone", "viewCount": 200, "likeCount": 10, "commentCount": 2, "shareCount": 3}]})
        if path.endswith("/v2/analytics/posts/linkedin"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404, json={"error": path})

    async def run_report():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://app.metricool.com") as client:
            return await build_daily_metricool_report(
                date(2026, 5, 29),
                settings=Settings(metricool_api_token="token"),
                client=client,
            )

    report = asyncio.run(run_report())

    assert report["brand"]["blog_id"] == 6278196
    assert report["totals"]["scheduled_posts"] == 3
    assert report["totals"]["analytics_posts"] == 3
    assert report["totals"]["failed_posts"] == 1
    assert report["totals"]["pending_posts"] == 1
    assert report["totals"]["clicks"] == 9
    assert report["totals"]["engagement_actions"] == 30
    assert report["platforms"][0]["platform"] == "facebook"
    assert report["platforms"][0]["clicks"] == 7
    assert report["failures"][0]["detail"] == "Bad media"


def test_daily_metricool_report_markdown_and_zapier_flattening():
    report = {
        "report_date": "2026-05-29",
        "timezone": "America/Chicago",
        "brand": {"label": "Horizon Wireless", "blog_id": 6278196},
        "totals": {
            "scheduled_posts": 1,
            "analytics_posts": 1,
            "published_posts": 1,
            "pending_posts": 0,
            "failed_posts": 0,
            "impressions": 100,
            "reach": 80,
            "clicks": 5,
            "engagement_actions": 10,
            "engagement_rate": 12.5,
        },
        "platforms": [
            {"platform": "facebook", "posts": 1, "published_posts": 1, "impressions": 100, "reach": 80, "clicks": 5, "engagement_actions": 10, "engagement_rate": 12.5, "pending_posts": 0, "failed_posts": 0},
        ],
        "top_posts": [{"platform": "facebook", "impressions": 100, "clicks": 5, "engagement_actions": 10, "text": "Shop phones"}],
        "failures": [],
        "recommendations": ["Post more iPhone listings."],
    }

    markdown = format_daily_report_markdown(report)
    flattened = flatten_report_for_zapier(report)

    assert "Horizon Wireless AI Marketing Report" in markdown
    assert "- Published posts: 1" in markdown
    assert "| Platform | Published | Analytics Posts |" in markdown
    assert flattened["subject"] == "Horizon Wireless AI Marketing Report - 2026-05-29"
    assert flattened["email_body"].startswith("Attached is the Horizon Wireless AI Marketing Report")
    assert "- Published posts: 1" in flattened["email_body"]
    assert flattened["attachment_url"].endswith("/reports/daily.pdf?date=2026-05-29")
    assert flattened["attachment_filename"] == "horizon-ai-marketing-report-2026-05-29.pdf"
    assert flattened["published_posts"] == 1
    assert flattened["clicks"] == 5
    assert flattened["best_platform"] == "facebook"


def test_daily_metricool_report_pdf_renders():
    report = {
        "report_date": "2026-05-29",
        "timezone": "America/Chicago",
        "brand": {"label": "Horizon Wireless", "blog_id": 6278196},
        "totals": {
            "scheduled_posts": 1,
            "analytics_posts": 1,
            "published_posts": 1,
            "pending_posts": 0,
            "failed_posts": 0,
            "impressions": 100,
            "reach": 80,
            "clicks": 5,
            "engagement_actions": 10,
            "engagement_rate": 12.5,
        },
        "platforms": [
            {"platform": "facebook", "posts": 1, "scheduled_posts": 1, "published_posts": 1, "draft_posts": 0, "impressions": 100, "reach": 80, "clicks": 5, "engagement_actions": 10, "engagement_rate": 12.5, "pending_posts": 0, "failed_posts": 0},
        ],
        "top_posts": [{"platform": "facebook", "impressions": 100, "reach": 80, "clicks": 5, "engagement_actions": 10, "text": "Shop phones"}],
        "failures": [],
        "recommendations": ["Post more iPhone listings."],
    }

    pdf = format_daily_report_pdf(report)

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
