import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.inventory import InventoryRepository  # noqa: E402
from app.store_sync import StorePageSyncer  # noqa: E402


async def run(store_url: str | None, max_pages: int | None) -> int:
    settings = get_settings()
    repository = InventoryRepository(settings.resolved_database_path)
    syncer = StorePageSyncer(settings, repository)
    status = await syncer.sync(store_url, max_pages)
    print(status["message"])
    print(f"Status: {status['status']}")
    print(f"Database: {settings.resolved_database_path}")
    return 0 if status["status"] in {"ok", "empty", "skipped", "failed"} else 1


def main() -> int:
    if len(sys.argv) > 3:
        print("Usage: python scripts/import_ebay_store_url.py ['https://www.ebay.com/str/STORE'] [max_pages]")
        return 2
    store_url = sys.argv[1] if len(sys.argv) >= 2 else None
    max_pages = int(sys.argv[2]) if len(sys.argv) == 3 else None
    return asyncio.run(run(store_url, max_pages))


if __name__ == "__main__":
    raise SystemExit(main())
