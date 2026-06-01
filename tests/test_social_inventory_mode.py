import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import app.agents as agents_module
from app.integrations import default_metricool_publication_times
from app.models import InventoryItem, SocialDraftRequest


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
        ),
        InventoryItem(
            sku="EBAY-2",
            title="Samsung Galaxy S25 - Blue 128GB",
            condition="Open box",
            price=650,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/2",
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
    for payload in batch.metricool_payloads:
        assert payload["facebook"] is True
        assert payload["instagram"] is True
        assert payload["tiktok"] is True
        assert payload["linkedin"] is True
        assert payload["as_draft"] is False
        assert payload["auto_publish"] is True
        assert payload["media_01"].endswith(f"{payload['product_sku']}.jpg")
        assert payload["publication_date_time"].startswith("2026-05-29")
        assert "\nBuy on eBay: https://www.ebay.com/itm/" in payload["post_content"]
        assert payload["buy_url"] == payload["ebay_url"]
        assert payload["link_url"] == payload["ebay_url"]
        assert payload["facebook_link_url"] == payload["ebay_url"]


def test_all_inventory_mode_staggers_from_publish_after(monkeypatch):
    items = [
        InventoryItem(
            sku="EBAY-1",
            title="Apple iPhone 14 Pro Max - Gold 128GB",
            quantity=1,
            ebay_url="https://www.ebay.com/itm/1",
        ),
        InventoryItem(
            sku="EBAY-2",
            title="Samsung Galaxy S25 - Blue 128GB",
            quantity=1,
            ebay_url="https://www.ebay.com/itm/2",
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
        "2026-05-30 07:30:00",
        "2026-05-30 09:00:00",
    ]


def test_all_inventory_mode_can_filter_by_query(monkeypatch):
    items = [
        InventoryItem(sku="EBAY-1", title="Apple iPhone 14 Pro Max", quantity=1),
        InventoryItem(sku="EBAY-2", title="Samsung Galaxy S25", quantity=1),
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


def test_all_phones_query_excludes_non_phone_inventory(monkeypatch):
    items = [
        InventoryItem(sku="EBAY-1", title="Apple iPhone 14 Pro Max", quantity=1),
        InventoryItem(sku="HZ-DEMO-001", title="Demo Vintage Camera Lens", quantity=1),
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
        InventoryItem(sku="HZ-DEMO-001", title="Demo Vintage Camera Lens", quantity=1),
        InventoryItem(sku="EBAY-1", title="Apple iPhone 14 Pro Max", quantity=1),
        InventoryItem(sku="EBAY-2", title="Samsung Galaxy S25", quantity=1),
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
