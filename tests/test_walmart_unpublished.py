import asyncio

import app.main as main_module
from app.inventory import InventoryRepository
from app.models import InventoryItem


class FakeWalmartClient:
    def __init__(self):
        self.offer_payloads = []
        self.inventory_payloads = []

    async def submit_offer_match_feed(self, payload):
        self.offer_payloads.append(payload)
        return {"feed_id": "OFFER-FEED", "status": "submitted"}

    async def submit_inventory_feed(self, payload):
        self.inventory_payloads.append(payload)
        return {"feed_id": "INVENTORY-FEED", "status": "submitted"}


def test_unpublished_batch_submits_once_with_zero_inventory(monkeypatch, tmp_path):
    repository = InventoryRepository(tmp_path / "inventory.db")
    item = InventoryItem(
        sku="EBAY-123",
        ebay_item_id="123",
        title="Samsung Galaxy Z Flip5 512GB Gray",
        condition="Open box",
        price=449,
        quantity=5,
        image_url="https://example.com/phone.jpg",
        listing_status="ACTIVE",
        source="ebay-trading-api",
        item_specifics={"Shipping Weight": "0.5 lb"},
    )
    repository.upsert_items([item])
    repository.upsert_walmart_drafts(
        [
            {
                "sku": item.sku,
                "ebay_item_id": item.ebay_item_id,
                "source_snapshot": item.model_dump(mode="json"),
                "prepared_listing": {
                    "product_identifier": {"type": "GTIN", "value": "00887276900123"}
                },
                "catalog_query": item.title,
                "catalog_candidates": [],
                "catalog_status": "candidates_found",
                "status": "draft_verified_match",
                "missing_fields": [],
            }
        ]
    )
    walmart_client = FakeWalmartClient()

    async def fake_preflight(import_request, *, force_verify_catalog=False):
        assert force_verify_catalog is True
        assert import_request.overrides[item.sku].product_id == "00887276900123"
        return {
            "items": [{"sku": item.sku, "ready": True}],
            "payload": {
                "MPItemFeedHeader": {"version": "4.2"},
                "MPItem": [{"Item": {"sku": item.sku, "price": 449}}],
            },
        }

    monkeypatch.setattr(main_module, "repository", repository)
    monkeypatch.setattr(main_module, "walmart_client", walmart_client)
    monkeypatch.setattr(main_module, "_prepare_walmart_import", fake_preflight)

    first = asyncio.run(main_module._submit_unpublished_batch_once("batch-1"))
    second = asyncio.run(main_module._submit_unpublished_batch_once("batch-1"))

    assert first["status"] == "submitted"
    assert second["status"] == "submitted"
    assert len(walmart_client.offer_payloads) == 1
    assert len(walmart_client.inventory_payloads) == 1
    assert walmart_client.inventory_payloads[0]["Inventory"][0]["quantity"]["amount"] == 0
    assert repository.walmart_drafts()[0]["status"] == "unpublished_offer_submitted"


def test_unpublished_batch_uses_public_identifier_then_requires_spec_match(monkeypatch, tmp_path):
    repository = InventoryRepository(tmp_path / "inventory.db")
    item = InventoryItem(
        sku="EBAY-PUBLIC",
        ebay_item_id="public",
        title="Exact public product",
        condition="Open box",
        price=299,
        quantity=2,
        image_url="https://example.com/public.jpg",
        listing_status="ACTIVE",
        source="ebay-trading-api",
        item_specifics={"Shipping Weight": "1 lb"},
    )
    repository.upsert_items([item])
    repository.upsert_walmart_drafts(
        [
            {
                "sku": item.sku,
                "ebay_item_id": item.ebay_item_id,
                "source_snapshot": item.model_dump(mode="json"),
                "prepared_listing": {"product_identifier": None},
                "catalog_query": item.title,
                "catalog_candidates": [],
                "catalog_status": "candidates_found",
                "status": "draft_needs_review",
                "missing_fields": ["product_identifier"],
            }
        ]
    )
    walmart_client = FakeWalmartClient()

    async def fake_preflight(import_request, *, force_verify_catalog=False):
        assert force_verify_catalog is True
        assert import_request.skus == [item.sku]
        assert import_request.overrides[item.sku].product_id == "123456789012"
        return {
            "items": [{"sku": item.sku, "ready": True}],
            "payload": {
                "MPItemFeedHeader": {"version": "4.2"},
                "MPItem": [{"Item": {"sku": item.sku, "price": 299}}],
            },
        }

    monkeypatch.setattr(main_module, "repository", repository)
    monkeypatch.setattr(main_module, "walmart_client", walmart_client)
    monkeypatch.setattr(main_module, "_prepare_walmart_import", fake_preflight)
    monkeypatch.setattr(
        main_module,
        "PUBLIC_CATALOG_IDENTIFIERS",
        {
            item.sku: {
                "product_id_type": "UPC",
                "product_id": "123456789012",
                "source_url": "https://example.com/public-record",
            }
        },
    )

    result = asyncio.run(main_module._submit_unpublished_batch_once("public-batch"))

    assert result["status"] == "submitted"
    assert result["matched_skus"] == [item.sku]
    assert walmart_client.inventory_payloads[0]["Inventory"][0]["quantity"]["amount"] == 0
