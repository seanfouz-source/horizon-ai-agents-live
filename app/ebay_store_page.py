import asyncio
import json
import re
import subprocess
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx

from app.models import InventoryItem


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
CURL_RESULT_MARKER = "__HORIZON_CURL_RESULT__"

ITEM_URL_RE = re.compile(r"https?://(?:www\.)?ebay\.com/itm/[^\"'<>\\\s]+")
ITEM_ID_RE = re.compile(r"/itm/(?:[^/?#]+/)?(\d+)")
LD_JSON_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def parse_store_page(html: str, page_url: str) -> list[InventoryItem]:
    """Extract public listing details from an eBay store/search HTML page."""
    items_by_url: dict[str, InventoryItem] = {}

    for item in _parse_json_ld(html):
        items_by_url[item.ebay_url or item.sku] = item

    for item in _parse_storefront_cards(html):
        items_by_url[item.ebay_url or item.sku] = item

    for item in _parse_listing_cards(html):
        key = item.ebay_url or item.sku
        existing = items_by_url.get(key)
        if existing:
            if not existing.price:
                existing.price = item.price
            if not existing.image_url:
                existing.image_url = item.image_url
            if existing.title == existing.sku and item.title:
                existing.title = item.title
        else:
            items_by_url[key] = item

    return list(items_by_url.values())


async def fetch_store_page_items(store_url: str, max_pages: int = 1) -> list[InventoryItem]:
    max_pages = max(1, min(max_pages, 10))
    items: dict[str, InventoryItem] = {}

    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    ) as client:
        for page in range(1, max_pages + 1):
            page_url = _page_url(store_url, page)
            html, effective_url = await _fetch_page_html(client, page_url)
            for item in parse_store_page(html, effective_url):
                items[item.ebay_url or item.sku] = item

    return list(items.values())


async def _fetch_page_html(client: httpx.AsyncClient, page_url: str) -> tuple[str, str]:
    response = await client.get(page_url)
    if response.status_code in {403, 429, 503}:
        return await asyncio.to_thread(_fetch_page_html_with_curl, page_url)
    response.raise_for_status()
    return response.text, str(response.url)


def _fetch_page_html_with_curl(page_url: str) -> tuple[str, str]:
    command = [
        "curl",
        "-sS",
        "-L",
        "--max-time",
        "30",
        "-A",
        USER_AGENT,
        "-H",
        "Accept-Language: en-US,en;q=0.9",
        "-H",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "--write-out",
        f"\n{CURL_RESULT_MARKER}%{{http_code}} %{{url_effective}}",
        page_url,
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=35)
    if completed.returncode != 0:
        request = httpx.Request("GET", page_url)
        response = httpx.Response(503, request=request, text=completed.stderr)
        raise httpx.HTTPStatusError("Could not reach eBay store page with curl fallback.", request=request, response=response)

    body, marker, result = completed.stdout.rpartition(CURL_RESULT_MARKER)
    if not marker:
        request = httpx.Request("GET", page_url)
        response = httpx.Response(503, request=request, text=completed.stderr)
        raise httpx.HTTPStatusError("Could not parse eBay curl fallback response.", request=request, response=response)

    status_text, _, effective_url = result.strip().partition(" ")
    status_code = int(status_text) if status_text.isdigit() else 503
    request = httpx.Request("GET", page_url)
    if status_code >= 400:
        response = httpx.Response(status_code, request=request, text=body)
        raise httpx.HTTPStatusError(f"eBay returned HTTP {status_code}", request=request, response=response)
    return body, effective_url or page_url


def _parse_json_ld(html: str) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    for match in LD_JSON_RE.finditer(html):
        raw_json = unescape(match.group(1).strip())
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        for product in _walk_json_products(payload):
            item = _item_from_json_product(product)
            if item:
                items.append(item)
    return items


def _parse_storefront_cards(html: str) -> list[InventoryItem]:
    """Extract listings from eBay's server-rendered storefront state."""
    items: list[InventoryItem] = []
    for module in _json_objects_after_key(html, "LISTINGS_MODULE"):
        for container in module.get("containers", []):
            for card in container.get("cards", []):
                item = _item_from_storefront_card(card)
                if item:
                    items.append(item)
    return items


def _item_from_storefront_card(card: dict[str, Any]) -> InventoryItem | None:
    if not isinstance(card, dict):
        return None

    action = card.get("action") if isinstance(card.get("action"), dict) else {}
    image = card.get("image") if isinstance(card.get("image"), dict) else {}
    price_value = card.get("displayPrice") if isinstance(card.get("displayPrice"), dict) else {}
    raw_url = _first_string(action.get("URL"))
    item_id = _first_string(card.get("listingId")) or _item_id(raw_url)
    url = _clean_url(raw_url) if raw_url else None
    if not url and item_id:
        url = f"https://www.ebay.com/itm/{item_id}"
    if not url or "ebay.com/itm/" not in url:
        return None

    title = _textual_display_text(card.get("title")) or _first_string(image.get("title"))
    price = _display_value_price(price_value) or _parse_price(_textual_display_text(price_value))
    currency = _display_value_currency(price_value) or "USD"

    return InventoryItem(
        sku=f"EBAY-{item_id}" if item_id else url,
        title=title or f"eBay listing {item_id or url}",
        price=price,
        currency=currency,
        quantity=1,
        ebay_item_id=item_id,
        ebay_url=url,
        image_url=_first_string(image.get("URL")),
        source="ebay-store-page",
        item_specifics={"Inventory source": "Public eBay store page"},
    )


def _json_objects_after_key(html: str, key: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    marker = json.dumps(key)
    position = 0
    while True:
        key_position = html.find(marker, position)
        if key_position == -1:
            break
        colon_position = html.find(":", key_position + len(marker))
        start_position = html.find("{", colon_position)
        if colon_position == -1 or start_position == -1:
            break
        end_position = _balanced_json_object_end(html, start_position)
        if end_position is None:
            position = start_position + 1
            continue
        try:
            payload = json.loads(html[start_position:end_position])
        except json.JSONDecodeError:
            position = end_position
            continue
        if isinstance(payload, dict):
            objects.append(payload)
        position = end_position
    return objects


def _balanced_json_object_end(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _walk_json_products(payload: Any) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        if payload.get("@type") in {"Product", "Offer"} or payload.get("url"):
            products.append(payload)
        for value in payload.values():
            products.extend(_walk_json_products(value))
    elif isinstance(payload, list):
        for value in payload:
            products.extend(_walk_json_products(value))
    return products


def _item_from_json_product(product: dict[str, Any]) -> InventoryItem | None:
    url = _clean_url(_first_string(product.get("url") or product.get("item")))
    name = _first_string(product.get("name") or product.get("title"))
    offers = product.get("offers") if isinstance(product.get("offers"), dict) else {}
    price = _parse_price(_first_string(product.get("price") or offers.get("price")))
    currency = _first_string(product.get("priceCurrency") or offers.get("priceCurrency")) or "USD"
    image = _first_string(product.get("image"))

    if not url or "ebay.com/itm/" not in url:
        return None

    item_id = _item_id(url)
    return InventoryItem(
        sku=f"EBAY-{item_id}" if item_id else url,
        title=name or f"eBay listing {item_id or url}",
        price=price,
        currency=currency,
        quantity=1,
        ebay_item_id=item_id,
        ebay_url=url,
        image_url=image,
        source="ebay-store-page",
        item_specifics={"Inventory source": "Public eBay store page"},
    )


def _parse_listing_cards(html: str) -> list[InventoryItem]:
    items: list[InventoryItem] = []
    seen_urls: set[str] = set()
    for match in ITEM_URL_RE.finditer(html):
        url = _clean_url(unescape(match.group(0)))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        window = html[max(0, match.start() - 2500) : min(len(html), match.end() + 2500)]
        title = _extract_title(window) or f"eBay listing {_item_id(url) or len(seen_urls)}"
        image = _extract_image(window)
        price = _extract_price(window)
        item_id = _item_id(url)
        items.append(
            InventoryItem(
                sku=f"EBAY-{item_id}" if item_id else f"EBAY-PUBLIC-{len(seen_urls)}",
                title=title,
                price=price,
                currency="USD",
                quantity=1,
                ebay_item_id=item_id,
                ebay_url=url,
                image_url=image,
                source="ebay-store-page",
                item_specifics={"Inventory source": "Public eBay store page"},
            )
        )
    return items


def _extract_title(fragment: str) -> str | None:
    patterns = [
        r"class=[\"'][^\"']*s-item__title[^\"']*[\"'][^>]*>(.*?)</",
        r"aria-label=[\"']([^\"']+)[\"']",
        r"alt=[\"']([^\"']+)[\"']",
    ]
    for pattern in patterns:
        match = re.search(pattern, fragment, re.IGNORECASE | re.DOTALL)
        if match:
            title = _strip_tags(match.group(1))
            if title and title.lower() not in {"shop on ebay", "opens in a new window or tab"}:
                return title
    return None


def _extract_image(fragment: str) -> str | None:
    match = re.search(r"<img[^>]+(?:src|data-src)=[\"'](https?://[^\"']+)[\"']", fragment, re.IGNORECASE)
    return unescape(match.group(1)) if match else None


def _extract_price(fragment: str) -> float | None:
    match = re.search(r"\$\s?[\d,]+(?:\.\d{2})?", fragment)
    return _parse_price(match.group(0)) if match else None


def _parse_price(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", value)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def _display_value_price(value: dict[str, Any]) -> float | None:
    raw_value = value.get("value")
    if isinstance(raw_value, dict):
        raw_value = raw_value.get("value")
    if isinstance(raw_value, int | float):
        return float(raw_value)
    return _parse_price(_first_string(raw_value))


def _display_value_currency(value: dict[str, Any]) -> str | None:
    raw_value = value.get("value")
    if isinstance(raw_value, dict):
        return _first_string(raw_value.get("currency"))
    return None


def _textual_display_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    spans = value.get("textSpans")
    if isinstance(spans, list):
        text = " ".join(_first_string(span.get("text")) or "" for span in spans if isinstance(span, dict))
        return re.sub(r"\s+", " ", text).strip() or None
    return None


def _first_string(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        for item in value:
            result = _first_string(item)
            if result:
                return result
    if isinstance(value, dict):
        for key in ("url", "contentUrl", "thumbnailUrl"):
            result = _first_string(value.get(key))
            if result:
                return result
    return None


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", unescape(text))
    return text.strip()


def _clean_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    clean_query = {
        key: value
        for key, value in parse_qs(parsed.query).items()
        if key in {"var", "hash"}
    }
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(clean_query, doseq=True), ""))


def _item_id(url: str | None) -> str | None:
    if not url:
        return None
    match = ITEM_ID_RE.search(url)
    return match.group(1) if match else None


def _page_url(store_url: str, page: int) -> str:
    absolute = urljoin(store_url, store_url)
    parsed = urlparse(absolute)
    query = parse_qs(parsed.query)
    if page > 1:
        query["_pgn"] = [str(page)]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(query, doseq=True), ""))
