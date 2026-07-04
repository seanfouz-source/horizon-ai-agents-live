import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import app.agents as agents_module
from app.integrations import default_metricool_publication_times
from app.inventory import InventoryRepository
from app.models import InventoryItem, SocialDraftRequest


@pytest.fixture(autouse=True)
def disable_live_metricool_lookup(monkeypatch):
    async def fake_scheduled_counts(*args, **kwargs):
        return {}

    monkeypatch.setattr(agents_module, "scheduled_post_counts_by_day", fake_scheduled_counts)


class FakeRepository:
    def __init__(self, items):
        self.items = items

    def all_promotable(self, limit=12):
        return self.items[:limit]

    def search(self, query, limit=8):
        query = query.lower()
        return [item for item in self.items if query in item.title.lower()][:limit]

    def get(self, sku):
        return next((item for item in self.items if item.sku == sku), None)


def test_all_inventory_mode_creates_one_payload_per_item_cross_posted(monkeypatch):
    items = [
        InventoryItem(
            sku="EBAY-1",
            title="Apple iPhone 14 Pro Max - Gold 128GB",
            condition="Open box",
            price=565,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/1",
            image_url="https://example.com/iphone.jpg",
        ),
        InventoryItem(
            sku="EBAY-2",
            title="Samsung Galaxy S25 - Blue 128GB",
            condition="Open box",
            price=650,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/2",
            image_url="https://example.com/samsung.jpg",
        ),
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: [f"2026-05-29 {hour:02d}:00:00" for hour in range(8, 8 + count)],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(
                promote_all_inventory=True,
                brand_name="Horizon Wireless",
                platforms=["facebook", "instagram", "tiktok", "linkedin"],
                as_draft=False,
                auto_publish=True,
            )
        )
    )

    assert len(batch.posts) == 2
    assert [post.product_sku for post in batch.posts] == ["EBAY-1", "EBAY-2"]
    assert len(batch.metricool_payloads) == 2
    expected_media_by_sku = {
        "EBAY-1": "https://example.com/iphone.jpg",
        "EBAY-2": "https://example.com/samsung.jpg",
    }
    for payload in batch.metricool_payloads:
        assert payload["facebook"] is True
        assert payload["instagram"] is True
        assert payload["tiktok"] is True
        assert payload["linkedin"] is True
        assert payload["as_draft"] is False
        assert payload["auto_publish"] is True
        assert payload["media_01"] == expected_media_by_sku[payload["product_sku"]]
        assert payload["publication_date_time"].startswith("2026-05-29")
        assert payload["post_content"].startswith("Horizon Wireless Summer Sale spotlight:")
        assert "Shop the full Horizon Wireless sale on our eBay store: https://www.ebay.com/str/exactspec" in payload[
            "post_content"
        ]
        assert "\nView this listing: https://www.ebay.com/itm/" in payload["post_content"]
        assert payload["buy_url"] == payload["ebay_url"]
        assert payload["link_url"] == payload["ebay_url"]
        assert payload["facebook_link_url"] == payload["ebay_url"]


def test_all_inventory_mode_caps_tiktok_without_stopping_other_platforms(monkeypatch):
    items = [
        InventoryItem(
            sku=f"EBAY-{index}",
            title=f"Apple iPhone 14 Pro Max - Gold {index}",
            condition="Open box",
            price=565,
            quantity=1,
            ebay_url=f"https://www.ebay.com/itm/{index}",
            image_url=f"https://example.com/iphone-{index}.jpg",
        )
        for index in range(1, 6)
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: [f"2026-06-12 {hour:02d}:00:00" for hour in range(8, 8 + count)],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(
                promote_all_inventory=True,
                brand_name="Horizon Wireless",
                platforms=["facebook", "instagram", "tiktok", "linkedin"],
                tiktok_daily_post_cap=3,
                as_draft=False,
                auto_publish=True,
            )
        )
    )

    assert len(batch.metricool_payloads) == 5
    assert [payload["tiktok"] for payload in batch.metricool_payloads] == [True, True, True, False, False]
    assert all(payload["facebook"] for payload in batch.metricool_payloads)
    assert all(payload["instagram"] for payload in batch.metricool_payloads)
    assert all(payload["linkedin"] for payload in batch.metricool_payloads)
    assert "TikTok auto-publish was kept to 3 posts per scheduled day" in batch.notes


def test_all_inventory_mode_staggers_from_publish_after(monkeypatch):
    items = [
        InventoryItem(
            sku="EBAY-1",
            title="Apple iPhone 14 Pro Max - Gold 128GB",
            quantity=1,
            ebay_url="https://www.ebay.com/itm/1",
            image_url="https://example.com/iphone.jpg",
        ),
        InventoryItem(
            sku="EBAY-2",
            title="Samsung Galaxy S25 - Blue 128GB",
            quantity=1,
            ebay_url="https://www.ebay.com/itm/2",
            image_url="https://example.com/samsung.jpg",
        ),
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    central = ZoneInfo("America/Chicago")
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: default_metricool_publication_times(
            count,
            now=datetime(2026, 5, 29, 9, 0, tzinfo=central),
            start_at=start_at,
        ),
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(
                promote_all_inventory=True,
                brand_name="Horizon Wireless",
                platforms=["facebook"],
                publish_after="2026-05-30 07:00:00",
                as_draft=False,
                auto_publish=True,
            )
        )
    )

    assert [payload["publication_date_time"] for payload in batch.metricool_payloads] == [
        "2026-05-30 09:00:00",
        "2026-05-30 18:00:00",
    ]


def test_all_inventory_mode_can_filter_by_query(monkeypatch):
    items = [
        InventoryItem(sku="EBAY-1", title="Apple iPhone 14 Pro Max", quantity=1, image_url="https://example.com/iphone.jpg"),
        InventoryItem(sku="EBAY-2", title="Samsung Galaxy S25", quantity=1, image_url="https://example.com/samsung.jpg"),
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: ["2026-05-29 08:00:00"],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(promote_all_inventory=True, query="Samsung", brand_name="Horizon Wireless")
        )
    )

    assert [post.product_sku for post in batch.posts] == ["EBAY-2"]


def test_all_inventory_mode_excludes_demo_rows(monkeypatch):
    items = [
        InventoryItem(
            sku="HZ-DEMO-001",
            title="Demo Vintage Camera Lens",
            quantity=1,
            ebay_item_id="123456789001",
            ebay_url="https://www.ebay.com/itm/123456789001",
            image_url="https://example.com/lens.jpg",
            source="csv",
        ),
        InventoryItem(
            sku="EBAY-1",
            title="Apple iPhone 14 Pro Max",
            quantity=1,
            ebay_item_id="1",
            ebay_url="https://www.ebay.com/itm/1",
            image_url="https://example.com/iphone.jpg",
            source="ebay-browse-api",
        ),
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: ["2026-05-29 08:00:00"],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(promote_all_inventory=True, query="all inventory", brand_name="Horizon Wireless")
        )
    )

    assert [post.product_sku for post in batch.posts] == ["EBAY-1"]


def test_all_inventory_mode_keeps_listing_image_with_sale_and_store_page_overrides(monkeypatch):
    items = [
        InventoryItem(
            sku="EBAY-1",
            title="Apple iPhone 14 Pro Max",
            condition="Open box",
            price=565,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/1",
            image_url="https://example.com/iphone.jpg",
        )
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: ["2026-05-29 08:00:00"],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(
                promote_all_inventory=True,
                brand_name="Horizon Wireless",
                sale_name="Horizon Wireless Summer Sale",
                store_url="https://www.ebay.com/str/exactspec",
                sale_media_url="https://example.com/summer-sale.jpg",
            )
        )
    )

    assert batch.campaign_name == "Horizon Wireless Summer Sale inventory promotion"
    assert "Horizon Wireless Summer Sale spotlight: Apple iPhone 14 Pro Max" in batch.metricool_payloads[0][
        "post_content"
    ]
    assert "Shop the full Horizon Wireless sale on our eBay store: https://www.ebay.com/str/exactspec" in batch.metricool_payloads[0][
        "post_content"
    ]
    assert batch.metricool_payloads[0]["media_01"] == "https://example.com/iphone.jpg"


def test_all_inventory_mode_uses_listing_image_even_with_explicit_media_url(monkeypatch):
    items = [
        InventoryItem(
            sku="EBAY-1",
            title="Apple iPhone 14 Pro Max",
            condition="Open box",
            price=565,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/1",
            image_url="https://example.com/iphone.jpg",
        )
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: ["2026-05-29 08:00:00"],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(
                promote_all_inventory=True,
                brand_name="Horizon Wireless",
                media_url="https://example.com/campaign-video.mp4",
            )
        )
    )

    assert batch.metricool_payloads[0]["media_01"] == "https://example.com/iphone.jpg"


def test_all_phones_query_excludes_non_phone_inventory(monkeypatch):
    items = [
        InventoryItem(sku="EBAY-1", title="Apple iPhone 14 Pro Max", quantity=1, image_url="https://example.com/iphone.jpg"),
        InventoryItem(sku="HZ-DEMO-001", title="Demo Vintage Camera Lens", quantity=1, image_url="https://example.com/lens.jpg"),
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: ["2026-05-29 08:00:00"],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(promote_all_inventory=True, query="all phones", brand_name="Horizon Wireless")
        )
    )

    assert [post.product_sku for post in batch.posts] == ["EBAY-1"]


def test_all_phones_query_looks_past_non_phone_first_items(monkeypatch):
    items = [
        InventoryItem(sku="HZ-DEMO-001", title="Demo Vintage Camera Lens", quantity=1, image_url="https://example.com/lens.jpg"),
        InventoryItem(sku="EBAY-1", title="Apple iPhone 14 Pro Max", quantity=1, image_url="https://example.com/iphone.jpg"),
        InventoryItem(sku="EBAY-2", title="Samsung Galaxy S25", quantity=1, image_url="https://example.com/samsung.jpg"),
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: [f"2026-05-29 {hour:02d}:00:00" for hour in range(8, 8 + count)],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(
                promote_all_inventory=True,
                query="all phones",
                max_products_per_run=2,
                brand_name="Horizon Wireless",
            )
        )
    )

    assert [post.product_sku for post in batch.posts] == ["EBAY-1", "EBAY-2"]


def test_all_inventory_mode_records_history_and_blocks_same_day_rerun(tmp_path, monkeypatch):
    repository = InventoryRepository(tmp_path / "inventory.db")
    repository.upsert_items(
        [
            InventoryItem(
                sku=f"EBAY-{index}",
                ebay_item_id=str(index),
                title=f"Apple iPhone 14 Pro Max - Gold {index}",
                condition="Open box",
                price=565,
                quantity=1,
                ebay_url=f"https://www.ebay.com/itm/{index}",
                image_url=f"https://example.com/iphone-{index}.jpg",
                listing_status="ACTIVE",
            )
            for index in range(1, 4)
        ]
    )
    monkeypatch.setattr(agents_module, "get_repository", lambda: repository)
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: [
            "2026-07-02 09:00:00",
            "2026-07-02 18:00:00",
            "2026-07-03 09:00:00",
            "2026-07-03 18:00:00",
        ][:count],
    )

    request = SocialDraftRequest(
        promote_all_inventory=True,
        max_products_per_run=3,
        brand_name="Horizon Wireless",
        platforms=["facebook", "instagram"],
        as_draft=False,
        auto_publish=True,
    )

    first_batch = asyncio.run(agents_module.create_social_drafts(request))
    second_batch = asyncio.run(agents_module.create_social_drafts(request))

    assert [payload["publication_date_time"] for payload in first_batch.metricool_payloads] == [
        "2026-07-02 09:00:00",
        "2026-07-02 18:00:00",
        "2026-07-03 09:00:00",
    ]
    assert repository.social_post_count_for_day("2026-07-02") == 2
    assert repository.social_post_count_for_day("2026-07-03") == 1
    assert second_batch.posts == []


def test_all_inventory_mode_respects_existing_daily_history(tmp_path, monkeypatch):
    repository = InventoryRepository(tmp_path / "inventory.db")
    repository.record_social_post(
        ebay_item_id="old-1",
        sku="EBAY-OLD-1",
        title="Existing Metricool post 1",
        item_url="https://www.ebay.com/itm/old1",
        image_url="https://example.com/old1.jpg",
        caption="Existing post",
        scheduled_at="2026-07-02 09:00:00",
        platform="facebook,instagram",
    )
    repository.record_social_post(
        ebay_item_id="old-2",
        sku="EBAY-OLD-2",
        title="Existing Metricool post 2",
        item_url="https://www.ebay.com/itm/old2",
        image_url="https://example.com/old2.jpg",
        caption="Existing post",
        scheduled_at="2026-07-02 18:00:00",
        platform="facebook,instagram",
    )
    repository.upsert_items(
        [
            InventoryItem(
                sku="EBAY-3",
                ebay_item_id="3",
                title="Samsung Galaxy S25 Blue 128GB",
                quantity=1,
                ebay_url="https://www.ebay.com/itm/3",
                image_url="https://example.com/samsung.jpg",
                listing_status="ACTIVE",
            )
        ]
    )
    monkeypatch.setattr(agents_module, "get_repository", lambda: repository)
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: [
            "2026-07-02 09:00:00",
            "2026-07-02 18:00:00",
            "2026-07-03 09:00:00",
            "2026-07-03 18:00:00",
        ][:count],
    )

    batch = asyncio.run(
        agents_module.create_social_drafts(
            SocialDraftRequest(
                promote_all_inventory=True,
                max_products_per_run=1,
                brand_name="Horizon Wireless",
                platforms=["facebook"],
            )
        )
    )

    assert [payload["publication_date_time"] for payload in batch.metricool_payloads] == ["2026-07-03 09:00:00"]
