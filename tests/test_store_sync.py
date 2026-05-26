from types import SimpleNamespace

import httpx

from app.inventory import InventoryRepository
from app.models import InventoryItem
from app.store_sync import StorePageSyncer


async def fake_fetch_store_page_items(store_url: str, max_pages: int = 1) -> list[InventoryItem]:
    return [
        InventoryItem(
            sku="EBAY-1",
            title="Store Page Phone",
            price=199.0,
            quantity=1,
            ebay_url="https://www.ebay.com/itm/1",
            source="ebay-store-page",
        )
    ]


def test_store_sync_imports_items(tmp_path, monkeypatch):
    import app.store_sync as store_sync_module

    monkeypatch.setattr(store_sync_module, "fetch_store_page_items", fake_fetch_store_page_items)
    repository = InventoryRepository(tmp_path / "inventory.db")
    settings = SimpleNamespace(ebay_store_url="https://www.ebay.com/str/exactspec", ebay_store_max_pages=3)
    syncer = StorePageSyncer(settings, repository)

    import asyncio

    status = asyncio.run(syncer.sync())

    assert status["status"] == "ok"
    assert status["imported"] == 1
    assert repository.search("phone")[0].sku == "EBAY-1"


async def fake_fetch_blocked_store_page(store_url: str, max_pages: int = 1) -> list[InventoryItem]:
    request = httpx.Request("GET", store_url)
    response = httpx.Response(503, request=request)
    raise httpx.HTTPStatusError("blocked", request=request, response=response)


def test_store_sync_refreshes_seed_fallback_when_ebay_blocks(tmp_path, monkeypatch):
    import app.store_sync as store_sync_module

    seed_csv = tmp_path / "seed.csv"
    seed_csv.write_text(
        "sku,title,description,condition,price,currency,quantity,ebay_item_id,ebay_url,image_url,category,item_specifics\n"
        "EBAY-2,Fallback Phone,,Open box,250.00,USD,1,2,https://www.ebay.com/itm/2,,Phones,{}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(store_sync_module, "fetch_store_page_items", fake_fetch_blocked_store_page)
    repository = InventoryRepository(tmp_path / "inventory.db")
    settings = SimpleNamespace(
        ebay_store_url="https://www.ebay.com/str/exactspec",
        ebay_store_max_pages=3,
        seed_inventory_csv=seed_csv,
    )
    syncer = StorePageSyncer(settings, repository)

    import asyncio

    status = asyncio.run(syncer.sync())

    assert status["status"] == "fallback"
    assert status["imported"] == 1
    assert status["inventory_count"] == 1
    assert repository.search("fallback")[0].sku == "EBAY-2"
