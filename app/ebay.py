import asyncio
import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from base64 import b64encode
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings
from app.models import InventoryItem


logger = logging.getLogger(__name__)
RETRY_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)


class EbayClient:
    base_url = "https://api.ebay.com"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._access_token = self._clean_access_token(settings.ebay_access_token)
        if not self._access_token and not self._has_refresh_credentials() and not self._has_client_credentials():
            raise RuntimeError(
                "EBAY_ACCESS_TOKEN, eBay OAuth refresh credentials, or EBAY_CLIENT_ID/EBAY_CLIENT_SECRET "
                "are required for live eBay sync."
            )

    async def fetch_inventory_items(self, limit: int = 200) -> list[InventoryItem]:
        sell_inventory_items: list[InventoryItem] = []
        try:
            sell_inventory_items = await self._fetch_sell_inventory_items(limit=limit)
        except httpx.HTTPError as exc:
            logger.warning("eBay Sell Inventory API sync failed: %s", exc.__class__.__name__)

        if sell_inventory_items:
            return sell_inventory_items

        seller_username = getattr(self.settings, "ebay_seller_username", None)
        if not seller_username:
            return []

        browse_items = await self._fetch_browse_seller_items(seller_username, limit=limit)
        if browse_items:
            logger.info("Imported %s active eBay listings through Browse API.", len(browse_items))
        if browse_items and self._has_refresh_credentials():
            try:
                trading_items = await self._enrich_with_trading_api(browse_items)
            except (httpx.HTTPError, RuntimeError) as exc:
                logger.warning(
                    "eBay Trading API enrichment could not start; using Browse data: %s",
                    exc,
                )
            else:
                logger.info(
                    "Expanded %s eBay listings into %s active seller SKU rows through Trading API.",
                    len(browse_items),
                    len(trading_items),
                )
                return trading_items
        return browse_items

    async def _fetch_sell_inventory_items(self, limit: int = 200) -> list[InventoryItem]:
        items: list[InventoryItem] = []
        offset = 0
        page_size = max(1, min(limit, 200))

        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            await self._ensure_access_token(client)
            while True:
                response = await self._get(
                    client,
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
                    item = self._apply_offer(item, offer)
                    if self._is_active_available_listing(item):
                        items.append(item)
                    else:
                        self._log_skipped_listing(item, self._listing_skip_reason(item))

                offset += len(raw_items)
                if offset >= int(payload.get("total", offset)) or len(raw_items) < page_size:
                    break

        return items

    async def _fetch_browse_seller_items(self, seller_username: str, limit: int = 200) -> list[InventoryItem]:
        items: list[InventoryItem] = []
        seen_item_ids: set[str] = set()
        seen_skus: set[str] = set()
        offset = 0
        page_size = max(1, min(limit, 200))
        query = getattr(self.settings, "ebay_browse_search_query", None)
        if query is None or query == "":
            query = " "

        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            await self._ensure_access_token(client, prefer_application=True)
            while len(items) < limit:
                response = await self._get(
                    client,
                    "/buy/browse/v1/item_summary/search",
                    params={
                        "q": query,
                        "filter": f"sellers:{{{seller_username}}}",
                        "limit": min(page_size, limit - len(items)),
                        "offset": offset,
                    },
                    headers=self._headers(),
                )
                response.raise_for_status()
                payload = response.json()
                summaries = payload.get("itemSummaries", [])
                if not summaries:
                    break

                for summary in summaries:
                    item_id = str(summary.get("itemId") or "")
                    if not item_id or item_id in seen_item_ids:
                        continue
                    seen_item_ids.add(item_id)
                    try:
                        detail = await self._fetch_browse_item_detail(client, item_id)
                    except httpx.HTTPError as exc:
                        logger.warning(
                            "Skipping eBay Browse item %s because detail fetch failed after retries: %s",
                            item_id,
                            exc,
                        )
                        continue
                    combined = {**summary, **detail}
                    try:
                        group_rows = await self._fetch_browse_item_group(client, combined)
                    except httpx.HTTPError as exc:
                        logger.warning(
                            "Could not expand eBay Browse item group %s; using parent data: %s",
                            item_id,
                            exc,
                        )
                        group_rows = []
                    for raw_item in group_rows or [combined]:
                        item = self._normalize_browse_item(raw_item)
                        if item.sku in seen_skus:
                            continue
                        seen_skus.add(item.sku)
                        if self._is_active_available_listing(item):
                            items.append(item)
                        else:
                            self._log_skipped_listing(item, self._listing_skip_reason(item))
                        if len(items) >= limit:
                            break
                    if len(items) >= limit:
                        break

                offset += len(summaries)
                if offset >= int(payload.get("total", offset)) or len(summaries) < page_size:
                    break

        return items

    async def _fetch_browse_item_detail(self, client: httpx.AsyncClient, item_id: str) -> dict[str, Any]:
        response = await self._get(
            client,
            f"/buy/browse/v1/item/{item_id}",
            params={"fieldgroups": "PRODUCT"},
            headers=self._headers(),
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def _fetch_browse_item_group(
        self,
        client: httpx.AsyncClient,
        raw_item: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not bool(getattr(self.settings, "ebay_expand_item_groups", False)):
            return []
        primary_group = raw_item.get("primaryItemGroup")
        group_id: object = None
        if isinstance(primary_group, dict):
            group_id = primary_group.get("itemGroupId")
        group_id = group_id or raw_item.get("itemGroupId")
        group_id = group_id or self._legacy_item_id(raw_item)
        if not group_id:
            return []

        response = await self._get(
            client,
            "/buy/browse/v1/item/get_items_by_item_group",
            params={"item_group_id": str(group_id), "fieldgroups": "PRODUCT"},
            headers=self._headers(),
        )
        if response.status_code in {400, 404}:
            return []
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        raw_group_items = payload.get("items")
        if not isinstance(raw_group_items, list):
            return []

        descriptions: dict[str, str] = {}
        for description_group in payload.get("commonDescriptions") or []:
            if not isinstance(description_group, dict):
                continue
            description = description_group.get("description")
            if not isinstance(description, str):
                continue
            for grouped_item_id in description_group.get("itemIds") or []:
                descriptions[str(grouped_item_id)] = description

        results: list[dict[str, Any]] = []
        for group_item in raw_group_items:
            if not isinstance(group_item, dict):
                continue
            item_id = str(group_item.get("itemId") or "")
            merged = {**raw_item, **group_item, "_browse_group_variant": True}
            if not merged.get("description") and item_id in descriptions:
                merged["description"] = descriptions[item_id]
            results.append(merged)
        if results:
            logger.info(
                "Expanded eBay Browse item group %s into %s purchasable variations.",
                group_id,
                len(results),
            )
        return results

    async def _enrich_with_trading_api(self, browse_items: list[InventoryItem]) -> list[InventoryItem]:
        enriched: list[InventoryItem] = []
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            await self._ensure_access_token(client)
            for browse_item in browse_items:
                if not browse_item.ebay_item_id:
                    enriched.append(browse_item)
                    continue
                try:
                    response = await self._post_content(
                        client,
                        "/ws/api.dll",
                        content=self._trading_get_item_request(browse_item.ebay_item_id),
                        headers=self._trading_headers(),
                    )
                    response.raise_for_status()
                    trading_items = self._parse_trading_get_item(response.content, browse_item)
                except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                    logger.warning(
                        "Could not enrich eBay listing %s through Trading API; using Browse data: %s",
                        browse_item.ebay_item_id,
                        exc,
                    )
                    enriched.append(browse_item)
                    continue

                active_items = [item for item in trading_items if self._is_active_available_listing(item)]
                if active_items:
                    enriched.extend(active_items)
                else:
                    self._log_skipped_listing(
                        browse_item,
                        "Trading API returned no active variation with available quantity",
                    )
        return enriched

    def _trading_headers(self) -> dict[str, str]:
        compatibility_level = str(
            getattr(self.settings, "ebay_trading_compatibility_level", "1455") or "1455"
        ).strip()
        return {
            "Content-Type": "text/xml;charset=UTF-8",
            "X-EBAY-API-IAF-TOKEN": str(self._access_token or ""),
            "X-EBAY-API-CALL-NAME": "GetItem",
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": compatibility_level,
        }

    @staticmethod
    def _trading_get_item_request(item_id: str) -> bytes:
        root = ET.Element("GetItemRequest", xmlns="urn:ebay:apis:eBLBaseComponents")
        ET.SubElement(root, "ItemID").text = str(item_id)
        ET.SubElement(root, "DetailLevel").text = "ReturnAll"
        ET.SubElement(root, "IncludeItemSpecifics").text = "true"
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _parse_trading_get_item(
        self,
        payload: bytes | str,
        browse_item: InventoryItem,
    ) -> list[InventoryItem]:
        root = ET.fromstring(payload)
        ack = self._xml_text(root, "Ack") or "Failure"
        if ack not in {"Success", "Warning"}:
            messages = [
                self._xml_text(error, "LongMessage") or self._xml_text(error, "ShortMessage")
                for error in self._xml_children(root, "Errors")
            ]
            clean_messages = [message for message in messages if message]
            raise ValueError("; ".join(clean_messages) or f"eBay Trading API returned {ack}.")

        item_node = self._xml_child(root, "Item")
        if item_node is None:
            raise ValueError("eBay Trading API response did not include an Item.")

        item_id = self._xml_text(item_node, "ItemID") or browse_item.ebay_item_id
        title = self._xml_text(item_node, "Title") or browse_item.title
        description = (
            self._clean_xml_description(self._xml_text(item_node, "Description"))
            or browse_item.description
        )
        condition = self._xml_text(item_node, "ConditionDisplayName") or browse_item.condition
        listing_status = (
            self._xml_nested_text(item_node, "SellingStatus", "ListingStatus")
            or browse_item.listing_status
            or "ACTIVE"
        ).upper()
        category = (
            self._xml_nested_text(item_node, "PrimaryCategory", "CategoryName")
            or browse_item.category
        )
        parent_specifics = self._xml_name_values(self._xml_child(item_node, "ItemSpecifics"))
        category_id = self._xml_nested_text(item_node, "PrimaryCategory", "CategoryID")
        condition_id = self._xml_text(item_node, "ConditionID")
        if category_id:
            parent_specifics["categoryId"] = category_id
        if condition_id:
            parent_specifics["conditionId"] = condition_id
        parent_specifics.update(
            self._xml_product_identifiers(self._xml_child(item_node, "ProductListingDetails"))
        )
        shipping_weight = self._xml_shipping_weight(item_node)
        if shipping_weight:
            parent_specifics["Shipping Weight"] = shipping_weight

        parent_images = self._dedupe_urls(
            [
                value
                for value in self._xml_child_texts(
                    self._xml_child(item_node, "PictureDetails"),
                    "PictureURL",
                )
                if value
            ]
            + browse_item.image_urls
        )
        item_price_node = self._xml_nested_child(item_node, "SellingStatus", "CurrentPrice")
        if item_price_node is None:
            item_price_node = self._xml_child(item_node, "StartPrice")
        item_price = self._float_value(item_price_node.text if item_price_node is not None else None)
        item_currency = (
            item_price_node.attrib.get("currencyID") if item_price_node is not None else None
        ) or browse_item.currency
        variations_node = self._xml_child(item_node, "Variations")
        variation_nodes = self._xml_children(variations_node, "Variation")
        if variation_nodes:
            picture_map = self._xml_variation_picture_map(variations_node)
            results: list[InventoryItem] = []
            for index, variation in enumerate(variation_nodes, start=1):
                variation_specifics = self._xml_name_values(
                    self._xml_child(variation, "VariationSpecifics")
                )
                specifics = dict(parent_specifics)
                specifics.update(variation_specifics)
                for identifier_name in list(specifics):
                    normalized_name = re.sub(r"[^a-z0-9]", "", identifier_name.lower())
                    if normalized_name in {"gtin", "upc", "ean", "isbn"}:
                        specifics.pop(identifier_name, None)
                specifics.update(
                    self._xml_product_identifiers(
                        self._xml_child(variation, "VariationProductListingDetails")
                    )
                )
                variation_sku = self._xml_text(variation, "SKU") or self._generated_variation_sku(
                    item_id or browse_item.ebay_item_id or browse_item.sku,
                    variation_specifics,
                    index,
                )
                total_quantity = self._int_value(self._xml_text(variation, "Quantity"))
                sold_quantity = self._int_value(
                    self._xml_nested_text(variation, "SellingStatus", "QuantitySold")
                )
                price_node = self._xml_child(variation, "StartPrice")
                price = self._float_value(price_node.text if price_node is not None else None)
                currency = (
                    price_node.attrib.get("currencyID") if price_node is not None else None
                ) or item_currency
                matched_images = self._variation_images(variation_specifics, picture_map)
                image_urls = self._dedupe_urls(matched_images + parent_images)
                variation_label = " / ".join(variation_specifics.values())
                variation_title = f"{title} - {variation_label}" if variation_label else title
                results.append(
                    InventoryItem(
                        sku=variation_sku,
                        title=variation_title,
                        description=description,
                        condition=condition,
                        price=price if price is not None else item_price or browse_item.price,
                        currency=currency,
                        quantity=max(0, total_quantity - sold_quantity),
                        ebay_item_id=item_id,
                        ebay_url=browse_item.ebay_url
                        or (f"https://www.ebay.com/itm/{item_id}" if item_id else None),
                        image_url=self._primary_image_url(matched_images)
                        or self._primary_image_url(parent_images),
                        image_urls=image_urls,
                        category=category,
                        listing_status=listing_status,
                        item_specifics=specifics,
                        source="ebay-trading-api",
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            return results

        total_quantity = self._int_value(self._xml_text(item_node, "Quantity"))
        sold_quantity = self._int_value(
            self._xml_nested_text(item_node, "SellingStatus", "QuantitySold")
        )
        item_sku = self._xml_text(item_node, "SKU") or browse_item.sku
        return [
            InventoryItem(
                sku=item_sku,
                title=title,
                description=description,
                condition=condition,
                price=item_price if item_price is not None else browse_item.price,
                currency=item_currency,
                quantity=max(0, total_quantity - sold_quantity),
                ebay_item_id=item_id,
                ebay_url=browse_item.ebay_url
                or (f"https://www.ebay.com/itm/{item_id}" if item_id else None),
                image_url=self._primary_image_url(parent_images) or browse_item.image_url,
                image_urls=parent_images,
                category=category,
                listing_status=listing_status,
                item_specifics=parent_specifics,
                source="ebay-trading-api",
                updated_at=datetime.now(timezone.utc),
            )
        ]

    @staticmethod
    def _xml_child(node: ET.Element | None, name: str) -> ET.Element | None:
        if node is None:
            return None
        for child in node:
            if str(child.tag).rsplit("}", 1)[-1] == name:
                return child
        return None

    @staticmethod
    def _xml_children(node: ET.Element | None, name: str) -> list[ET.Element]:
        if node is None:
            return []
        return [
            child
            for child in node
            if str(child.tag).rsplit("}", 1)[-1] == name
        ]

    @classmethod
    def _xml_nested_child(cls, node: ET.Element | None, *names: str) -> ET.Element | None:
        current = node
        for name in names:
            current = cls._xml_child(current, name)
            if current is None:
                return None
        return current

    @classmethod
    def _xml_text(cls, node: ET.Element | None, name: str) -> str | None:
        child = cls._xml_child(node, name)
        if child is None or child.text is None:
            return None
        value = child.text.strip()
        return value or None

    @classmethod
    def _xml_nested_text(cls, node: ET.Element | None, *names: str) -> str | None:
        child = cls._xml_nested_child(node, *names)
        if child is None or child.text is None:
            return None
        value = child.text.strip()
        return value or None

    @classmethod
    def _xml_child_texts(cls, node: ET.Element | None, name: str) -> list[str]:
        return [
            child.text.strip()
            for child in cls._xml_children(node, name)
            if child.text and child.text.strip()
        ]

    @classmethod
    def _xml_name_values(cls, container: ET.Element | None) -> dict[str, str]:
        values: dict[str, str] = {}
        for pair in cls._xml_children(container, "NameValueList"):
            name = cls._xml_text(pair, "Name")
            pair_values = cls._xml_child_texts(pair, "Value")
            if name and pair_values:
                values[name] = ", ".join(pair_values)
        return values

    @classmethod
    def _xml_product_identifiers(cls, container: ET.Element | None) -> dict[str, str]:
        identifiers: dict[str, str] = {}
        for name in ("GTIN", "UPC", "EAN", "ISBN"):
            value = cls._xml_text(container, name)
            if value:
                identifiers[name] = value
        return identifiers

    @classmethod
    def _xml_shipping_weight(cls, item_node: ET.Element) -> str | None:
        package = cls._xml_child(item_node, "ShippingPackageDetails")
        weight_lbs = 0.0
        found = False
        for name in ("WeightMajor", "WeightMinor"):
            measure = cls._xml_child(package, name)
            if measure is None or measure.text is None:
                continue
            try:
                amount = float(measure.text.strip())
            except (TypeError, ValueError):
                continue
            unit = str(measure.attrib.get("unit") or "lb").strip().lower()
            factors = {
                "lb": 1.0,
                "lbs": 1.0,
                "pound": 1.0,
                "oz": 1 / 16,
                "ounce": 1 / 16,
                "kg": 2.2046226218,
                "kilogram": 2.2046226218,
                "g": 0.0022046226218,
                "gr": 0.0022046226218,
                "gram": 0.0022046226218,
            }
            factor = factors.get(unit)
            if factor is None:
                continue
            weight_lbs += amount * factor
            found = True
        if not found or weight_lbs <= 0:
            return None
        formatted = f"{weight_lbs:.3f}".rstrip("0").rstrip(".")
        return f"{formatted} lb"

    @classmethod
    def _xml_variation_picture_map(
        cls,
        variations_node: ET.Element | None,
    ) -> dict[tuple[str, str], list[str]]:
        picture_map: dict[tuple[str, str], list[str]] = {}
        for pictures in cls._xml_children(variations_node, "Pictures"):
            name = cls._xml_text(pictures, "VariationSpecificName")
            if not name:
                continue
            for picture_set in cls._xml_children(pictures, "VariationSpecificPictureSet"):
                value = cls._xml_text(picture_set, "VariationSpecificValue")
                urls = cls._xml_child_texts(picture_set, "PictureURL")
                if value and urls:
                    picture_map[(name.casefold(), value.casefold())] = urls
        return picture_map

    @staticmethod
    def _variation_images(
        variation_specifics: dict[str, str],
        picture_map: dict[tuple[str, str], list[str]],
    ) -> list[str]:
        urls: list[str] = []
        for name, value in variation_specifics.items():
            urls.extend(picture_map.get((name.casefold(), value.casefold()), []))
        return EbayClient._dedupe_urls(urls)

    @staticmethod
    def _generated_variation_sku(
        item_id: str,
        variation_specifics: dict[str, str],
        index: int,
    ) -> str:
        identity = "|".join(
            f"{name}={value}" for name, value in sorted(variation_specifics.items())
        ) or str(index)
        suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", f"EBAY-{item_id}").strip("-.")
        return f"{base[:39]}-{suffix}"

    @staticmethod
    def _clean_xml_description(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"<[^>]+>", " ", value)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:500] or None

    @staticmethod
    def _int_value(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Content-Language": "en-US",
            "X-EBAY-C-MARKETPLACE-ID": self.settings.ebay_marketplace_id,
        }

    def _has_refresh_credentials(self) -> bool:
        return all(
            str(getattr(self.settings, field, "") or "").strip()
            for field in ("ebay_client_id", "ebay_client_secret", "ebay_refresh_token")
        )

    def _has_client_credentials(self) -> bool:
        return all(
            str(getattr(self.settings, field, "") or "").strip()
            for field in ("ebay_client_id", "ebay_client_secret")
        )

    async def _ensure_access_token(
        self,
        client: httpx.AsyncClient,
        *,
        prefer_application: bool = False,
    ) -> None:
        if prefer_application and self._has_client_credentials():
            refreshed_token = await self._client_credentials_access_token(client)
        elif self._has_refresh_credentials():
            refreshed_token = await self._refresh_access_token(client)
        elif self._has_client_credentials():
            refreshed_token = await self._client_credentials_access_token(client)
        else:
            refreshed_token = None
        if refreshed_token:
            self._access_token = refreshed_token

    async def _refresh_access_token(self, client: httpx.AsyncClient) -> str | None:
        client_id = str(getattr(self.settings, "ebay_client_id", "") or "").strip()
        client_secret = str(getattr(self.settings, "ebay_client_secret", "") or "").strip()
        refresh_token = str(getattr(self.settings, "ebay_refresh_token", "") or "").strip()
        scopes = str(getattr(self.settings, "ebay_oauth_scopes", "") or "").strip()
        if not client_id or not client_secret or not refresh_token:
            return None

        credentials = b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if scopes:
            data["scope"] = scopes
        response = await self._post(
            client,
            "/identity/v1/oauth2/token",
            data=data,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise RuntimeError("eBay OAuth refresh response did not include an access token.")
        logger.info("Refreshed eBay access token for inventory sync.")
        return access_token.strip()

    async def _client_credentials_access_token(self, client: httpx.AsyncClient) -> str | None:
        client_id = str(getattr(self.settings, "ebay_client_id", "") or "").strip()
        client_secret = str(getattr(self.settings, "ebay_client_secret", "") or "").strip()
        scopes = str(getattr(self.settings, "ebay_oauth_scopes", "") or "").strip()
        if not client_id or not client_secret:
            return None

        credentials = b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        data = {
            "grant_type": "client_credentials",
        }
        if scopes:
            data["scope"] = scopes
        response = await self._post(
            client,
            "/identity/v1/oauth2/token",
            data=data,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise RuntimeError("eBay OAuth client credentials response did not include an access token.")
        logger.info("Minted eBay application access token for inventory sync.")
        return access_token.strip()

    async def _fetch_offer(self, client: httpx.AsyncClient, sku: str) -> dict[str, Any]:
        response = await self._get(
            client,
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
        item_specifics.update(self._sell_product_identifiers(product))
        item_specifics.update(self._sell_package_specifics(raw_item))
        image_urls = self._image_urls_from_sell_product(product)
        item_id = str(raw_item.get("sku") or "")

        return InventoryItem(
            sku=item_id,
            title=str(product.get("title") or item_id or "Untitled eBay item"),
            description=product.get("description"),
            condition=raw_item.get("condition"),
            quantity=int(availability.get("quantity") or 0),
            image_url=self._primary_image_url(image_urls),
            image_urls=image_urls,
            item_specifics=item_specifics,
            source="ebay-api",
            updated_at=datetime.now(timezone.utc),
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
        item.listing_status = str(offer.get("status") or listing.get("listingStatus") or "PUBLISHED")
        if offer.get("availableQuantity") is not None:
            item.quantity = int(offer.get("availableQuantity") or item.quantity)
        return item

    def _normalize_browse_item(self, raw_item: dict[str, Any]) -> InventoryItem:
        legacy_item_id = self._legacy_item_id(raw_item)
        restful_item_id = str(raw_item.get("itemId") or "")
        image_urls = self._image_urls_from_browse_item(raw_item)
        price = raw_item.get("price") or {}
        availability = self._browse_availability(raw_item)
        item_specifics = self._browse_item_specifics(raw_item)
        category = self._browse_category(raw_item)
        short_description = self._short_description(raw_item)

        return InventoryItem(
            sku=(
                self._generated_browse_variation_sku(legacy_item_id or restful_item_id, restful_item_id)
                if raw_item.get("_browse_group_variant")
                else f"EBAY-{legacy_item_id}" if legacy_item_id else restful_item_id
            ),
            title=str(raw_item.get("title") or f"eBay listing {legacy_item_id}"),
            description=short_description,
            condition=raw_item.get("condition"),
            price=self._float_value(price.get("value")),
            currency=str(price.get("currency") or "USD"),
            quantity=availability["quantity"],
            ebay_item_id=legacy_item_id,
            ebay_url=raw_item.get("itemWebUrl") or (f"https://www.ebay.com/itm/{legacy_item_id}" if legacy_item_id else None),
            image_url=self._primary_image_url(image_urls),
            image_urls=image_urls,
            category=category,
            listing_status=availability["status"],
            item_specifics=item_specifics,
            source="ebay-browse-api",
            updated_at=datetime.now(timezone.utc),
        )

    def _is_active_available_listing(self, item: InventoryItem) -> bool:
        return self._listing_skip_reason(item) is None

    @staticmethod
    def _listing_skip_reason(item: InventoryItem) -> str | None:
        if item.quantity <= 0:
            return "listing has no available quantity"
        if not item.image_url:
            return "listing has no valid primary eBay image"
        status = (item.listing_status or "ACTIVE").strip().upper()
        if status in {"SOLD", "ENDED", "INACTIVE", "OUT_OF_STOCK", "UNAVAILABLE"}:
            return f"listing status is {status}"
        if status in {"ACTIVE", "IN_STOCK", "PUBLISHED", "LIVE"} or not item.listing_status:
            return None
        return f"listing status is {status}"

    @staticmethod
    def _log_skipped_listing(item: InventoryItem, reason: str | None) -> None:
        logger.warning(
            "Skipping eBay listing for inventory social automation: ebay_item_id=%s sku=%s title=%r "
            "image_url=%s ebay_url=%s status=skipped error=%s",
            item.ebay_item_id,
            item.sku,
            item.title,
            item.image_url,
            item.ebay_url,
            reason or "not promotable",
        )

    @staticmethod
    def _legacy_item_id(raw_item: dict[str, Any]) -> str | None:
        value = raw_item.get("legacyItemId")
        if value:
            return str(value)
        item_id = str(raw_item.get("itemId") or "")
        match = re.search(r"\|(\d+)\|", item_id)
        return match.group(1) if match else None

    @staticmethod
    def _float_value(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _short_description(raw_item: dict[str, Any]) -> str | None:
        value = raw_item.get("shortDescription") or raw_item.get("conditionDescription") or raw_item.get("description")
        if not isinstance(value, str):
            return None
        cleaned = re.sub(r"<[^>]+>", " ", value)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:500] or None

    @staticmethod
    def _browse_category(raw_item: dict[str, Any]) -> str | None:
        category_path = raw_item.get("categoryPath")
        if isinstance(category_path, str) and category_path.strip():
            return category_path.strip()
        categories = raw_item.get("categories")
        if isinstance(categories, list) and categories:
            names = [str(category.get("categoryName")) for category in categories if isinstance(category, dict)]
            return " > ".join(name for name in names if name and name != "None") or None
        return None

    @staticmethod
    def _browse_availability(raw_item: dict[str, Any]) -> dict[str, int | str]:
        availabilities = raw_item.get("estimatedAvailabilities")
        if not isinstance(availabilities, list) or not availabilities:
            return {"quantity": 1, "status": "ACTIVE"}

        quantity = 0
        status = "OUT_OF_STOCK"
        for availability in availabilities:
            if not isinstance(availability, dict):
                continue
            availability_status = str(availability.get("estimatedAvailabilityStatus") or "").upper()
            available_quantity = availability.get("estimatedAvailableQuantity")
            remaining_quantity = availability.get("estimatedRemainingQuantity")
            candidate_quantity = available_quantity if available_quantity is not None else remaining_quantity
            if availability_status in {"IN_STOCK", "LIMITED_STOCK"}:
                status = "IN_STOCK"
                quantity = max(quantity, int(candidate_quantity or 1))
        return {"quantity": quantity, "status": status}

    @staticmethod
    def _browse_item_specifics(raw_item: dict[str, Any]) -> dict[str, str]:
        item_specifics: dict[str, str] = {}
        localized_aspects = raw_item.get("localizedAspects")
        if isinstance(localized_aspects, list):
            for aspect in localized_aspects:
                if not isinstance(aspect, dict):
                    continue
                name = str(aspect.get("name") or "").strip()
                value = str(aspect.get("value") or "").strip()
                if name and value:
                    item_specifics[name] = value
        direct_fields = {
            "brand": "Brand",
            "color": "Color",
            "gtin": "GTIN",
            "upc": "UPC",
            "ean": "EAN",
            "isbn": "ISBN",
            "mpn": "MPN",
            "conditionId": "conditionId",
            "categoryId": "categoryId",
            "listingMarketplaceId": "listingMarketplaceId",
        }
        for field, label in direct_fields.items():
            value = raw_item.get(field)
            if value:
                if isinstance(value, list):
                    clean_values = [str(part).strip() for part in value if str(part).strip()]
                    if clean_values:
                        item_specifics[label] = clean_values[0]
                else:
                    item_specifics[label] = str(value)
        product = raw_item.get("product")
        if isinstance(product, dict):
            gtins = product.get("gtins")
            if isinstance(gtins, list):
                clean_gtins = [str(value).strip() for value in gtins if str(value).strip()]
                if clean_gtins:
                    item_specifics["GTIN"] = clean_gtins[0]
            mpns = product.get("mpns")
            if isinstance(mpns, list):
                clean_mpns = [str(value).strip() for value in mpns if str(value).strip()]
                if clean_mpns:
                    item_specifics["MPN"] = clean_mpns[0]
            brand = product.get("brand")
            if brand:
                item_specifics["Brand"] = str(brand).strip()
        item_specifics.update(EbayClient._browse_shipping_specifics(raw_item))
        return item_specifics

    @staticmethod
    def _generated_browse_variation_sku(legacy_item_id: str, restful_item_id: str) -> str:
        suffix = hashlib.sha256(restful_item_id.encode("utf-8")).hexdigest()[:10]
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", f"EBAY-{legacy_item_id}").strip("-.")
        return f"{base[:39]}-{suffix}"

    @staticmethod
    def _sell_product_identifiers(product: dict[str, Any]) -> dict[str, str]:
        identifiers: dict[str, str] = {}
        fields = {
            "brand": "Brand",
            "mpn": "MPN",
            "gtin": "GTIN",
            "upc": "UPC",
            "ean": "EAN",
            "isbn": "ISBN",
        }
        for field, label in fields.items():
            value = product.get(field)
            if isinstance(value, list):
                clean_values = [str(part).strip() for part in value if str(part).strip()]
                if clean_values:
                    identifiers[label] = clean_values[0]
            elif value is not None and str(value).strip():
                identifiers[label] = str(value).strip()
        return identifiers

    @staticmethod
    def _sell_package_specifics(raw_item: dict[str, Any]) -> dict[str, str]:
        package = raw_item.get("packageWeightAndSize")
        if not isinstance(package, dict):
            return {}
        weight = package.get("weight")
        if not isinstance(weight, dict) or weight.get("value") is None:
            return {}
        unit = str(weight.get("unit") or "POUND").strip().lower()
        unit_labels = {
            "pound": "lb",
            "ounce": "oz",
            "kilogram": "kg",
            "gram": "g",
        }
        return {"Shipping Weight": f"{weight['value']} {unit_labels.get(unit, unit)}"}

    @staticmethod
    def _browse_shipping_specifics(raw_item: dict[str, Any]) -> dict[str, str]:
        shipping_options = raw_item.get("shippingOptions")
        if not isinstance(shipping_options, list):
            return {}
        for option in shipping_options:
            if not isinstance(option, dict):
                continue
            shipping_cost = option.get("shippingCost") or option.get("shippingCostConverted")
            if not isinstance(shipping_cost, dict):
                continue
            value = EbayClient._float_value(shipping_cost.get("value"))
            currency = str(shipping_cost.get("currency") or "USD")
            if value is None:
                continue
            if value == 0:
                return {"Shipping": "Free Shipping", "Shipping Cost": f"0 {currency}"}
            return {"Shipping Cost": f"{value:g} {currency}"}
        return {}

    def _image_urls_from_sell_product(self, product: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for value in product.get("imageUrls") or []:
            if isinstance(value, str):
                urls.append(value)
        return self._dedupe_urls(urls)

    def _image_urls_from_browse_item(self, raw_item: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for field in ("image", "additionalImages", "thumbnailImages"):
            value = raw_item.get(field)
            if isinstance(value, dict):
                url = value.get("imageUrl")
                if isinstance(url, str):
                    urls.append(url)
            elif isinstance(value, list):
                for image in value:
                    if isinstance(image, dict) and isinstance(image.get("imageUrl"), str):
                        urls.append(str(image["imageUrl"]))
        return self._dedupe_urls(urls)

    def _primary_image_url(self, urls: list[str]) -> str | None:
        usable_urls = [url for url in self._dedupe_urls(urls) if self._usable_image_url(url)]
        if not usable_urls:
            return None
        return max(
            enumerate(usable_urls),
            key=lambda pair: (self._image_url_pixel_hint(pair[1]), -pair[0]),
        )[1]

    @staticmethod
    def _image_url_pixel_hint(url: str) -> int:
        match = re.search(r"/s-l(\d+)(?:[./?]|$)", url.lower())
        if not match:
            return 0
        return int(match.group(1))

    @staticmethod
    def _usable_image_url(url: str) -> bool:
        lowered = url.lower().split("?")[0]
        return lowered.startswith("https://") and any(
            marker in lowered
            for marker in (".jpg", ".jpeg", ".png", ".webp", "/images/", "i.ebayimg.com")
        )

    @staticmethod
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

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self._request_with_retry(client, "GET", path, params=params, headers=headers)

    async def _post(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        data: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self._request_with_retry(client, "POST", path, data=data, headers=headers)

    async def _post_content(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        content: bytes | str,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self._request_with_retry(
            client,
            "POST",
            path,
            content=content,
            headers=headers,
        )

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        data: dict[str, object] | None = None,
        content: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        last_exc: httpx.HTTPError | None = None
        for attempt, delay in enumerate((*RETRY_DELAYS_SECONDS, 0.0), start=1):
            try:
                if method == "POST":
                    if content is not None:
                        response = await client.post(path, content=content, headers=headers)
                    else:
                        response = await client.post(path, data=data, headers=headers)
                else:
                    response = await client.get(path, params=params, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                if delay:
                    logger.warning(
                        "Temporary eBay %s %s failure on attempt %s; retrying in %.1fs: %s",
                        method,
                        path,
                        attempt,
                        delay,
                        exc.__class__.__name__,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

            if response.status_code in RETRY_STATUS_CODES and delay:
                logger.warning(
                    "Temporary eBay %s %s HTTP %s on attempt %s; retrying in %.1fs.",
                    method,
                    path,
                    response.status_code,
                    attempt,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            if response.status_code == 401 and await self._recover_access_token(client, path):
                headers = self._with_current_bearer_token(headers)
                logger.warning(
                    "eBay %s %s returned 401 Unauthorized; minted a fresh OAuth token and retrying once.",
                    method,
                    path,
                )
                if method == "POST":
                    if content is not None:
                        response = await client.post(path, content=content, headers=headers)
                    else:
                        response = await client.post(path, data=data, headers=headers)
                else:
                    response = await client.get(path, params=params, headers=headers)
            return response

        if last_exc:
            raise last_exc
        raise RuntimeError(f"eBay {method} {path} failed before returning a response.")

    async def _recover_access_token(self, client: httpx.AsyncClient, path: str) -> bool:
        if path == "/identity/v1/oauth2/token":
            return False
        try:
            if path.startswith("/buy/browse/") and self._has_client_credentials():
                token = await self._client_credentials_access_token(client)
            elif self._has_refresh_credentials():
                token = await self._refresh_access_token(client)
            elif self._has_client_credentials():
                token = await self._client_credentials_access_token(client)
            else:
                return False
        except httpx.HTTPError as exc:
            logger.warning("Could not recover eBay OAuth token after 401: %s", exc)
            return False
        if not token:
            return False
        self._access_token = token
        return True

    def _with_current_bearer_token(self, headers: dict[str, str] | None) -> dict[str, str] | None:
        if headers is None:
            return None
        updated = dict(headers)
        if "X-EBAY-API-IAF-TOKEN" in updated:
            updated["X-EBAY-API-IAF-TOKEN"] = str(self._access_token or "")
        else:
            updated["Authorization"] = f"Bearer {self._access_token}"
        return updated

    @staticmethod
    def _clean_access_token(value: object) -> str | None:
        token = str(value or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        return token or None
