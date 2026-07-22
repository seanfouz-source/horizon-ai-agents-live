import asyncio
import json
import re
import uuid
from base64 import b64encode
from datetime import date
from typing import Any, Iterable
from urllib.parse import quote

import httpx

from app.config import Settings
from app.models import InventoryItem, WalmartItemOverride


RETRY_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)
PRODUCT_ID_TYPES = ("GTIN", "UPC", "EAN", "ISBN")
CONDITION_IMAGE_REQUIRED = {
    "Remanufactured",
    "Pre-Owned: Like New",
    "Pre-Owned: Good",
    "Pre-Owned: Fair",
    "New with defects",
}
SUPPORTED_CONDITIONS = {
    "Pre-Owned: Fair",
    "Remanufactured",
    "New with defects",
    "Open Box",
    "Pre-Owned: Good",
    "New without box",
    "New",
    "New without tags",
    "Pre-Owned: Like New",
}


class WalmartApiError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class WalmartMarketplaceClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = str(settings.walmart_api_base_url).rstrip("/")
        self._access_token: str | None = None
        self._token_expires_in: int | None = None

    @property
    def configured(self) -> bool:
        return bool(
            str(getattr(self.settings, "walmart_client_id", "") or "").strip()
            and str(getattr(self.settings, "walmart_client_secret", "") or "").strip()
        )

    async def verify_credentials(self) -> dict[str, Any]:
        token = await self._get_access_token(force=True)
        return {
            "status": "ok",
            "configured": True,
            "access_token_received": bool(token),
            "expires_in": self._token_expires_in,
            "environment": "sandbox" if "sandbox" in self.base_url.lower() else "production",
        }

    async def search_catalog(
        self,
        product_id_type: str,
        product_id: str,
        *,
        response_format: str = "SPEC",
    ) -> dict[str, Any]:
        identifier_type = str(product_id_type).strip().upper()
        if identifier_type not in {"UPC", "GTIN"}:
            return {
                "status": "not_checked",
                "matched": None,
                "reason": f"Walmart catalog search does not support {identifier_type} identifiers.",
            }

        response = await self._request(
            "GET",
            "/v3/items/walmart/search",
            params={identifier_type.lower(): product_id, "responseFormat": response_format},
        )
        payload = self._json_object(response)
        items = payload.get("items")
        results = items if isinstance(items, list) else []
        first = results[0] if results and isinstance(results[0], dict) else None
        feed_type = str(first.get("feedType") or "") if first else ""
        return {
            "status": "matched" if feed_type == "MP_ITEM_MATCH" else "not_matched",
            "matched": feed_type == "MP_ITEM_MATCH",
            "feed_type": feed_type or None,
            "version": first.get("version") if first else None,
            "product_type": first.get("productType") if first else None,
        }

    async def submit_offer_match_feed(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._request(
            "POST",
            "/v3/feeds",
            params={"feedType": "MP_ITEM_MATCH"},
            json=payload,
        )
        result = self._json_object(response)
        feed_id = result.get("feedId")
        if not isinstance(feed_id, str) or not feed_id:
            raise WalmartApiError("Walmart accepted the request but did not return a feedId.")
        return {
            "status": "submitted",
            "feed_type": "MP_ITEM_MATCH",
            "feed_id": feed_id,
            "correlation_id": response.request.headers.get("WM_QOS.CORRELATION_ID"),
        }

    async def submit_inventory_feed(self, payload: dict[str, Any]) -> dict[str, Any]:
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        response = await self._request(
            "POST",
            "/v3/feeds",
            params={"feedType": "inventory"},
            files={"file": ("walmart-inventory.json", content, "application/json")},
        )
        result = self._json_object(response)
        feed_id = result.get("feedId")
        if not isinstance(feed_id, str) or not feed_id:
            raise WalmartApiError("Walmart accepted the inventory request but did not return a feedId.")
        return {
            "status": "submitted",
            "feed_type": "inventory",
            "feed_id": feed_id,
            "correlation_id": response.request.headers.get("WM_QOS.CORRELATION_ID"),
        }

    async def get_feed_status(
        self,
        feed_id: str,
        *,
        include_details: bool = True,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        clean_feed_id = str(feed_id or "").strip()
        if not clean_feed_id:
            raise WalmartApiError("A Walmart feedId is required.")
        response = await self._request(
            "GET",
            f"/v3/feeds/{quote(clean_feed_id, safe='')}",
            params={
                "includeDetails": str(bool(include_details)).lower(),
                "offset": max(0, offset),
                "limit": max(1, min(limit, 50)),
            },
        )
        return self._json_object(response)

    async def _get_access_token(self, *, force: bool = False) -> str:
        if self._access_token and not force:
            return self._access_token
        if not self.configured:
            raise WalmartApiError(
                "WALMART_CLIENT_ID and WALMART_CLIENT_SECRET are required for Walmart Marketplace API calls."
            )

        client_id = str(self.settings.walmart_client_id or "").strip()
        client_secret = str(self.settings.walmart_client_secret or "").strip()
        credentials = b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        correlation_id = str(uuid.uuid4())
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            response = await client.post(
                "/v3/token",
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "WM_QOS.CORRELATION_ID": correlation_id,
                    "WM_SVC.NAME": self.settings.walmart_service_name,
                },
            )
        self._raise_for_status(response, "Walmart OAuth token request")
        payload = self._json_object(response)
        token_payload = payload
        nested = payload.get("clientCredentialsRes")
        if isinstance(nested, dict) and isinstance(nested.get("value"), dict):
            token_payload = nested["value"]
        token = token_payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise WalmartApiError("Walmart OAuth response did not include an access token.")
        self._access_token = token.strip()
        try:
            self._token_expires_in = int(token_payload.get("expires_in") or 900)
        except (TypeError, ValueError):
            self._token_expires_in = 900
        return self._access_token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._get_access_token()
        correlation_id = str(uuid.uuid4())
        headers = {
            "Accept": "application/json",
            "WM_SEC.ACCESS_TOKEN": token,
            "WM_QOS.CORRELATION_ID": correlation_id,
            "WM_SVC.NAME": self.settings.walmart_service_name,
            "WM_MARKET": self.settings.walmart_market,
        }
        channel_type = str(getattr(self.settings, "walmart_channel_type", "") or "").strip()
        if channel_type:
            headers["WM_CONSUMER.CHANNEL.TYPE"] = channel_type
        headers.update(kwargs.pop("headers", {}))

        response: httpx.Response | None = None
        async with httpx.AsyncClient(base_url=self.base_url, timeout=60) as client:
            for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
                response = await client.request(method, path, headers=headers, **kwargs)
                if response.status_code == 401 and attempt == 0:
                    headers["WM_SEC.ACCESS_TOKEN"] = await self._get_access_token(force=True)
                    continue
                if response.status_code not in RETRY_STATUS_CODES or attempt >= len(RETRY_DELAYS_SECONDS):
                    break
                await asyncio.sleep(RETRY_DELAYS_SECONDS[attempt])

        if response is None:
            raise WalmartApiError(f"Walmart {method} {path} did not return a response.")
        self._raise_for_status(response, f"Walmart {method} {path}")
        return response

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise WalmartApiError("Walmart returned a non-JSON response.", status_code=response.status_code) from exc
        if not isinstance(payload, dict):
            raise WalmartApiError("Walmart returned an unexpected response shape.", status_code=response.status_code)
        return payload

    @staticmethod
    def _raise_for_status(response: httpx.Response, operation: str) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WalmartApiError(
                f"{operation} failed with HTTP {response.status_code}.",
                status_code=response.status_code,
            ) from exc


def build_offer_match_preview(
    items: Iterable[InventoryItem],
    overrides: dict[str, WalmartItemOverride] | None = None,
    *,
    default_shipping_weight_lbs: float | None = None,
) -> dict[str, Any]:
    item_overrides = overrides or {}
    ready_entries: list[dict[str, Any]] = []
    item_results: list[dict[str, Any]] = []

    for item in items:
        override = item_overrides.get(item.sku, WalmartItemOverride())
        entry, errors, warnings, resolved = _build_offer_match_item(
            item,
            override,
            default_shipping_weight_lbs=default_shipping_weight_lbs,
        )
        ready = not errors
        if entry is not None and ready:
            ready_entries.append({"Item": entry})
        item_results.append(
            {
                "sku": item.sku,
                "ebay_item_id": item.ebay_item_id,
                "title": item.title,
                "ebay_url": item.ebay_url,
                "ready": ready,
                "errors": errors,
                "warnings": warnings,
                "resolved": resolved,
            }
        )

    payload = {
        "MPItemFeedHeader": {
            "processMode": "REPLACE",
            "subset": "EXTERNAL",
            "locale": "en",
            "sellingChannel": "mpsetupbymatch",
            "version": "4.2",
        },
        "MPItem": ready_entries,
    }
    return {
        "feed_type": "MP_ITEM_MATCH",
        "total": len(item_results),
        "ready": len(ready_entries),
        "blocked": len(item_results) - len(ready_entries),
        "items": item_results,
        "payload": payload,
    }


def build_inventory_feed(items: Iterable[InventoryItem]) -> dict[str, Any]:
    today = date.today().isoformat()
    inventory = [
        {
            "sku": item.sku,
            "quantity": {"unit": "EACH", "amount": max(0, int(item.quantity))},
            "inventoryAvailableDate": today,
        }
        for item in items
    ]
    return {"InventoryHeader": {"version": "1.4"}, "Inventory": inventory}


def _build_offer_match_item(
    item: InventoryItem,
    override: WalmartItemOverride,
    *,
    default_shipping_weight_lbs: float | None,
) -> tuple[dict[str, Any] | None, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    product_id_type, product_id = _product_identifier(item, override)
    shipping_weight_lbs = (
        override.shipping_weight_lbs
        if override.shipping_weight_lbs is not None
        else _shipping_weight_lbs(item.item_specifics)
    )
    if shipping_weight_lbs is None:
        shipping_weight_lbs = default_shipping_weight_lbs
        if shipping_weight_lbs is not None:
            warnings.append("Used WALMART_DEFAULT_SHIPPING_WEIGHT_LBS; verify the packaged weight before submission.")
    condition = _walmart_condition(override.condition or item.condition)
    price = override.price if override.price is not None else item.price
    quantity = override.quantity if override.quantity is not None else item.quantity
    main_image_url = override.main_image_url or item.image_url

    if not item.sku or len(item.sku) > 50:
        errors.append("Walmart requires a seller SKU between 1 and 50 characters.")
    if not product_id_type or not product_id:
        errors.append("Missing a UPC, GTIN, EAN, or ISBN product identifier.")
    elif not _valid_product_identifier(product_id_type, product_id):
        errors.append(f"{product_id_type} value has an invalid format or length.")
    if shipping_weight_lbs is None or shipping_weight_lbs <= 0:
        errors.append("Missing Shipping Weight in pounds.")
    if not condition:
        errors.append("eBay condition could not be mapped to a supported Walmart condition.")
    elif condition not in SUPPORTED_CONDITIONS:
        errors.append(f"Walmart condition {condition!r} is not supported by MP_ITEM_MATCH v4.2.")
    if price is None or price <= 0:
        errors.append("Missing a positive Walmart selling price.")
    if quantity is None or quantity <= 0:
        errors.append("The eBay listing is not currently in stock.")
    if main_image_url and len(main_image_url) > 200:
        message = "Main image URL exceeds the MP_ITEM_MATCH v4.2 limit of 200 characters."
        if condition in CONDITION_IMAGE_REQUIRED:
            errors.append(message)
        else:
            warnings.append(f"{message} The optional image was omitted.")
        main_image_url = None
    if condition in CONDITION_IMAGE_REQUIRED and not main_image_url and not any(
        "Main image URL exceeds" in error for error in errors
    ):
        errors.append(f"Walmart requires a main image for condition {condition!r}.")

    resolved = {
        "product_id_type": product_id_type,
        "product_id": product_id,
        "shipping_weight_lbs": shipping_weight_lbs,
        "condition": condition,
        "price": price,
        "quantity": quantity,
        "main_image_url": main_image_url,
    }
    if errors:
        return None, errors, warnings, resolved

    entry: dict[str, Any] = {
        "sku": item.sku,
        "productIdentifiers": {
            "productIdType": product_id_type,
            "productId": product_id,
        },
        "ShippingWeight": round(float(shipping_weight_lbs), 3),
        "price": round(float(price), 2),
        "condition": condition,
    }
    if main_image_url:
        entry["mainImageUrl"] = main_image_url
    return entry, errors, warnings, resolved


def _product_identifier(
    item: InventoryItem,
    override: WalmartItemOverride,
) -> tuple[str | None, str | None]:
    if override.product_id_type and override.product_id:
        return override.product_id_type.upper(), _digits(override.product_id)

    specifics = {_normalize_key(key): value for key, value in item.item_specifics.items()}
    for identifier_type in PRODUCT_ID_TYPES:
        value = specifics.get(_normalize_key(identifier_type))
        if value:
            return identifier_type, _digits(value)
    return None, None


def _shipping_weight_lbs(item_specifics: dict[str, str]) -> float | None:
    normalized = {_normalize_key(key): value for key, value in item_specifics.items()}
    for key in ("shippingweight", "packageweight", "shippingweightlbs", "weight"):
        value = normalized.get(key)
        parsed = _parse_weight_lbs(value)
        if parsed is not None:
            return parsed
    return None


def _parse_weight_lbs(value: object) -> float | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*(lb|lbs|pound|pounds|oz|ounce|ounces|kg|g)?", text)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2) or "lb"
    if unit in {"oz", "ounce", "ounces"}:
        amount /= 16
    elif unit == "kg":
        amount *= 2.2046226218
    elif unit == "g":
        amount *= 0.0022046226218
    return round(amount, 3) if amount > 0 else None


def _walmart_condition(value: str | None) -> str | None:
    clean = re.sub(r"\s+", " ", str(value or "").strip()).lower()
    exact = {
        "new": "New",
        "brand new": "New",
        "new with defects": "New with defects",
        "new without box": "New without box",
        "new without tags": "New without tags",
        "open box": "Open Box",
        "remanufactured": "Remanufactured",
        "pre-owned: fair": "Pre-Owned: Fair",
        "pre-owned: good": "Pre-Owned: Good",
        "pre-owned: like new": "Pre-Owned: Like New",
        "used - acceptable": "Pre-Owned: Fair",
        "used - good": "Pre-Owned: Good",
        "used - excellent": "Pre-Owned: Like New",
        "used - like new": "Pre-Owned: Like New",
    }
    return exact.get(clean)


def _valid_product_identifier(identifier_type: str, value: str) -> bool:
    if not value.isdigit():
        return False
    lengths = {
        "GTIN": {14},
        "UPC": {12},
        "EAN": {13},
        "ISBN": {10, 13},
    }
    return len(value) in lengths.get(identifier_type, set())


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())
