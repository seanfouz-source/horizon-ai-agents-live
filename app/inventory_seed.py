import csv
import json
from pathlib import Path

from app.inventory import InventoryRepository
from app.models import InventoryItem


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


def load_inventory_csv(path: Path) -> list[InventoryItem]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
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
                source="csv-seed",
            )
            for row in reader
        ]


def seed_inventory_if_empty(repository: InventoryRepository, csv_path: Path | None) -> int:
    if repository.count() > 0 or not csv_path or not csv_path.exists():
        return 0
    return repository.upsert_items(load_inventory_csv(csv_path))
