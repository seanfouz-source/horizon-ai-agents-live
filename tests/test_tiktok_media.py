from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.media import product_card_tiktok_jpeg_for_item
from app.models import InventoryItem


def _demo_item() -> InventoryItem:
    return InventoryItem(
        sku="EBAY-123",
        title="Demo Phone",
        price=199.0,
        condition="Open box",
        quantity=1,
        ebay_item_id="123",
    )


def test_product_card_tiktok_jpeg_for_item_returns_portrait_jpeg():
    jpeg = product_card_tiktok_jpeg_for_item(_demo_item())

    assert jpeg.startswith(b"\xff\xd8\xff")
    with Image.open(BytesIO(jpeg)) as image:
        assert image.size == (1080, 1920)
        assert image.mode == "RGB"


def test_product_tiktok_media_endpoint_serves_portrait_jpeg(monkeypatch):
    import app.main as main_module

    class FakeRepository:
        def get(self, sku):
            return _demo_item() if sku == "EBAY-123" else None

    monkeypatch.setattr(main_module, "repository", FakeRepository())
    client = TestClient(main_module.app)

    response = client.get("/media/products/EBAY-123.tiktok.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    with Image.open(BytesIO(response.content)) as image:
        assert image.size == (1080, 1920)


def test_product_tiktok_media_head_endpoint_includes_media_headers(monkeypatch):
    import app.main as main_module

    class FakeRepository:
        def get(self, sku):
            return _demo_item() if sku == "EBAY-123" else None

    monkeypatch.setattr(main_module, "repository", FakeRepository())
    client = TestClient(main_module.app)

    response = client.head("/media/products/EBAY-123.tiktok.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert int(response.headers["content-length"]) > 1000
    assert response.content == b""
