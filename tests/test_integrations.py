from datetime import datetime
from zoneinfo import ZoneInfo

from app.integrations import default_metricool_publication_time, metricool_payload, zapier_social_drafts_response
from app.models import SocialDraftBatch, SocialDraftRequest, SocialPost


def test_zapier_social_drafts_response_adds_flat_metricool_fields():
    batch = SocialDraftBatch(
        campaign_name="ExactSpec test",
        posts=[],
        metricool_payloads=[
            {
                "brand_name": "ExactSpec",
                "facebook": True,
                "instagram": False,
                "tiktok": False,
                "publication_date_time": "2026-05-25 05:46:21",
                "post_content": "Shop this ExactSpec listing.",
                "as_draft": True,
                "auto_publish": False,
                "post_type": "POST",
            },
            {
                "brand_name": "ExactSpec",
                "facebook": False,
                "instagram": True,
                "tiktok": False,
                "publication_date_time": "2026-05-25 05:46:21",
                "post_content": "Shop this ExactSpec listing.",
                "as_draft": True,
                "auto_publish": False,
                "post_type": "POST",
            },
            {
                "brand_name": "ExactSpec",
                "facebook": False,
                "instagram": False,
                "tiktok": True,
                "publication_date_time": "2026-05-25 05:46:21",
                "post_content": "Shop this ExactSpec listing.",
                "as_draft": True,
                "auto_publish": False,
                "post_type": "POST",
            }
        ],
    )

    response = zapier_social_drafts_response(batch)

    assert response["metricool_publication_date_time"] == "2026-05-25 05:46:21"
    assert response["publicationDate"] == "2026-05-25 05:46:21"
    assert response["metricool_post_content"] == "Shop this ExactSpec listing."
    assert response["metricool_facebook"] is True
    assert response["metricool_instagram"] is False
    assert response["metricool_tiktok"] is False
    assert response["metricool_as_draft"] is True


def test_zapier_social_drafts_response_enables_media_platforms_when_supported():
    batch = SocialDraftBatch(
        campaign_name="ExactSpec test",
        posts=[],
        metricool_payloads=[
            {
                "brand_name": "ExactSpec",
                "facebook": False,
                "instagram": True,
                "tiktok": False,
                "publication_date_time": "2026-05-25 05:46:21",
                "post_content": "Shop this ExactSpec listing.",
                "media_01": "https://example.com/product.jpg",
                "as_draft": False,
                "auto_publish": True,
                "post_type": "POST",
            },
            {
                "brand_name": "ExactSpec",
                "facebook": False,
                "instagram": False,
                "tiktok": True,
                "publication_date_time": "2026-05-25 05:46:21",
                "post_content": "Shop this ExactSpec listing.",
                "media_01": "https://example.com/product.mp4",
                "as_draft": False,
                "auto_publish": True,
                "post_type": "POST",
            },
        ],
    )

    response = zapier_social_drafts_response(batch)

    assert response["metricool_instagram"] is True
    assert response["metricool_tiktok"] is True


def test_metricool_payload_adds_generated_product_media_url():
    payload = metricool_payload(
        SocialPost(
            platform="instagram",
            text="Shop this listing.",
            product_sku="EBAY-123",
            product_title="Demo Phone",
        ),
        SocialDraftRequest(brand_name="ExactSpec"),
    )

    assert payload["media_01"] == "https://horizon-ai-agents.onrender.com/media/products/EBAY-123.png"


def test_default_metricool_publication_time_uses_next_busy_slot():
    central = ZoneInfo("America/Chicago")
    now = datetime(2026, 5, 26, 9, 0, tzinfo=central)

    assert default_metricool_publication_time(now) == "2026-05-26 12:30:00"


def test_default_metricool_publication_time_skips_weekend():
    central = ZoneInfo("America/Chicago")
    now = datetime(2026, 5, 29, 17, 30, tzinfo=central)

    assert default_metricool_publication_time(now) == "2026-06-01 12:30:00"
