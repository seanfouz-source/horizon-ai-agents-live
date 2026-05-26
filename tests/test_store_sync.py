from types import SimpleNamespace

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
