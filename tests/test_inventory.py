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


def test_inventory_persists_ebay_api_image_list_and_status(tmp_path):
    repository = InventoryRepository(tmp_path / "inventory.db")
    repository.upsert_items(
        [
            InventoryItem(
                sku="EBAY-123",
                title="Samsung Galaxy S25",
                quantity=1,
                ebay_item_id="123",
                ebay_url="https://www.ebay.com/itm/123",
                image_url="https://example.com/main.jpg",
                image_urls=["https://example.com/main.jpg", "https://example.com/side.jpg"],
                listing_status="ACTIVE",
            )
        ]
    )

    item = repository.get("EBAY-123")

    assert item is not None
    assert item.image_urls == ["https://example.com/main.jpg", "https://example.com/side.jpg"]
    assert item.listing_status == "ACTIVE"


def test_replace_ebay_inventory_snapshot_marks_missing_ebay_rows_inactive(tmp_path):
    repository = InventoryRepository(tmp_path / "inventory.db")
    repository.upsert_items(
        [
            InventoryItem(
                sku="EBAY-OLD",
                ebay_item_id="old",
                title="Old eBay listing",
                quantity=1,
                ebay_url="https://www.ebay.com/itm/old",
                image_url="https://example.com/old.jpg",
                source="ebay-store-page",
                listing_status="ACTIVE",
            ),
            InventoryItem(
                sku="HZ-DEMO-001",
                ebay_item_id="demo",
                title="Demo item",
                quantity=2,
                image_url="https://example.com/demo.jpg",
                source="csv",
            ),
        ]
    )

    repository.replace_ebay_inventory_snapshot(
        [
            InventoryItem(
                sku="EBAY-CURRENT",
                ebay_item_id="current",
                title="Current eBay listing",
                quantity=1,
                ebay_url="https://www.ebay.com/itm/current",
                image_url="https://example.com/current.jpg",
                source="ebay-browse-api",
                listing_status="IN_STOCK",
            )
        ]
    )

    old_item = repository.get("EBAY-OLD")
    current_item = repository.get("EBAY-CURRENT")
    demo_item = repository.get("HZ-DEMO-001")

    assert old_item is not None
    assert old_item.quantity == 0
    assert old_item.listing_status == "ENDED"
    assert current_item is not None
    assert current_item.quantity == 1
    assert current_item.listing_status == "IN_STOCK"
    assert demo_item is not None
    assert demo_item.quantity == 2


def test_replace_ebay_snapshot_retires_parent_row_when_listing_expands_to_variations(tmp_path):
    repository = InventoryRepository(tmp_path / "inventory.db")
    repository.upsert_items(
        [
            InventoryItem(
                sku="EBAY-123",
                ebay_item_id="123",
                title="Phone - all colors",
                quantity=3,
                image_url="https://example.com/parent.jpg",
                source="ebay-browse-api",
                listing_status="IN_STOCK",
            )
        ]
    )

    repository.replace_ebay_inventory_snapshot(
        [
            InventoryItem(
                sku="PHONE-BLUE",
                ebay_item_id="123",
                title="Phone - Blue",
                quantity=1,
                image_url="https://example.com/blue.jpg",
                source="ebay-trading-api",
                listing_status="ACTIVE",
            )
        ]
    )

    parent = repository.get("EBAY-123")
    variation = repository.get("PHONE-BLUE")
    assert parent is not None
    assert parent.quantity == 0
    assert parent.listing_status == "ENDED"
    assert variation is not None
    assert variation.quantity == 1


def test_item_for_social_reference_resolves_post_history_to_listing(tmp_path):
    repository = InventoryRepository(tmp_path / "inventory.db")
    repository.upsert_items(
        [
            InventoryItem(
                sku="EBAY-123",
                ebay_item_id="123",
                title="Samsung Galaxy S25",
                quantity=1,
                ebay_url="https://www.ebay.com/itm/123",
                image_url="https://i.ebayimg.com/images/g/demo/s-l1600.jpg",
                listing_status="ACTIVE",
                source="ebay-browse-api",
            )
        ]
    )
    repository.record_social_post(
        ebay_item_id="123",
        sku="EBAY-123",
        title="Samsung Galaxy S25",
        item_url="https://www.ebay.com/itm/123",
        image_url="https://i.ebayimg.com/images/g/demo/s-l1600.jpg",
        caption="Post caption",
        scheduled_at="2026-07-06 09:00:00",
        platform="facebook,instagram",
        metricool_post_id="fb-post-123",
    )

    item = repository.item_for_social_reference("fb-post-123")

    assert item is not None
    assert item.ebay_item_id == "123"
