from datetime import datetime
from zoneinfo import ZoneInfo

import app.agents as agents_module
from app.integrations import default_metricool_publication_times
from app.main import _zapier_slow_mover_outreach_response
from app.models import InventoryItem, SlowMoverMetric, SlowMoverOutreachRequest


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


def test_slow_mover_outreach_prioritizes_metrics_and_builds_metricool_payloads(monkeypatch):
    items = [
        InventoryItem(
            sku="EBAY-1",
            title="Apple iPhone 12 Pro Max 128GB Pacific Blue Open Box",
            condition="Open box",
            price=350,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/1",
            image_url="https://example.com/iphone.jpg",
            category="Cell Phones & Smartphones",
        ),
        InventoryItem(
            sku="EBAY-2",
            title="Samsung Galaxy A16 5G Open Box Complete in Box",
            condition="Open box",
            price=150,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/2",
            image_url="https://example.com/samsung.jpg",
            category="Cell Phones & Smartphones",
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

    plan = agents_module.create_slow_mover_outreach(
        SlowMoverOutreachRequest(
            slow_mover_metrics=[
                SlowMoverMetric(sku="EBAY-1", days_since_sale=30, views=12, watchers=0, quantity_sold=0),
                SlowMoverMetric(sku="EBAY-2", days_since_sale=10, views=50, watchers=3, quantity_sold=0),
            ],
            max_items=2,
            angles_per_item=2,
            as_draft=False,
            auto_publish=True,
        )
    )

    assert [draft.sku for draft in plan.drafts] == ["EBAY-1", "EBAY-2"]
    assert plan.drafts[0].priority_score > plan.drafts[1].priority_score
    assert plan.drafts[0].comment_keyword == "LINKEBAY1"
    assert "Comment LINKEBAY1" in plan.posts[0].text
    assert len(plan.metricool_payloads) == 4
    first_payload = plan.metricool_payloads[0]
    assert first_payload["facebook"] is True
    assert first_payload["instagram"] is True
    assert first_payload["tiktok"] is True
    assert first_payload["linkedin"] is True
    assert first_payload["as_draft"] is False
    assert first_payload["auto_publish"] is True
    assert first_payload["comment_keyword"] == "LINKEBAY1"
    assert first_payload["publication_date_time"] == "2026-05-29 10:30:00"


def test_zapier_slow_mover_response_adds_loop_fields(monkeypatch):
    items = [
        InventoryItem(
            sku="EBAY-366419891578",
            title="Motorola Edge 2025 Black 256GB Open Box",
            condition="Open box",
            price=190,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/366419891578",
            category="Cell Phones & Smartphones",
        )
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: [f"2026-05-30 {hour:02d}:00:00" for hour in range(8, 8 + count)],
    )

    request = SlowMoverOutreachRequest(
        slow_mover_metrics='[{"sku":"EBAY-366419891578","listing_age_days":21,"views":8,"watchers":0,"quantity_sold":0}]',
        angles_per_item=1,
        as_draft=False,
        auto_publish=True,
    )
    response = _zapier_slow_mover_outreach_response(agents_module.create_slow_mover_outreach(request))

    assert response["slow_mover_count"] == 1
    assert response["metricool_payload_count"] == 1
    assert response["publicationDate_items"] == ["2026-05-30 08:00:00"]
    assert response["draft_items"] == [False]
    assert response["comment_keyword_items"] == ["LINK891578"]
    assert response["metricool_comment_keyword_items"] == ["LINK891578"]
    assert response["manychat_reply_items"][0].endswith("https://www.ebay.com/itm/366419891578")


def test_slow_mover_all_phones_looks_past_non_phone_first_item(monkeypatch):
    items = [
        InventoryItem(
            sku="EBAY-WATCH",
            title="Apple Watch Series 11 GPS Cellular Open Box",
            quantity=1,
            ebay_url="https://www.ebay.com/itm/watch",
        ),
        InventoryItem(
            sku="EBAY-PHONE",
            title="Samsung Galaxy Note20 Ultra 5G White Open Box",
            quantity=1,
            ebay_url="https://www.ebay.com/itm/phone",
        ),
    ]
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository(items))
    monkeypatch.setattr(
        agents_module,
        "default_metricool_publication_times",
        lambda count, start_at=None: ["2026-06-01 08:00:00"] * count,
    )

    plan = agents_module.create_slow_mover_outreach(
        SlowMoverOutreachRequest(max_items=1, angles_per_item=1, as_draft=True, auto_publish=False)
    )

    assert [draft.sku for draft in plan.drafts] == ["EBAY-PHONE"]
    assert len(plan.metricool_payloads) == 1
