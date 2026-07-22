import asyncio
from types import SimpleNamespace

import httpx

import app.walmart as walmart_module
from app.models import InventoryItem, WalmartItemOverride
from app.walmart import WalmartMarketplaceClient, build_inventory_feed, build_offer_match_preview


def test_offer_match_preview_maps_ebay_fields():
    item = InventoryItem(
        sku="EBAY-123",
        title="Samsung Galaxy S25 128GB",
        condition="Open box",
        price=525,
        quantity=2,
        image_url="https://i.ebayimg.com/images/g/demo/s-l1600.jpg",
        item_specifics={"UPC": "887276900123", "Shipping Weight": "24 oz"},
        source="ebay-browse-api",
    )

    preview = build_offer_match_preview([item])

    assert preview["ready"] == 1
    assert preview["blocked"] == 0
    offer = preview["payload"]["MPItem"][0]["Item"]
    assert offer["sku"] == "EBAY-123"
    assert offer["productIdentifiers"] == {"productIdType": "UPC", "productId": "887276900123"}
    assert offer["ShippingWeight"] == 1.5
    assert offer["condition"] == "Open Box"
    assert offer["price"] == 525


def test_offer_match_preview_blocks_missing_identifier_and_weight():
    item = InventoryItem(
        sku="EBAY-123",
        title="Phone without Walmart requirements",
        condition="Open box",
        price=100,
        quantity=1,
        source="ebay-store-page",
    )

    preview = build_offer_match_preview([item])

    assert preview["ready"] == 0
    assert preview["blocked"] == 1
    assert preview["payload"]["MPItem"] == []
    assert "Missing a UPC, GTIN, EAN, or ISBN product identifier." in preview["items"][0]["errors"]
    assert "Missing Shipping Weight in pounds." in preview["items"][0]["errors"]


def test_offer_match_preview_accepts_per_sku_overrides():
    item = InventoryItem(
        sku="EBAY-123",
        title="Apple iPhone",
        condition="Used",
        price=350,
        quantity=1,
        image_url="https://i.ebayimg.com/images/g/demo/s-l1600.jpg",
    )
    override = WalmartItemOverride(
        product_id_type="GTIN",
        product_id="00000000000123",
        shipping_weight_lbs=1.25,
        condition="Pre-Owned: Good",
    )

    preview = build_offer_match_preview([item], {item.sku: override})

    assert preview["ready"] == 1
    assert preview["items"][0]["resolved"]["condition"] == "Pre-Owned: Good"
    assert preview["payload"]["MPItem"][0]["Item"]["mainImageUrl"] == item.image_url


def test_offer_match_preview_blocks_required_image_over_url_limit():
    item = InventoryItem(
        sku="EBAY-123",
        title="Pre-owned phone",
        condition="Used - Good",
        price=250,
        quantity=1,
        image_url="https://example.com/" + ("x" * 190) + ".jpg",
        item_specifics={"UPC": "887276900123", "Shipping Weight": "1 lb"},
    )

    preview = build_offer_match_preview([item])

    assert preview["ready"] == 0
    assert "Main image URL exceeds the MP_ITEM_MATCH v4.2 limit" in preview["items"][0]["errors"][0]


def test_inventory_feed_includes_zero_quantity_for_ended_listings():
    payload = build_inventory_feed(
        [
            InventoryItem(sku="EBAY-LIVE", title="Live", quantity=2),
            InventoryItem(sku="EBAY-ENDED", title="Ended", quantity=0, listing_status="ENDED"),
        ]
    )

    assert payload["InventoryHeader"] == {"version": "1.4"}
    assert [row["quantity"]["amount"] for row in payload["Inventory"]] == [2, 0]


class FakeAsyncClient:
    def __init__(self, handler, *args, **kwargs):
        self.handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def post(self, path, data=None, headers=None):
        return self.handler("POST", path, data=data, headers=headers or {})

    async def request(self, method, path, headers=None, **kwargs):
        return self.handler(method, path, headers=headers or {}, **kwargs)


def _settings():
    return SimpleNamespace(
        walmart_client_id="client-id",
        walmart_client_secret="client-secret",
        walmart_api_base_url="https://marketplace.walmartapis.com",
        walmart_service_name="Walmart Marketplace",
        walmart_market="us",
        walmart_channel_type=None,
    )


def test_walmart_client_authenticates_and_submits_match_feed(monkeypatch):
    requests = []

    def handler(method, path, headers, **kwargs):
        requests.append((method, path, headers, kwargs))
        request = httpx.Request(method, f"https://marketplace.walmartapis.com{path}", headers=headers)
        if path == "/v3/token":
            assert headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "access-token", "expires_in": 900}, request=request)
        if path == "/v3/feeds":
            assert headers["WM_SEC.ACCESS_TOKEN"] == "access-token"
            assert kwargs["params"] == {"feedType": "MP_ITEM_MATCH"}
            return httpx.Response(200, json={"feedId": "FEED@123"}, request=request)
        raise AssertionError(f"Unexpected Walmart request: {method} {path}")

    monkeypatch.setattr(
        walmart_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(handler, *args, **kwargs),
    )
    client = WalmartMarketplaceClient(_settings())

    result = asyncio.run(
        client.submit_offer_match_feed(
            {
                "MPItemFeedHeader": {"version": "4.2"},
                "MPItem": [{"Item": {"sku": "EBAY-123"}}],
            }
        )
    )

    assert result["feed_id"] == "FEED@123"
    assert [request[1] for request in requests] == ["/v3/token", "/v3/feeds"]


def test_walmart_catalog_search_reports_match(monkeypatch):
    def handler(method, path, headers, **kwargs):
        request = httpx.Request(method, f"https://marketplace.walmartapis.com{path}", headers=headers)
        if path == "/v3/token":
            return httpx.Response(200, json={"access_token": "access-token"}, request=request)
        if path == "/v3/items/walmart/search":
            assert kwargs["params"] == {"upc": "887276900123", "responseFormat": "SPEC"}
            return httpx.Response(
                200,
                json={"items": [{"feedType": "MP_ITEM_MATCH", "version": "4.2"}]},
                request=request,
            )
        raise AssertionError(f"Unexpected Walmart request: {method} {path}")

    monkeypatch.setattr(
        walmart_module.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeAsyncClient(handler, *args, **kwargs),
    )

    result = asyncio.run(WalmartMarketplaceClient(_settings()).search_catalog("UPC", "887276900123"))

    assert result["matched"] is True
    assert result["feed_type"] == "MP_ITEM_MATCH"
