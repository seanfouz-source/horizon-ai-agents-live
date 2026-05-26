from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings
from app.ebay_store_page import fetch_store_page_items
from app.inventory import InventoryRepository
from app.inventory_seed import load_inventory_csv


class StorePageSyncer:
    def __init__(self, settings: Settings, repository: InventoryRepository):
        self.settings = settings
        self.repository = repository
        self.last_status: dict[str, Any] = {
            "source": "ebay-store-page",
            "store_url": settings.ebay_store_url,
            "status": "not_run",
            "imported": 0,
            "message": "Store page sync has not run yet.",
            "last_attempt_at": None,
        }

    async def sync(self, store_url: str | None = None, max_pages: int | None = None) -> dict[str, Any]:
        target_url = store_url or self.settings.ebay_store_url
        page_count = max_pages or self.settings.ebay_store_max_pages
        attempted_at = datetime.now(timezone.utc).isoformat()

        if not target_url:
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": None,
                "status": "skipped",
                "imported": 0,
                "message": "No eBay store URL is configured.",
                "last_attempt_at": attempted_at,
            }
            return self.last_status

        attempt_urls = [target_url]
        backup_url = getattr(self.settings, "ebay_store_backup_url", None)
        if backup_url and backup_url not in attempt_urls:
            attempt_urls.append(backup_url)

        last_failure = "No public listing cards were found"
        for attempt_url in attempt_urls:
            try:
                items = await fetch_store_page_items(attempt_url, max_pages=page_count)
            except httpx.HTTPStatusError as exc:
                last_failure = f"eBay returned HTTP {exc.response.status_code}"
                continue
            except httpx.HTTPError as exc:
                last_failure = f"Could not reach eBay store page: {exc.__class__.__name__}"
                continue
            except Exception as exc:
                last_failure = f"Store page sync failed with {exc.__class__.__name__}"
                continue

            if not items:
                last_failure = "No public listing cards were found"
                continue

            count = self.repository.upsert_items(items)
            used_backup = attempt_url != target_url
            message = f"Imported {count} public eBay listings."
            if used_backup:
                message = f"{message} Used backup store URL after the primary URL did not return listings."
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": attempt_url,
                "status": "ok",
                "imported": count,
                "inventory_count": self.repository.count(),
                "message": message,
                "last_attempt_at": attempted_at,
            }
            return self.last_status

        fallback = self._fallback_inventory()
        self.last_status = {
            "source": "ebay-store-page",
            "store_url": target_url,
            "status": fallback["status"],
            "imported": fallback["imported"],
            "inventory_count": fallback["inventory_count"],
            "message": self._fallback_message(last_failure, fallback),
            "last_attempt_at": attempted_at,
        }
        return self.last_status

    def _fallback_inventory(self) -> dict[str, int | bool | str]:
        inventory_count = self.repository.count()
        if inventory_count > 0:
            return {
                "available": True,
                "imported": 0,
                "inventory_count": inventory_count,
                "status": "cached",
                "source": "cache",
            }

        seed_path = getattr(self.settings, "seed_inventory_csv", None)
        imported = 0
        available = False
        if seed_path and seed_path.exists():
            items = load_inventory_csv(seed_path)
            imported = self.repository.upsert_items(items)
            available = bool(items)
        inventory_count = self.repository.count()
        return {
            "available": available or inventory_count > 0,
            "imported": imported,
            "inventory_count": inventory_count,
            "status": "fallback" if available or inventory_count > 0 else "failed",
            "source": "seed",
        }

    @staticmethod
    def _fallback_message(reason: str, fallback: dict[str, int | bool | str]) -> str:
        if fallback["source"] == "cache":
            return (
                f"{reason}; preserved the last successful inventory cache "
                f"with {fallback['inventory_count']} items available."
            )
        if fallback["available"]:
            return (
                f"{reason}; refreshed fallback inventory from the seed/cache "
                f"and kept {fallback['inventory_count']} items available."
            )
        return f"{reason}; no fallback inventory is available."
