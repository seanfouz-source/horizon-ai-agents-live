import re
import struct
import zlib
from io import BytesIO
from functools import lru_cache

from app.models import InventoryItem


CARD_WIDTH = 1080
CARD_HEIGHT = 1080
TIKTOK_CARD_WIDTH = 1080
TIKTOK_CARD_HEIGHT = 1920
BACKGROUND = (248, 250, 252)
INK = (18, 24, 38)
MUTED = (86, 96, 112)
ACCENT = (0, 112, 186)
ACCENT_DARK = (12, 74, 110)
PANEL = (255, 255, 255)
LINE = (210, 218, 228)


FONT: dict[str, tuple[str, ...]] = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "$": ("01110", "10100", "10100", "01110", "00101", "00101", "11110"),
    "#": ("01010", "11111", "01010", "11111", "01010", "00000", "00000"),
    "&": ("01100", "10010", "10100", "01000", "10101", "10010", "01101"),
    "+": ("00000", "00100", "00100", "11111", "00100", "00100", "00000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10011", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00001", "00001", "00001", "00001", "10001", "10001", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}


@lru_cache(maxsize=512)
def product_card_png(
    sku: str,
    title: str,
    price: float | None,
    condition: str | None,
    ebay_item_id: str | None,
) -> bytes:
    try:
        return _pillow_product_card_png(sku, title, price, condition, ebay_item_id)
    except Exception:
        return _pixel_product_card_png(sku, title, price, condition, ebay_item_id)


@lru_cache(maxsize=512)
def product_card_jpeg(
    sku: str,
    title: str,
    price: float | None,
    condition: str | None,
    ebay_item_id: str | None,
) -> bytes:
    image = _pillow_product_card_image(sku, title, price, condition, ebay_item_id)
    output = BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True, progressive=True)
    return output.getvalue()


def tiktok_ebay_photo_jpeg(source_url: str) -> bytes:
    image = _pillow_tiktok_ebay_photo_image(_download_image_bytes(source_url))
    output = BytesIO()
    image.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def _pillow_product_card_png(
    sku: str,
    title: str,
    price: float | None,
    condition: str | None,
    ebay_item_id: str | None,
) -> bytes:
    image = _pillow_product_card_image(sku, title, price, condition, ebay_item_id)
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _pillow_product_card_image(
    sku: str,
    title: str,
    price: float | None,
    condition: str | None,
    ebay_item_id: str | None,
):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CARD_WIDTH, 244), fill=ACCENT)
    draw.rectangle((0, 222, CARD_WIDTH, 244), fill=ACCENT_DARK)

    brand_font = _load_font(ImageFont, 88, bold=True)
    kicker_font = _load_font(ImageFont, 32, bold=True)
    title_font = _load_font(ImageFont, 58, bold=True)
    price_font = _load_font(ImageFont, 82, bold=True)
    body_font = _load_font(ImageFont, 34)
    cta_font = _load_font(ImageFont, 42, bold=True)

    draw.text((72, 62), "ExactSpec", font=brand_font, fill=(255, 255, 255))
    draw.text((78, 158), "EBAY LISTING", font=kicker_font, fill=(219, 234, 254))

    draw.rounded_rectangle((72, 304, CARD_WIDTH - 72, 810), radius=18, fill=PANEL, outline=LINE, width=3)
    y = 360
    for line in _wrap_for_pillow(_clean_text(title), title_font, 800, draw, 4):
        draw.text((120, y), line, font=title_font, fill=INK)
        y += 68

    price_text = "PRICE ON EBAY" if price is None else f"${price:,.2f}"
    draw.text((120, 676), price_text, font=price_font, fill=ACCENT_DARK)

    details = [value for value in [condition, sku] if value]
    y = 818
    for detail in details[:3]:
        draw.text((120, y), _clean_text(str(detail)), font=body_font, fill=MUTED)
        y += 44

    draw.rounded_rectangle((72, 936, CARD_WIDTH - 72, 1012), radius=12, fill=INK)
    draw.text((120, 957), "Shop this listing on eBay", font=cta_font, fill=(255, 255, 255))

    return image


def _pillow_tiktok_ebay_photo_image(image_bytes: bytes):
    from PIL import Image, ImageOps

    with Image.open(BytesIO(image_bytes)) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        source.thumbnail((TIKTOK_CARD_WIDTH, TIKTOK_CARD_HEIGHT), Image.Resampling.LANCZOS)
        image = Image.new("RGB", (TIKTOK_CARD_WIDTH, TIKTOK_CARD_HEIGHT), (255, 255, 255))
        x = (TIKTOK_CARD_WIDTH - source.width) // 2
        y = (TIKTOK_CARD_HEIGHT - source.height) // 2
        image.paste(source, (x, y))
        return image


def _pixel_product_card_png(
    sku: str,
    title: str,
    price: float | None,
    condition: str | None,
    ebay_item_id: str | None,
) -> bytes:
    image = _canvas(CARD_WIDTH, CARD_HEIGHT, BACKGROUND)
    _rect(image, 0, 0, CARD_WIDTH, 210, ACCENT)
    _rect(image, 0, 210, CARD_WIDTH, 230, ACCENT_DARK)
    _text(image, 72, 68, "EXACTSPEC", 11, (255, 255, 255))
    _text(image, 72, 152, "EBAY LISTING", 5, (219, 234, 254))

    _rect(image, 72, 292, CARD_WIDTH - 72, 810, PANEL)
    _outline(image, 72, 292, CARD_WIDTH - 72, 810, LINE)

    title_lines = _wrap(_clean_text(title), 22, 4)
    y = 344
    for line in title_lines:
        _text(image, 118, y, line, 7, INK)
        y += 72

    price_text = "PRICE ON EBAY" if price is None else f"${price:,.2f}"
    _text(image, 118, 690, price_text, 10, ACCENT_DARK)

    details = [value for value in [condition, sku] if value]
    y = 812
    for detail in details[:3]:
        _text(image, 122, y, _clean_text(str(detail)), 4, MUTED)
        y += 48

    _rect(image, 72, 932, CARD_WIDTH - 72, 1008, INK)
    _text(image, 118, 955, "SHOP THIS LISTING ON EBAY", 5, (255, 255, 255))
    return _png_bytes(image)


def product_card_for_item(item: InventoryItem) -> bytes:
    return product_card_png(item.sku, item.title, item.price, item.condition, item.ebay_item_id)


def product_card_jpeg_for_item(item: InventoryItem) -> bytes:
    return product_card_jpeg(item.sku, item.title, item.price, item.condition, item.ebay_item_id)


def tiktok_ebay_photo_jpeg_for_item(item: InventoryItem) -> bytes:
    source_url = _preferred_ebay_image_url(item)
    if not source_url:
        raise ValueError("Inventory item does not have an eBay image URL.")
    return tiktok_ebay_photo_jpeg(source_url)


def _preferred_ebay_image_url(item: InventoryItem) -> str | None:
    urls = []
    if item.image_url:
        urls.append(item.image_url)
    urls.extend(item.image_urls)
    usable_urls = [url for url in _dedupe_urls(urls) if _usable_remote_image_url(url)]
    if not usable_urls:
        return None
    return max(
        enumerate(usable_urls),
        key=lambda pair: (_image_url_pixel_hint(pair[1]), -pair[0]),
    )[1]


def _download_image_bytes(url: str) -> bytes:
    import httpx

    response = httpx.get(url, follow_redirects=True, timeout=20)
    response.raise_for_status()
    if not response.content:
        raise ValueError("Downloaded eBay image was empty.")
    return response.content


def _usable_remote_image_url(url: str) -> bool:
    lowered = str(url).strip().lower().split("?")[0]
    return lowered.startswith("https://") and any(
        marker in lowered
        for marker in (".jpg", ".jpeg", ".png", ".webp", "/images/", "i.ebayimg.com")
    )


def _image_url_pixel_hint(url: str) -> int:
    match = re.search(r"/s-l(\d+)(?:[./?]|$)", url.lower())
    if not match:
        return 0
    return int(match.group(1))


def _dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        clean_url = str(url).strip()
        if not clean_url or clean_url in seen:
            continue
        seen.add(clean_url)
        deduped.append(clean_url)
    return deduped


def _load_font(image_font, size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return image_font.truetype(path, size=size)
        except OSError:
            continue
    return image_font.load_default()


def _wrap_for_pillow(text: str, font, max_width: int, draw, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        while lines[-1] and _text_width(draw, f"{lines[-1]}...", font) > max_width:
            lines[-1] = lines[-1][:-1].rstrip()
        lines[-1] = f"{lines[-1]}..."
    return lines or ["ExactSpec listing"]


def _text_width(draw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _canvas(width: int, height: int, color: tuple[int, int, int]) -> list[bytearray]:
    row = bytearray(color * width)
    return [bytearray(row) for _ in range(height)]


def _rect(image: list[bytearray], x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int]) -> None:
    width = len(image[0]) // 3
    x1 = max(0, min(width, x1))
    x2 = max(0, min(width, x2))
    y1 = max(0, min(len(image), y1))
    y2 = max(0, min(len(image), y2))
    fill = bytes(color * max(0, x2 - x1))
    for y in range(y1, y2):
        image[y][x1 * 3 : x2 * 3] = fill


def _outline(image: list[bytearray], x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int]) -> None:
    _rect(image, x1, y1, x2, y1 + 3, color)
    _rect(image, x1, y2 - 3, x2, y2, color)
    _rect(image, x1, y1, x1 + 3, y2, color)
    _rect(image, x2 - 3, y1, x2, y2, color)


def _text(image: list[bytearray], x: int, y: int, text: str, scale: int, color: tuple[int, int, int]) -> None:
    cursor = x
    for character in text.upper():
        glyph = FONT.get(character, FONT[" "])
        for row_index, row in enumerate(glyph):
            for column_index, value in enumerate(row):
                if value == "1":
                    _rect(
                        image,
                        cursor + column_index * scale,
                        y + row_index * scale,
                        cursor + (column_index + 1) * scale,
                        y + (row_index + 1) * scale,
                        color,
                    )
        cursor += 6 * scale


def _wrap(text: str, width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:width]
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        lines[-1] = lines[-1][: max(0, width - 3)].rstrip() + "..."
    return lines or ["EXACTSPEC LISTING"]


def _clean_text(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9 #&+/$.-]+", " ", value)
    return re.sub(r"\s+", " ", text).strip()


def _png_bytes(image: list[bytearray]) -> bytes:
    height = len(image)
    width = len(image[0]) // 3
    raw = b"".join(b"\x00" + bytes(row) for row in image)
    compressed = zlib.compress(raw, level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        +
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
