import json
import sqlite3
import string
from pathlib import Path
from typing import Iterable

from app.models import InventoryItem


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "cost",
    "do",
    "does",
    "for",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "much",
    "of",
    "on",
    "or",
    "price",
    "that",
    "the",
    "this",
    "to",
    "with",
    "you",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory_items (
    sku TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    condition TEXT,
    price REAL,
    currency TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    ebay_item_id TEXT,
    ebay_url TEXT,
    image_url TEXT,
    category TEXT,
    item_specifics TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inventory_title ON inventory_items(title);
CREATE INDEX IF NOT EXISTS idx_inventory_ebay_item_id ON inventory_items(ebay_item_id);
"""


class InventoryRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM inventory_items").fetchone()
        return int(row["total"])

    def upsert_items(self, items: Iterable[InventoryItem]) -> int:
        rows = [self._to_row(item) for item in items]
        if not rows:
            return 0
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO inventory_items (
                    sku, title, description, condition, price, currency, quantity,
                    ebay_item_id, ebay_url, image_url, category, item_specifics,
                    source, updated_at
                )
                VALUES (
                    :sku, :title, :description, :condition, :price, :currency, :quantity,
                    :ebay_item_id, :ebay_url, :image_url, :category, :item_specifics,
                    :source, :updated_at
                )
                ON CONFLICT(sku) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    condition = excluded.condition,
                    price = excluded.price,
                    currency = excluded.currency,
                    quantity = excluded.quantity,
                    ebay_item_id = excluded.ebay_item_id,
                    ebay_url = excluded.ebay_url,
                    image_url = excluded.image_url,
                    category = excluded.category,
                    item_specifics = excluded.item_specifics,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def get(self, sku: str) -> InventoryItem | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM inventory_items WHERE sku = ?",
                (sku,),
            ).fetchone()
        return self._from_row(row) if row else None

    def search(self, query: str | None, limit: int = 8, in_stock_only: bool = True) -> list[InventoryItem]:
        limit = max(1, min(limit, 25))
        terms = []
        for raw_term in (query or "").split():
            term = raw_term.strip(string.punctuation).lower()
            if term and term not in STOPWORDS:
                terms.append(term)
        where = []
        params: list[object] = []

        if in_stock_only:
            where.append("quantity > 0")

        for term in terms:
            like = f"%{term}%"
            where.append(
                """
                (
                    lower(sku) LIKE ?
                    OR lower(title) LIKE ?
                    OR lower(coalesce(description, '')) LIKE ?
                    OR lower(coalesce(category, '')) LIKE ?
                    OR lower(item_specifics) LIKE ?
                )
                """
            )
            params.extend([like, like, like, like, like])

        sql = "SELECT * FROM inventory_items"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY quantity DESC, updated_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def all_promotable(self, limit: int = 12) -> list[InventoryItem]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM inventory_items
                WHERE quantity > 0
                ORDER BY updated_at DESC, quantity DESC
                LIMIT ?
                """,
                (max(1, min(limit, 50)),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def _to_row(self, item: InventoryItem) -> dict[str, object]:
        return {
            **item.model_dump(exclude={"item_specifics", "updated_at"}),
            "item_specifics": json.dumps(item.item_specifics, sort_keys=True),
            "updated_at": item.updated_at.isoformat(),
        }

    def _from_row(self, row: sqlite3.Row) -> InventoryItem:
        data = dict(row)
        data["item_specifics"] = json.loads(data.get("item_specifics") or "{}")
        return InventoryItem.model_validate(data)
