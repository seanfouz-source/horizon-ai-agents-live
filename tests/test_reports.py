import asyncio
from datetime import date

import httpx

from app.config import Settings
from app.reports import (
    build_daily_metricool_report,
    flatten_report_for_zapier,
    format_daily_report_markdown,
    format_daily_report_pdf,
    report_email_body,
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
    assert report["totals"]["content_posts"] == 3
    assert report["totals"]["platform_placements"] == 3
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
            "content_posts": 1,
            "platform_placements": 1,
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
    assert "- Content posts scheduled: 1" in markdown
    assert "- Platform placements tracked: 1" in markdown
    assert "- Published placements: 1" in markdown
    assert "| Platform | Published | Analytics Posts |" in markdown
    assert flattened["subject"] == "Horizon Wireless AI Marketing Report - 2026-05-29"
    assert flattened["email_body"].startswith("Attached is the Horizon Wireless AI Marketing Report")
    assert "- Content posts scheduled: 1" in flattened["email_body"]
    assert "- Platform placements tracked: 1" in flattened["email_body"]
    assert "- Published placements: 1" in flattened["email_body"]
    assert "Metricool platform analytics:" in flattened["email_body"]
    assert "- Facebook: 1 published, 1 Metricool analytics posts, 100 impressions/views" in flattened["email_body"]
    assert "Metricool top post analytics:" in flattened["email_body"]
    assert "Shop phones" in flattened["email_body"]
    assert flattened["attachment_url"].endswith("/reports/daily.pdf?date=2026-05-29&v=published-status")
    assert flattened["attachment_filename"] == "horizon-ai-marketing-report-2026-05-29.pdf"
    assert flattened["content_posts"] == 1
    assert flattened["platform_placements"] == 1
    assert flattened["published_posts"] == 1
    assert flattened["analytics_note"] == "Metricool returned 1 post-level analytics records with numeric metrics."
    assert flattened["top_post_rows"].startswith("- Facebook: 100 impressions/views")
    assert flattened["clicks"] == 5
    assert flattened["best_platform"] == "facebook"


def test_report_email_body_explains_metricool_records_without_numeric_metrics():
    report = {
        "report_date": "2026-06-04",
        "timezone": "America/Chicago",
        "brand": {"label": "Horizon Wireless", "blog_id": 6278196},
        "totals": {
            "content_posts": 1,
            "platform_placements": 4,
            "scheduled_posts": 4,
            "analytics_posts": 2,
            "published_posts": 2,
            "pending_posts": 2,
            "failed_posts": 0,
            "impressions": 0,
            "reach": 0,
            "clicks": 0,
            "engagement_actions": 0,
            "engagement_rate": 0.0,
        },
        "platforms": [
            {"platform": "facebook", "posts": 0, "published_posts": 0, "impressions": 0, "reach": 0, "clicks": 0, "engagement_actions": 0, "engagement_rate": 0.0, "pending_posts": 1, "failed_posts": 0},
            {"platform": "linkedin", "posts": 2, "published_posts": 2, "impressions": 0, "reach": 0, "clicks": 0, "engagement_actions": 0, "engagement_rate": 0.0, "pending_posts": 1, "failed_posts": 0},
        ],
        "top_posts": [
            {"platform": "linkedin", "impressions": 0, "reach": 0, "clicks": 0, "engagement_actions": 0, "text": "Horizon Wireless listing update", "url": "https://linkedin.com/feed/update/1"},
        ],
        "failures": [],
        "recommendations": ["Metricool returned post records, but numeric analytics are still pending."],
    }

    body = report_email_body(report)

    assert "Metricool returned 2 post records, but numeric metrics are still 0/not available yet." in body
    assert "- Content posts scheduled: 1" in body
    assert "- Platform placements tracked: 4" in body
    assert "- LinkedIn: 2 published, 2 Metricool analytics posts, 0 impressions/views" in body
    assert "- LinkedIn: 0 impressions/views, 0 reach, 0 clicks, 0 engagements - Horizon Wireless listing update" in body
    assert "URL: https://linkedin.com/feed/update/1" in body
    assert "- No failed Metricool posts found for this report date." in body


def test_daily_metricool_report_pdf_renders():
    report = {
        "report_date": "2026-05-29",
        "timezone": "America/Chicago",
        "brand": {"label": "Horizon Wireless", "blog_id": 6278196},
        "totals": {
            "content_posts": 1,
            "platform_placements": 1,
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
