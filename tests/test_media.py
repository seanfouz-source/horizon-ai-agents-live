from app.media import product_card_for_item, product_card_jpeg_for_item
from app.models import InventoryItem


def test_product_card_for_item_returns_png_bytes():
    png = product_card_for_item(
        InventoryItem(
            sku="EBAY-123",
            title="Demo Phone",
            price=199.0,
            condition="Open box",
            quantity=1,
            ebay_item_id="123",
        )
    )

    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 1000


def test_product_card_jpeg_for_item_returns_jpeg_bytes():
    jpeg = product_card_jpeg_for_item(
        InventoryItem(
            sku="EBAY-123",
            title="Demo Phone",
            price=199.0,
            condition="Open box",
            quantity=1,
            ebay_item_id="123",
        )
    )

    assert jpeg.startswith(b"\xff\xd8\xff")
    assert len(jpeg) > 1000
