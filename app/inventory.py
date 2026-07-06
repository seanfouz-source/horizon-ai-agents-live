import json
import sqlite3
import string
from datetime import date, datetime, timedelta, timezone
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
    image_urls TEXT NOT NULL DEFAULT '[]',
    category TEXT,
    listing_status TEXT,
    item_specifics TEXT NOT NULL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inventory_title ON inventory_items(title);
CREATE INDEX IF NOT EXISTS idx_inventory_ebay_item_id ON inventory_items(ebay_item_id);

CREATE TABLE IF NOT EXISTS social_post_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ebay_item_id TEXT,
    sku TEXT,
    title TEXT NOT NULL,
    item_url TEXT,
    image_url TEXT,
    caption TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    posted_at TEXT,
    platform TEXT NOT NULL,
    metricool_post_id TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_social_history_day ON social_post_history(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_social_history_ebay_item_id ON social_post_history(ebay_item_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_social_history_unique_scheduled_item
ON social_post_history(ebay_item_id, scheduled_at, platform)
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
            self._ensure_inventory_columns(connection)

    def _ensure_inventory_columns(self, connection: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(inventory_items)").fetchall()
        }
        if "image_urls" not in columns:
            connection.execute("ALTER TABLE inventory_items ADD COLUMN image_urls TEXT NOT NULL DEFAULT '[]'")
        if "listing_status" not in columns:
            connection.execute("ALTER TABLE inventory_items ADD COLUMN listing_status TEXT")

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
                    ebay_item_id, ebay_url, image_url, image_urls, category,
                    listing_status, item_specifics,
                    source, updated_at
                )
                VALUES (
                    :sku, :title, :description, :condition, :price, :currency, :quantity,
                    :ebay_item_id, :ebay_url, :image_url, :image_urls, :category,
                    :listing_status, :item_specifics,
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
                    image_urls = excluded.image_urls,
                    category = excluded.category,
                    listing_status = excluded.listing_status,
                    item_specifics = excluded.item_specifics,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def replace_ebay_inventory_snapshot(self, items: Iterable[InventoryItem]) -> int:
        current_items = list(items)
        count = self.upsert_items(current_items)
        active_item_ids = {
            item.ebay_item_id
            for item in current_items
            if item.ebay_item_id
        }
        active_skus = {item.sku for item in current_items if item.sku}

        with self.connect() as connection:
            if active_item_ids or active_skus:
                connection.execute(
                    """
                    UPDATE inventory_items
                    SET quantity = 0,
                        listing_status = 'ENDED',
                        updated_at = ?
                    WHERE (
                        sku LIKE 'EBAY-%'
                        OR source LIKE 'ebay-%'
                    )
                    AND (
                        ebay_item_id IS NULL
                        OR ebay_item_id = ''
                        OR ebay_item_id NOT IN ({item_placeholders})
                    )
                    AND sku NOT IN ({sku_placeholders})
                    """.format(
                        item_placeholders=", ".join("?" for _ in active_item_ids) or "''",
                        sku_placeholders=", ".join("?" for _ in active_skus) or "''",
                    ),
                    (
                        datetime.now(timezone.utc).isoformat(),
                        *sorted(active_item_ids),
                        *sorted(active_skus),
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE inventory_items
                    SET quantity = 0,
                        listing_status = 'ENDED',
                        updated_at = ?
                    WHERE sku LIKE 'EBAY-%'
                    OR source LIKE 'ebay-%'
                    """,
                    (datetime.now(timezone.utc).isoformat(),),
                )
        return count

    def get(self, sku: str) -> InventoryItem | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM inventory_items WHERE sku = ?",
                (sku,),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_by_ebay_item_id(self, ebay_item_id: str) -> InventoryItem | None:
        item_id = str(ebay_item_id or "").strip()
        if not item_id:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM inventory_items
                WHERE ebay_item_id = ?
                OR sku = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (item_id, f"EBAY-{item_id}"),
            ).fetchone()
        return self._from_row(row) if row else None

    def item_for_social_reference(self, reference: str) -> InventoryItem | None:
        social_reference = str(reference or "").strip()
        if not social_reference:
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT ebay_item_id, sku
                FROM social_post_history
                WHERE metricool_post_id = ?
                OR CAST(id AS TEXT) = ?
                OR ebay_item_id = ?
                OR sku = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (social_reference, social_reference, social_reference, social_reference),
            ).fetchone()
        if not row:
            return None
        if row["sku"]:
            item = self.get(str(row["sku"]))
            if item:
                return item
        if row["ebay_item_id"]:
            return self.get_by_ebay_item_id(str(row["ebay_item_id"]))
        return None

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
                AND image_url IS NOT NULL
                AND image_url != ''
                AND (
                    listing_status IS NULL
                    OR upper(listing_status) IN ('ACTIVE', 'IN_STOCK', 'PUBLISHED', 'LIVE')
                )
                ORDER BY updated_at DESC, quantity DESC
                LIMIT ?
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def social_post_count_for_day(self, scheduled_day: date | str) -> int:
        day = scheduled_day.isoformat() if isinstance(scheduled_day, date) else str(scheduled_day)[:10]
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM social_post_history
                WHERE substr(scheduled_at, 1, 10) = ?
                AND status NOT IN ('failed', 'cancelled', 'skipped')
                """,
                (day,),
            ).fetchone()
        return int(row["total"])

    def social_post_count_for_hour(self, scheduled_hour: str) -> int:
        hour = str(scheduled_hour)[:13]
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM social_post_history
                WHERE substr(scheduled_at, 1, 13) = ?
                AND status NOT IN ('failed', 'cancelled', 'skipped')
                """,
                (hour,),
            ).fetchone()
        return int(row["total"])

    def social_post_count_for_slot(self, scheduled_at: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM social_post_history
                WHERE scheduled_at = ?
                AND status NOT IN ('failed', 'cancelled', 'skipped')
                """,
                (scheduled_at,),
            ).fetchone()
        return int(row["total"])

    def recently_promoted_ebay_item_ids(
        self,
        cooldown_days: int = 14,
        now: datetime | None = None,
    ) -> set[str]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        threshold = (current - timedelta(days=max(0, cooldown_days))).strftime("%Y-%m-%d %H:%M:%S")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ebay_item_id
                FROM social_post_history
                WHERE ebay_item_id IS NOT NULL
                AND ebay_item_id != ''
                AND status NOT IN ('failed', 'cancelled', 'skipped')
                AND (
                    scheduled_at >= ?
                    OR posted_at >= ?
                )
                """,
                (threshold, threshold),
            ).fetchall()
        return {str(row["ebay_item_id"]) for row in rows}

    def last_social_post_at_by_ebay_item_id(self) -> dict[str, str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT ebay_item_id, MAX(COALESCE(posted_at, scheduled_at, created_at)) AS last_at
                FROM social_post_history
                WHERE ebay_item_id IS NOT NULL
                AND ebay_item_id != ''
                AND status NOT IN ('failed', 'cancelled', 'skipped')
                GROUP BY ebay_item_id
                """
            ).fetchall()
        return {str(row["ebay_item_id"]): str(row["last_at"]) for row in rows if row["last_at"]}

    def record_social_post(
        self,
        *,
        ebay_item_id: str | None,
        sku: str | None,
        title: str,
        item_url: str | None,
        image_url: str | None,
        caption: str,
        scheduled_at: str,
        platform: str,
        metricool_post_id: str | None = None,
        status: str = "scheduled",
        error_message: str | None = None,
    ) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO social_post_history (
                    ebay_item_id, sku, title, item_url, image_url, caption,
                    scheduled_at, posted_at, platform, metricool_post_id, status,
                    error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ebay_item_id, scheduled_at, platform) DO UPDATE SET
                    title = excluded.title,
                    item_url = excluded.item_url,
                    image_url = excluded.image_url,
                    caption = excluded.caption,
                    metricool_post_id = COALESCE(excluded.metricool_post_id, metricool_post_id),
                    status = excluded.status,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (
                    ebay_item_id,
                    sku,
                    title,
                    item_url,
                    image_url,
                    caption,
                    scheduled_at,
                    platform,
                    metricool_post_id,
                    status,
                    error_message,
                    now,
                    now,
                ),
            )
            row = connection.execute("SELECT last_insert_rowid() AS id").fetchone()
        return int(row["id"] or cursor.lastrowid or 0)

    def _to_row(self, item: InventoryItem) -> dict[str, object]:
        return {
            **item.model_dump(exclude={"item_specifics", "image_urls", "updated_at"}),
            "item_specifics": json.dumps(item.item_specifics, sort_keys=True),
            "image_urls": json.dumps(item.image_urls),
            "updated_at": item.updated_at.isoformat(),
        }

    def _from_row(self, row: sqlite3.Row) -> InventoryItem:
        data = dict(row)
        data["item_specifics"] = json.loads(data.get("item_specifics") or "{}")
        data["image_urls"] = json.loads(data.get("image_urls") or "[]")
        return InventoryItem.model_validate(data)
