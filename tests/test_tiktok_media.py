from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

import app.media as media_module
from app.media import tiktok_ebay_photo_jpeg_for_item
from app.models import InventoryItem


def _source_jpeg(width: int = 1600, height: int = 1200) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), (240, 240, 240)).save(output, format="JPEG")
    return output.getvalue()


def _demo_item() -> InventoryItem:
    return InventoryItem(
        sku="EBAY-123",
        title="Demo Phone",
        price=199.0,
        condition="Open box",
        quantity=1,
        ebay_item_id="123",
        image_url="https://i.ebayimg.com/images/g/demo/s-l300.jpg",
        image_urls=[
            "https://i.ebayimg.com/images/g/demo/s-l300.jpg",
            "https://i.ebayimg.com/images/g/demo/s-l1600.jpg",
        ],
    )


def test_tiktok_ebay_photo_jpeg_for_item_returns_portrait_jpeg(monkeypatch):
    downloaded_urls = []

    def fake_download(url):
        downloaded_urls.append(url)
        return _source_jpeg()

    monkeypatch.setattr(media_module, "_download_image_bytes", fake_download)

    jpeg = tiktok_ebay_photo_jpeg_for_item(_demo_item())

    assert jpeg.startswith(b"\xff\xd8\xff")
    assert downloaded_urls == ["https://i.ebayimg.com/images/g/demo/s-l1600.jpg"]
    with Image.open(BytesIO(jpeg)) as image:
        assert image.size == (1080, 1920)
        assert image.mode == "RGB"


def test_product_tiktok_media_endpoint_serves_portrait_jpeg(monkeypatch):
    import app.main as main_module

    class FakeRepository:
        def get(self, sku):
            return _demo_item() if sku == "EBAY-123" else None

    monkeypatch.setattr(main_module, "repository", FakeRepository())
    monkeypatch.setattr(media_module, "_download_image_bytes", lambda url: _source_jpeg())
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
    monkeypatch.setattr(media_module, "_download_image_bytes", lambda url: _source_jpeg())
    client = TestClient(main_module.app)

    response = client.head("/media/products/EBAY-123.tiktok.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert int(response.headers["content-length"]) > 1000
    assert response.content == b""
