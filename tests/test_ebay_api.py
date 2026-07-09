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
        return self._call_handler(path, params or {}, headers or {}, "GET")

    async def post(self, path, data=None, headers=None):
        return self._call_handler(path, data or {}, headers or {}, "POST")

    def _call_handler(self, path, payload, headers, method):
        arg_count = getattr(getattr(self.handler, "__code__", None), "co_argcount", 2)
        if arg_count >= 4:
            return self.handler(path, payload, headers, method)
        return self.handler(path, payload)


def test_ebay_client_falls_back_to_browse_api_and_selects_primary_image(monkeypatch):
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
                    "shippingOptions": [
                        {
                            "shippingCost": {"value": "0.00", "currency": "USD"},
                        }
                    ],
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
    assert items[0].item_specifics["Shipping"] == "Free Shipping"


def test_ebay_client_retries_temporary_browse_api_failures(monkeypatch):
    calls = {"search": 0}

    async def fake_sleep(delay):
        return None

    def handler(path, params):
        request = httpx.Request("GET", f"https://api.ebay.com{path}")
        if path == "/sell/inventory/v1/inventory_item":
            return httpx.Response(200, json={"inventoryItems": [], "total": 0}, request=request)
        if path == "/buy/browse/v1/item_summary/search":
            calls["search"] += 1
            if calls["search"] == 1:
                return httpx.Response(503, json={"error": "temporary"}, request=request)
            return httpx.Response(
                200,
                json={
                    "itemSummaries": [
                        {
                            "itemId": "v1|123456789012|0",
                            "legacyItemId": "123456789012",
                            "title": "Samsung Galaxy S25 Blue",
                            "itemWebUrl": "https://www.ebay.com/itm/123456789012",
                            "image": {"imageUrl": "https://i.ebayimg.com/images/g/demo/s-l1600.jpg"},
                            "estimatedAvailabilities": [
                                {
                                    "estimatedAvailabilityStatus": "IN_STOCK",
                                    "estimatedAvailableQuantity": 1,
                                }
                            ],
                        }
                    ],
                    "total": 1,
                },
                request=request,
            )
        if path == "/buy/browse/v1/item/v1|123456789012|0":
            return httpx.Response(
                404,
                json={},
                request=request,
            )
        raise AssertionError(f"Unexpected eBay path: {path}")

    monkeypatch.setattr(ebay_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(ebay_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(handler))
    settings = SimpleNamespace(
        ebay_access_token="token",
        ebay_marketplace_id="EBAY_US",
        ebay_seller_username="exactspec-electronics",
        ebay_browse_search_query=" ",
    )

    items = asyncio.run(EbayClient(settings).fetch_inventory_items())

    assert calls["search"] == 2
    assert [item.ebay_item_id for item in items] == ["123456789012"]


def test_ebay_client_skips_browse_listing_without_primary_image(monkeypatch, caplog):
    def handler(path, params):
        request = httpx.Request("GET", f"https://api.ebay.com{path}")
        if path == "/sell/inventory/v1/inventory_item":
            return httpx.Response(200, json={"inventoryItems": [], "total": 0}, request=request)
        if path == "/buy/browse/v1/item_summary/search":
            return httpx.Response(
                200,
                json={
                    "itemSummaries": [
                        {
                            "itemId": "v1|123456789012|0",
                            "legacyItemId": "123456789012",
                            "title": "Samsung Galaxy S25 Blue",
                            "itemWebUrl": "https://www.ebay.com/itm/123456789012",
                            "estimatedAvailabilities": [
                                {
                                    "estimatedAvailabilityStatus": "IN_STOCK",
                                    "estimatedAvailableQuantity": 1,
                                }
                            ],
                        }
                    ],
                    "total": 1,
                },
                request=request,
            )
        if path == "/buy/browse/v1/item/v1|123456789012|0":
            return httpx.Response(404, json={}, request=request)
        raise AssertionError(f"Unexpected eBay path: {path}")

    monkeypatch.setattr(ebay_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(handler))
    settings = SimpleNamespace(
        ebay_access_token="token",
        ebay_marketplace_id="EBAY_US",
        ebay_seller_username="exactspec-electronics",
        ebay_browse_search_query=" ",
    )

    with caplog.at_level("WARNING", logger="app.ebay"):
        items = asyncio.run(EbayClient(settings).fetch_inventory_items())

    assert items == []
    assert "listing has no valid primary eBay image" in caplog.text


def test_ebay_client_refreshes_access_token_before_sync(monkeypatch):
    requests = []

    def handler(path, payload, headers, method):
        requests.append((method, path, payload, headers.get("Authorization", "")))
        request = httpx.Request(method, f"https://api.ebay.com{path}")
        if method == "POST" and path == "/identity/v1/oauth2/token":
            assert payload["scope"] == "https://api.ebay.com/oauth/api_scope"
            assert headers["Authorization"].startswith("Basic ")
            if payload["grant_type"] == "refresh_token":
                assert payload["refresh_token"] == "refresh-token"
                return httpx.Response(200, json={"access_token": "fresh-access-token", "expires_in": 7200}, request=request)
            if payload["grant_type"] == "client_credentials":
                return httpx.Response(200, json={"access_token": "application-access-token", "expires_in": 7200}, request=request)
        if path == "/sell/inventory/v1/inventory_item":
            assert headers["Authorization"] == "Bearer fresh-access-token"
            return httpx.Response(200, json={"inventoryItems": [], "total": 0}, request=request)
        if path == "/buy/browse/v1/item_summary/search":
            assert headers["Authorization"] == "Bearer application-access-token"
            return httpx.Response(200, json={"itemSummaries": [], "total": 0}, request=request)
        raise AssertionError(f"Unexpected eBay request: {method} {path}")

    monkeypatch.setattr(ebay_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(handler))
    settings = SimpleNamespace(
        ebay_access_token=None,
        ebay_client_id="client-id",
        ebay_client_secret="client-secret",
        ebay_refresh_token="refresh-token",
        ebay_oauth_scopes="https://api.ebay.com/oauth/api_scope",
        ebay_marketplace_id="EBAY_US",
        ebay_seller_username="exactspec-electronics",
        ebay_browse_search_query=" ",
    )

    items = asyncio.run(EbayClient(settings).fetch_inventory_items())

    assert items == []
    assert requests[0][0:2] == ("POST", "/identity/v1/oauth2/token")
    assert requests[1][0:2] == ("GET", "/sell/inventory/v1/inventory_item")


def test_ebay_client_mints_application_token_with_client_credentials(monkeypatch):
    requests = []

    def handler(path, payload, headers, method):
        requests.append((method, path, payload, headers.get("Authorization", "")))
        request = httpx.Request(method, f"https://api.ebay.com{path}")
        if method == "POST" and path == "/identity/v1/oauth2/token":
            assert payload["grant_type"] == "client_credentials"
            assert payload["scope"] == "https://api.ebay.com/oauth/api_scope"
            assert headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "application-access-token", "expires_in": 7200}, request=request)
        if path == "/sell/inventory/v1/inventory_item":
            assert headers["Authorization"] == "Bearer application-access-token"
            return httpx.Response(200, json={"inventoryItems": [], "total": 0}, request=request)
        if path == "/buy/browse/v1/item_summary/search":
            assert headers["Authorization"] == "Bearer application-access-token"
            return httpx.Response(200, json={"itemSummaries": [], "total": 0}, request=request)
        raise AssertionError(f"Unexpected eBay request: {method} {path}")

    monkeypatch.setattr(ebay_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(handler))
    settings = SimpleNamespace(
        ebay_access_token=None,
        ebay_client_id="client-id",
        ebay_client_secret="client-secret",
        ebay_refresh_token=None,
        ebay_oauth_scopes="https://api.ebay.com/oauth/api_scope",
        ebay_marketplace_id="EBAY_US",
        ebay_seller_username="exactspec-electronics",
        ebay_browse_search_query=" ",
    )

    items = asyncio.run(EbayClient(settings).fetch_inventory_items())

    assert items == []
    assert requests[0][0:2] == ("POST", "/identity/v1/oauth2/token")
    assert requests[1][0:2] == ("GET", "/sell/inventory/v1/inventory_item")


def test_ebay_client_uses_application_token_for_browse_after_refresh_token_sell_sync(monkeypatch):
    requests = []

    def handler(path, payload, headers, method):
        requests.append((method, path, payload, headers.get("Authorization", "")))
        request = httpx.Request(method, f"https://api.ebay.com{path}")
        if method == "POST" and path == "/identity/v1/oauth2/token":
            if payload["grant_type"] == "refresh_token":
                return httpx.Response(200, json={"access_token": "seller-user-token"}, request=request)
            if payload["grant_type"] == "client_credentials":
                return httpx.Response(200, json={"access_token": "browse-application-token"}, request=request)
        if path == "/sell/inventory/v1/inventory_item":
            assert headers["Authorization"] == "Bearer seller-user-token"
            return httpx.Response(200, json={"inventoryItems": [], "total": 0}, request=request)
        if path == "/buy/browse/v1/item_summary/search":
            assert headers["Authorization"] == "Bearer browse-application-token"
            return httpx.Response(200, json={"itemSummaries": [], "total": 0}, request=request)
        raise AssertionError(f"Unexpected eBay request: {method} {path}")

    monkeypatch.setattr(ebay_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(handler))
    settings = SimpleNamespace(
        ebay_access_token=None,
        ebay_client_id="client-id",
        ebay_client_secret="client-secret",
        ebay_refresh_token="refresh-token",
        ebay_oauth_scopes="https://api.ebay.com/oauth/api_scope",
        ebay_marketplace_id="EBAY_US",
        ebay_seller_username="exactspec-electronics",
        ebay_browse_search_query=" ",
    )

    items = asyncio.run(EbayClient(settings).fetch_inventory_items())

    assert items == []
    assert requests[0][2]["grant_type"] == "refresh_token"
    assert requests[2][2]["grant_type"] == "client_credentials"


def test_ebay_client_renews_application_token_once_after_browse_401(monkeypatch):
    token_calls = 0
    browse_authorizations = []

    def handler(path, payload, headers, method):
        nonlocal token_calls
        request = httpx.Request(method, f"https://api.ebay.com{path}")
        if method == "POST" and path == "/identity/v1/oauth2/token":
            token_calls += 1
            assert payload["grant_type"] == "client_credentials"
            return httpx.Response(200, json={"access_token": f"app-token-{token_calls}"}, request=request)
        if path == "/buy/browse/v1/item_summary/search":
            browse_authorizations.append(headers["Authorization"])
            if len(browse_authorizations) == 1:
                return httpx.Response(401, json={"error": "unauthorized"}, request=request)
            return httpx.Response(
                200,
                json={
                    "itemSummaries": [
                        {
                            "itemId": "v1|123456789012|0",
                            "legacyItemId": "123456789012",
                            "title": "Samsung Galaxy S25 Blue",
                            "itemWebUrl": "https://www.ebay.com/itm/123456789012",
                            "image": {"imageUrl": "https://i.ebayimg.com/images/g/demo/s-l1600.jpg"},
                            "estimatedAvailabilities": [
                                {
                                    "estimatedAvailabilityStatus": "IN_STOCK",
                                    "estimatedAvailableQuantity": 1,
                                }
                            ],
                        }
                    ],
                    "total": 1,
                },
                request=request,
            )
        if path == "/buy/browse/v1/item/v1|123456789012|0":
            return httpx.Response(404, json={}, request=request)
        raise AssertionError(f"Unexpected eBay request: {method} {path}")

    monkeypatch.setattr(ebay_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeAsyncClient(handler))
    settings = SimpleNamespace(
        ebay_access_token="Bearer stale-token",
        ebay_client_id="client-id",
        ebay_client_secret="client-secret",
        ebay_refresh_token=None,
        ebay_oauth_scopes="https://api.ebay.com/oauth/api_scope",
        ebay_marketplace_id="EBAY_US",
        ebay_seller_username="exactspec-electronics",
        ebay_browse_search_query=" ",
    )

    items = asyncio.run(EbayClient(settings)._fetch_browse_seller_items("exactspec-electronics"))

    assert token_calls == 2
    assert browse_authorizations == ["Bearer app-token-1", "Bearer app-token-2"]
    assert [item.ebay_item_id for item in items] == ["123456789012"]
