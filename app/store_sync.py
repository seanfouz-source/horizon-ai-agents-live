from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings
from app.ebay_store_page import fetch_store_page_items
from app.inventory import InventoryRepository


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
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": target_url,
                "status": "failed",
                "imported": 0,
                "message": f"eBay returned HTTP {exc.response.status_code}; kept existing inventory.",
                "last_attempt_at": attempted_at,
            }
            return self.last_status
        except httpx.HTTPError as exc:
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": target_url,
                "status": "failed",
                "imported": 0,
                "message": f"Could not reach eBay store page: {exc.__class__.__name__}; kept existing inventory.",
                "last_attempt_at": attempted_at,
            }
            return self.last_status
        except Exception as exc:
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": target_url,
                "status": "failed",
                "imported": 0,
                "message": f"Store page sync failed with {exc.__class__.__name__}; kept existing inventory.",
                "last_attempt_at": attempted_at,
            }
            return self.last_status

        if not items:
            self.last_status = {
                "source": "ebay-store-page",
                "store_url": target_url,
                "status": "empty",
                "imported": 0,
                "message": "No public listing cards were found; kept existing inventory.",
                "last_attempt_at": attempted_at,
            }
            return self.last_status

        count = self.repository.upsert_items(items)
        self.last_status = {
            "source": "ebay-store-page",
            "store_url": target_url,
            "status": "ok",
            "imported": count,
            "message": f"Imported {count} public eBay listings.",
            "last_attempt_at": attempted_at,
        }
        return self.last_status
