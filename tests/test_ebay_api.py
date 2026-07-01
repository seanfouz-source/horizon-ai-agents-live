import asyncio
from types import SimpleNamespace

import httpx

import app.ebay as ebay_module
from app.ebay import EbayClient


class FakeAsyncClient:
    def __init__(self, handler, *args, **kwargs):
        self.handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, path, params=None, headers=None):
        return self.handler(path, params or {})


def test_ebay_client_falls_back_to_browse_api_and_selects_best_image(monkeypatch):
    def handler(path, params):
        request = httpx.Request("GET", f"https://api.ebay.com{path}")
        if path == "/sell/inventory/v1/inventory_item":
            return httpx.Response(200, json={"inventoryItems": [], "total": 0}, request=request)
        if path == "/buy/browse/v1/item_summary/search":
            assert params["filter"] == "sellers:{exactspec-electronics}"
            return httpx.Response(
                200,
                json={
                    "itemSummaries": [
                        {
                            "itemId": "v1|123456789012|0",
                            "legacyItemId": "123456789012",
                            "title": "Samsung Galaxy S25 Blue",
                            "itemWebUrl": "https://www.ebay.com/itm/123456789012",
                            "image": {"imageUrl": "https://i.ebayimg.com/images/g/demo/s-l300.jpg"},
                        }
                    ],
                    "total": 1,
                    "limit": 1,
                    "offset": 0,
                },
                request=request,
            )
        if path == "/buy/browse/v1/item/v1|123456789012|0":
            return httpx.Response(
                200,
                json={
                    "itemId": "v1|123456789012|0",
                    "legacyItemId": "123456789012",
                    "title": "Samsung Galaxy S25 Blue",
                    "shortDescription": "Open box phone with box.",
                    "condition": "Open box",
                    "price": {"value": "525.00", "currency": "USD"},
                    "itemWebUrl": "https://www.ebay.com/itm/123456789012",
                    "image": {"imageUrl": "https://i.ebayimg.com/images/g/demo/s-l300.jpg"},
                    "additionalImages": [
                        {"imageUrl": "https://i.ebayimg.com/images/g/demo/s-l1600.jpg"},
                    ],
                    "categoryPath": "Cell Phones & Smartphones",
                    "localizedAspects": [{"name": "Storage Capacity", "value": "128 GB"}],
                    "estimatedAvailabilities": [
                        {
                            "estimatedAvailabilityStatus": "IN_STOCK",
                            "estimatedAvailableQuantity": 2,
                        }
                    ],
                },
                request=request,
            )
        raise AssertionError(f"Unexpected eBay path: {path}")

    monkeypatch.setattr(ebay_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(handler))
    settings = SimpleNamespace(
        ebay_access_token="token",
        ebay_marketplace_id="EBAY_US",
        ebay_seller_username="exactspec-electronics",
        ebay_browse_search_query=" ",
    )

    items = asyncio.run(EbayClient(settings).fetch_inventory_items())

    assert len(items) == 1
    assert items[0].sku == "EBAY-123456789012"
    assert items[0].quantity == 2
    assert items[0].listing_status == "IN_STOCK"
    assert items[0].image_url == "https://i.ebayimg.com/images/g/demo/s-l1600.jpg"
    assert items[0].image_urls == [
        "https://i.ebayimg.com/images/g/demo/s-l300.jpg",
        "https://i.ebayimg.com/images/g/demo/s-l1600.jpg",
    ]
    assert items[0].item_specifics["Storage Capacity"] == "128 GB"
