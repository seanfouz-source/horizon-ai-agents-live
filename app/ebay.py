from typing import Any

import httpx

from app.config import Settings
from app.models import InventoryItem


class EbayClient:
    base_url = "https://api.ebay.com"

    def __init__(self, settings: Settings):
        if not settings.ebay_access_token:
            raise RuntimeError("EBAY_ACCESS_TOKEN is required for live eBay sync.")
        self.settings = settings

    async def fetch_inventory_items(self, limit: int = 200) -> list[InventoryItem]:
        items: list[InventoryItem] = []
        offset = 0
        page_size = max(1, min(limit, 200))

        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            while True:
                response = await client.get(
                    "/sell/inventory/v1/inventory_item",
                    params={"limit": page_size, "offset": offset},
                    headers=self._headers(),
                )
                response.raise_for_status()
                payload = response.json()
                raw_items = payload.get("inventoryItems", [])
                if not raw_items:
                    break

                for raw_item in raw_items:
                    item = self._normalize_inventory_item(raw_item)
                    offer = await self._fetch_offer(client, item.sku)
                    items.append(self._apply_offer(item, offer))

                offset += len(raw_items)
                if offset >= int(payload.get("total", offset)) or len(raw_items) < page_size:
                    break

        return items

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.ebay_access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Content-Language": "en-US",
            "X-EBAY-C-MARKETPLACE-ID": self.settings.ebay_marketplace_id,
        }

    async def _fetch_offer(self, client: httpx.AsyncClient, sku: str) -> dict[str, Any]:
        response = await client.get(
            "/sell/inventory/v1/offer",
            params={"sku": sku},
            headers=self._headers(),
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        offers = response.json().get("offers", [])
        return offers[0] if offers else {}

    def _normalize_inventory_item(self, raw_item: dict[str, Any]) -> InventoryItem:
        product = raw_item.get("product", {})
        availability = raw_item.get("availability", {}).get("shipToLocationAvailability", {})
        aspects = product.get("aspects") or {}
        item_specifics = {
            str(key): ", ".join(value) if isinstance(value, list) else str(value)
            for key, value in aspects.items()
        }

        return InventoryItem(
            sku=str(raw_item.get("sku") or ""),
            title=str(product.get("title") or raw_item.get("sku") or "Untitled eBay item"),
            description=product.get("description"),
            condition=raw_item.get("condition"),
            quantity=int(availability.get("quantity") or 0),
            image_url=(product.get("imageUrls") or [None])[0],
            item_specifics=item_specifics,
            source="ebay-api",
        )

    def _apply_offer(self, item: InventoryItem, offer: dict[str, Any]) -> InventoryItem:
        price = (offer.get("pricingSummary") or {}).get("price") or {}
        listing = offer.get("listing") or {}
        listing_id = listing.get("listingId") or offer.get("listingId")

        if price.get("value") is not None:
            item.price = float(price["value"])
            item.currency = price.get("currency") or item.currency
        if listing_id:
            item.ebay_item_id = str(listing_id)
            item.ebay_url = f"https://www.ebay.com/itm/{listing_id}"
        return item
