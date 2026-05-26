import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.inventory import InventoryRepository  # noqa: E402
from app.models import InventoryItem  # noqa: E402


def parse_item_specifics(value: str | None) -> dict[str, str]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(val) for key, val in parsed.items()}


def load_csv(path: Path) -> list[InventoryItem]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        items = []
        for row in reader:
            items.append(
                InventoryItem(
                    sku=row["sku"].strip(),
                    title=row["title"].strip(),
                    description=(row.get("description") or "").strip() or None,
                    condition=(row.get("condition") or "").strip() or None,
                    price=float(row["price"]) if row.get("price") else None,
                    currency=(row.get("currency") or "USD").strip() or "USD",
                    quantity=int(float(row.get("quantity") or 0)),
                    ebay_item_id=(row.get("ebay_item_id") or "").strip() or None,
                    ebay_url=(row.get("ebay_url") or "").strip() or None,
                    image_url=(row.get("image_url") or "").strip() or None,
                    category=(row.get("category") or "").strip() or None,
                    item_specifics=parse_item_specifics(row.get("item_specifics")),
                    source="csv",
                )
            )
    return items


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/import_inventory_csv.py data/inventory_sample.csv")
        return 2
    csv_path = Path(sys.argv[1]).resolve()
    settings = get_settings()
    repository = InventoryRepository(settings.resolved_database_path)
    count = repository.upsert_items(load_csv(csv_path))
    print(f"Imported {count} inventory items into {settings.resolved_database_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
