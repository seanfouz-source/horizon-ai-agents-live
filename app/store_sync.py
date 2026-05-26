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

        try:
            items = await fetch_store_page_items(target_url, max_pages=page_count)
        except httpx.HTTPStatusError as exc:
            fallback = self._refresh_seed_fallback()
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": target_url,
                "status": "fallback" if fallback["available"] else "failed",
                "imported": fallback["imported"],
                "inventory_count": fallback["inventory_count"],
                "message": self._fallback_message(
                    f"eBay returned HTTP {exc.response.status_code}",
                    fallback,
                ),
                "last_attempt_at": attempted_at,
            }
            return self.last_status
        except httpx.HTTPError as exc:
            fallback = self._refresh_seed_fallback()
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": target_url,
                "status": "fallback" if fallback["available"] else "failed",
                "imported": fallback["imported"],
                "inventory_count": fallback["inventory_count"],
                "message": self._fallback_message(
                    f"Could not reach eBay store page: {exc.__class__.__name__}",
                    fallback,
                ),
                "last_attempt_at": attempted_at,
            }
            return self.last_status
        except Exception as exc:
            fallback = self._refresh_seed_fallback()
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": target_url,
                "status": "fallback" if fallback["available"] else "failed",
                "imported": fallback["imported"],
                "inventory_count": fallback["inventory_count"],
                "message": self._fallback_message(
                    f"Store page sync failed with {exc.__class__.__name__}",
                    fallback,
                ),
                "last_attempt_at": attempted_at,
            }
            return self.last_status

        if not items:
            fallback = self._refresh_seed_fallback()
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": target_url,
                "status": "fallback" if fallback["available"] else "empty",
                "imported": fallback["imported"],
                "inventory_count": fallback["inventory_count"],
                "message": self._fallback_message("No public listing cards were found", fallback),
                "last_attempt_at": attempted_at,
            }
            return self.last_status

        count = self.repository.upsert_items(items)
        self.last_status = {
            "source": "ebay-store-page",
            "store_url": target_url,
            "status": "ok",
            "imported": count,
            "inventory_count": self.repository.count(),
            "message": f"Imported {count} public eBay listings.",
            "last_attempt_at": attempted_at,
        }
        return self.last_status

    def _refresh_seed_fallback(self) -> dict[str, int | bool]:
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
        }

    @staticmethod
    def _fallback_message(reason: str, fallback: dict[str, int | bool]) -> str:
        if fallback["available"]:
            return (
                f"{reason}; refreshed fallback inventory from the seed/cache "
                f"and kept {fallback['inventory_count']} items available."
            )
        return f"{reason}; no fallback inventory is available."
