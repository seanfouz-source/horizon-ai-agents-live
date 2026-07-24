import asyncio
from types import SimpleNamespace

import httpx

import app.ebay as ebay_module
from app.ebay import EbayClient
from app.ebay_draft_batch import inventory_sheet_missing_drafts


def _settings():
    return SimpleNamespace(
        ebay_access_token="user-token",
        ebay_client_id=None,
        ebay_client_secret=None,
        ebay_refresh_token=None,
        ebay_oauth_scopes="https://api.ebay.com/oauth/api_scope/sell.inventory",
        ebay_marketplace_id="EBAY_US",
    )


def _catalog_product(title: str, epid: str = "12345") -> dict:
    return {
        "epid": epid,
        "title": title,
        "image": {"imageUrl": "https://i.ebayimg.com/images/g/catalog/s-l1600.jpg"},
        "additionalImages": [
            {"imageUrl": "https://i.ebayimg.com/images/g/catalog-two/s-l1600.jpg"}
        ],
        "aspects": [],
    }


def test_inventory_sheet_batch_contains_only_the_69_missing_variants():
    drafts = inventory_sheet_missing_drafts()

    assert len(drafts) == 69
    assert sum(draft.quantity for draft in drafts) == 416
    assert {draft.sheet_row for draft in drafts} == set(range(2, 73)) - {13, 54}
    assert len({draft.sku for draft in drafts}) == 69
    assert all(len(draft.title) <= 80 for draft in drafts)


def test_catalog_match_requires_model_storage_and_color():
    draft = next(
        item for item in inventory_sheet_missing_drafts() if item.sheet_row == 48
    )
    exact = _catalog_product("Apple iPhone 13 Pro Max 256GB Sierra Blue Unlocked")
    wrong_storage = _catalog_product("Apple iPhone 13 Pro Max 128GB Sierra Blue Unlocked")

    assert EbayClient._catalog_match(draft, exact)["exact"] is True
    assert EbayClient._catalog_match(draft, wrong_storage)["exact"] is False
    assert EbayClient._select_catalog_product(draft, [wrong_storage, exact]) == exact


class FakeDraftAsyncClient:
    calls: list[tuple[str, str, object]] = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        FakeDraftAsyncClient.calls = self.calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get(self, path, params=None, headers=None):
        self.calls.append(("GET", path, params))
        request = httpx.Request("GET", f"https://api.ebay.com{path}")
        if path == "/commerce/catalog/v1_beta/product_summary/search":
            return httpx.Response(
                200,
                json={
                    "productSummaries": [
                        _catalog_product("Apple iPhone 13 Pro Max 256GB Sierra Blue Unlocked")
                    ]
                },
                request=request,
            )
        if path == "/sell/inventory/v1/offer":
            return httpx.Response(200, json={"offers": []}, request=request)
        raise AssertionError(f"Unexpected GET path: {path}")

    async def put(self, path, json=None, headers=None):
        self.calls.append(("PUT", path, json))
        request = httpx.Request("PUT", f"https://api.ebay.com{path}")
        return httpx.Response(204, request=request)

    async def post(self, path, data=None, content=None, json=None, headers=None):
        payload = json if json is not None else content if content is not None else data
        self.calls.append(("POST", path, payload))
        request = httpx.Request("POST", f"https://api.ebay.com{path}")
        if path == "/sell/inventory/v1/offer":
            return httpx.Response(201, json={"offerId": "OFFER-1"}, request=request)
        raise AssertionError(f"Unexpected POST path: {path}")


def test_confirmed_batch_creates_unpublished_offer_with_catalog_images(monkeypatch):
    monkeypatch.setattr(ebay_module.httpx, "AsyncClient", FakeDraftAsyncClient)
    draft = next(
        item for item in inventory_sheet_missing_drafts() if item.sheet_row == 48
    )

    results = asyncio.run(
        EbayClient(_settings()).prepare_unpublished_drafts([draft], confirm=True)
    )

    assert results[0]["status"] == "created_unpublished"
    assert results[0]["offer_id"] == "OFFER-1"
    assert results[0]["published"] is False
    put_payload = next(
        payload
        for method, path, payload in FakeDraftAsyncClient.calls
        if method == "PUT" and "/inventory_item/" in path
    )
    assert put_payload["product"]["imageUrls"] == [
        "https://i.ebayimg.com/images/g/catalog/s-l1600.jpg",
        "https://i.ebayimg.com/images/g/catalog-two/s-l1600.jpg",
    ]
    assert not any("/publish" in path for _, path, _ in FakeDraftAsyncClient.calls)

