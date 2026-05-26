from app.inventory import InventoryRepository
from app.models import InventoryItem


def test_inventory_search_finds_item_specifics(tmp_path):
    repository = InventoryRepository(tmp_path / "inventory.db")
    repository.upsert_items(
        [
            InventoryItem(
                sku="HZ-1",
                title="Mechanical Keyboard",
                quantity=4,
                price=45.0,
                item_specifics={"Switch Type": "Blue"},
            )
        ]
    )

    results = repository.search("blue keyboard")

    assert len(results) == 1
    assert results[0].sku == "HZ-1"
