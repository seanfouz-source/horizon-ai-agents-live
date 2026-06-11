from datetime import datetime
from zoneinfo import ZoneInfo

from app.integrations import (
    apply_tiktok_daily_post_cap,
    default_metricool_publication_time,
    default_metricool_publication_times,
    metricool_payload,
    zapier_social_drafts_response,
)
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
                "ebay_url": "https://www.ebay.com/itm/1",
                "buy_url": "https://www.ebay.com/itm/1",
                "link_url": "https://www.ebay.com/itm/1",
                "facebook_link_url": "https://www.ebay.com/itm/1",
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
                "linkedin": False,
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
                "tiktok": False,
                "linkedin": True,
                "publication_date_time": "2026-05-25 05:46:21",
                "post_content": "Shop this ExactSpec listing.",
                "as_draft": True,
                "auto_publish": False,
                "post_type": "POST",
            },
        ],
    )

    response = zapier_social_drafts_response(batch)

    assert response["metricool_publication_date_time"] == "2026-05-25 05:46:21"
    assert response["publicationDate"] == "2026-05-25 05:46:21"
    assert response["draft"] is True
    assert response["metricool_post_content"] == "Shop this ExactSpec listing."
    assert response["metricool_facebook"] is True
    assert response["metricool_instagram"] is False
    assert response["metricool_tiktok"] is False
    assert response["metricool_linkedin"] is True
    assert response["metricool_as_draft"] is True
    assert response["metricool_payload_count"] == 4
    assert response["metricool_ebay_url"] == "https://www.ebay.com/itm/1"
    assert response["metricool_buy_url"] == "https://www.ebay.com/itm/1"
    assert response["metricool_link_url"] == "https://www.ebay.com/itm/1"
    assert response["metricool_facebook_link_url"] == "https://www.ebay.com/itm/1"
    assert response["metricool_post_content_items"] == [
        "Shop this ExactSpec listing.",
        "Shop this ExactSpec listing.",
        "Shop this ExactSpec listing.",
        "Shop this ExactSpec listing.",
    ]
    assert response["metricool_publication_date_time_items"] == [
        "2026-05-25 05:46:21",
        "2026-05-25 05:46:21",
        "2026-05-25 05:46:21",
        "2026-05-25 05:46:21",
    ]
    assert response["publicationDate_items"] == [
        "2026-05-25 05:46:21",
        "2026-05-25 05:46:21",
        "2026-05-25 05:46:21",
        "2026-05-25 05:46:21",
    ]
    assert response["draft_items"] == [True, True, True, True]
    assert response["metricool_ebay_url_items"][0] == "https://www.ebay.com/itm/1"
    assert response["metricool_buy_url_items"][0] == "https://www.ebay.com/itm/1"
    assert response["metricool_link_url_items"][0] == "https://www.ebay.com/itm/1"
    assert response["metricool_facebook_link_url_items"][0] == "https://www.ebay.com/itm/1"


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
                "linkedin": False,
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
            platform="linkedin",
            text="Shop this listing.",
            product_sku="EBAY-123",
            product_title="Demo Phone",
        ),
        SocialDraftRequest(brand_name="ExactSpec"),
    )

    assert payload["media_01"] == "https://horizon-ai-agents.onrender.com/media/products/EBAY-123.jpg"


def test_metricool_payload_replaces_tiktok_png_with_generated_jpeg():
    payload = metricool_payload(
        SocialPost(
            platform="tiktok",
            text="Shop this listing.",
            product_sku="EBAY-123",
            product_title="Demo Phone",
            ebay_url="https://www.ebay.com/itm/123",
            media_url="https://example.com/product-card.png",
        ),
        SocialDraftRequest(brand_name="ExactSpec"),
    )

    assert payload["media_01"] == "https://horizon-ai-agents.onrender.com/media/products/EBAY-123.jpg"


def test_metricool_payload_uses_campaign_video_for_tiktok():
    payload = metricool_payload(
        SocialPost(
            platform="tiktok",
            text="Watch the Horizon Wireless retail store walkthrough.",
            product_sku="EBAY-123",
            product_title="Demo Phone",
        ),
        SocialDraftRequest(brand_name="Horizon Wireless", campaign_video="retail"),
    )

    assert payload["media_01"] == "https://horizon-ai-agents.onrender.com/media/campaigns/ebay-retail-store.mp4"


def test_metricool_payload_ignores_descriptive_ai_schedule(monkeypatch):
    monkeypatch.setattr("app.integrations.default_metricool_publication_time", lambda: "2026-05-26 07:30:00")

    payload = metricool_payload(
        SocialPost(
            platform="facebook",
            text="Wholesale devices available from Horizon Wireless.",
            suggested_schedule="Weekday morning (9-11 AM)",
        ),
        SocialDraftRequest(brand_name="Horizon Wireless"),
    )

    assert payload["publication_date_time"] == "2026-05-26 07:30:00"


def test_metricool_payload_adds_facebook_group_targets():
    payload = metricool_payload(
        SocialPost(
            platform="facebook",
            text="Wholesale devices available from Horizon Wireless.",
        ),
        SocialDraftRequest(
            brand_name="Horizon Wireless",
            facebook_groups="Wireless Wholesale Buyers, Phone Resellers",
            publish_to_facebook_groups=True,
        ),
    )

    assert payload["publish_to_facebook_groups"] is True
    assert payload["facebook_groups"] == ["Wireless Wholesale Buyers", "Phone Resellers"]


def test_metricool_payload_cross_posts_all_inventory_to_requested_platforms():
    payload = metricool_payload(
        SocialPost(
            platform="facebook",
            text="Shop this listing.",
            product_sku="EBAY-123",
            product_title="Demo Phone",
            ebay_url="https://www.ebay.com/itm/123",
            media_url="https://example.com/product-card.png",
        ),
        SocialDraftRequest(
            brand_name="Horizon Wireless",
            promote_all_inventory=True,
            platforms=["facebook", "instagram", "tiktok", "linkedin"],
            auto_publish=True,
            as_draft=False,
        ),
    )

    assert payload["facebook"] is True
    assert payload["instagram"] is True
    assert payload["tiktok"] is True
    assert payload["linkedin"] is True
    assert payload["publicationDate"] == payload["publication_date_time"]
    assert payload["draft"] is False
    assert payload["media_01"] == "https://horizon-ai-agents.onrender.com/media/products/EBAY-123.jpg"
    assert payload["buy_url"] == "https://www.ebay.com/itm/123"
    assert payload["link_url"] == "https://www.ebay.com/itm/123"
    assert payload["facebook_link_url"] == "https://www.ebay.com/itm/123"


def test_apply_tiktok_daily_post_cap_keeps_other_platforms_active():
    payloads = [
        {
            "facebook": True,
            "instagram": True,
            "tiktok": True,
            "linkedin": True,
            "publication_date_time": f"2026-06-12 {hour:02d}:00:00",
            "as_draft": False,
            "auto_publish": True,
        }
        for hour in range(8, 13)
    ]

    suppressed_count = apply_tiktok_daily_post_cap(payloads, daily_cap=3)

    assert suppressed_count == 2
    assert [payload["tiktok"] for payload in payloads] == [True, True, True, False, False]
    assert all(payload["facebook"] for payload in payloads)
    assert all(payload["instagram"] for payload in payloads)
    assert all(payload["linkedin"] for payload in payloads)
    assert payloads[3]["tiktok_throttle_reason"].startswith("TikTok auto-publish disabled")
    assert payloads[4]["tiktok_daily_post_cap"] == 3


def test_apply_tiktok_daily_post_cap_resets_by_scheduled_day():
    payloads = [
        {
            "tiktok": True,
            "publication_date_time": "2026-06-12 08:00:00",
            "as_draft": False,
            "auto_publish": True,
        },
        {
            "tiktok": True,
            "publication_date_time": "2026-06-12 09:00:00",
            "as_draft": False,
            "auto_publish": True,
        },
        {
            "tiktok": True,
            "publication_date_time": "2026-06-13 08:00:00",
            "as_draft": False,
            "auto_publish": True,
        },
    ]

    suppressed_count = apply_tiktok_daily_post_cap(payloads, daily_cap=1)

    assert suppressed_count == 1
    assert [payload["tiktok"] for payload in payloads] == [True, False, True]


def test_zapier_social_drafts_response_uses_tiktok_safe_flat_media():
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
                "media_01": "https://example.com/product-card.png",
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
                "media_01": "https://example.com/product-card.jpg",
                "as_draft": False,
                "auto_publish": True,
                "post_type": "POST",
            },
        ],
    )

    response = zapier_social_drafts_response(batch)

    assert response["metricool_tiktok"] is True
    assert response["metricool_media_01"] == "https://example.com/product-card.jpg"


def test_zapier_social_drafts_response_flattens_facebook_groups():
    batch = SocialDraftBatch(
        campaign_name="Horizon wholesale video",
        posts=[],
        metricool_payloads=[
            {
                "brand_name": "Horizon Wireless",
                "facebook": True,
                "instagram": False,
                "tiktok": False,
                "linkedin": False,
                "publish_to_facebook_groups": True,
                "facebook_groups": ["Wireless Wholesale Buyers", "Phone Resellers"],
                "publication_date_time": "2026-05-29 14:30:00",
                "post_content": "Wholesale devices available from Horizon Wireless.",
                "media_01": "https://example.com/wholesale.mp4",
                "as_draft": False,
                "auto_publish": True,
                "post_type": "POST",
            }
        ],
    )

    response = zapier_social_drafts_response(batch)

    assert response["metricool_publish_to_facebook_groups"] is True
    assert response["metricool_facebook_groups"] == "Wireless Wholesale Buyers, Phone Resellers"


def test_default_metricool_publication_time_uses_next_daily_slot():
    central = ZoneInfo("America/Chicago")
    now = datetime(2026, 5, 26, 9, 0, tzinfo=central)

    assert default_metricool_publication_time(now) == "2026-05-26 10:30:00"


def test_default_metricool_publication_time_uses_evening_and_weekend_slots():
    central = ZoneInfo("America/Chicago")
    now = datetime(2026, 5, 29, 17, 30, tzinfo=central)

    assert default_metricool_publication_time(now) == "2026-05-29 18:00:00"


def test_default_metricool_publication_times_continue_into_saturday():
    central = ZoneInfo("America/Chicago")
    now = datetime(2026, 5, 29, 22, 45, tzinfo=central)

    assert default_metricool_publication_times(3, now) == [
        "2026-05-30 07:30:00",
        "2026-05-30 09:00:00",
        "2026-05-30 10:30:00",
    ]


def test_default_metricool_publication_times_can_start_on_sunday():
    central = ZoneInfo("America/Chicago")
    now = datetime(2026, 5, 29, 9, 0, tzinfo=central)

    assert default_metricool_publication_times(3, now, start_at="2026-05-31 08:00:00") == [
        "2026-05-31 09:00:00",
        "2026-05-31 10:30:00",
        "2026-05-31 12:00:00",
    ]


def test_default_metricool_publication_times_stagger_across_the_day():
    central = ZoneInfo("America/Chicago")
    now = datetime(2026, 5, 26, 7, 0, tzinfo=central)

    assert default_metricool_publication_times(5, now) == [
        "2026-05-26 07:30:00",
        "2026-05-26 09:00:00",
        "2026-05-26 10:30:00",
        "2026-05-26 12:00:00",
        "2026-05-26 13:30:00",
    ]
