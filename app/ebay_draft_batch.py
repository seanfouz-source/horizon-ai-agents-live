from __future__ import annotations

from dataclasses import asdict, dataclass


EBAY_INVENTORY_SHEET_BATCH_ID = "walmart-sheet-missing-2026-07-24"


@dataclass(frozen=True)
class EbayDraftSpec:
    sheet_row: int
    sku: str
    title: str
    quantity: int
    price: float
    category_id: str
    condition: str
    condition_description: str
    brand: str
    model: str
    color: str | None = None
    storage: str | None = None
    network: str | None = None
    connectivity: str | None = None
    catalog_query: str | None = None

    @property
    def aspects(self) -> dict[str, list[str]]:
        aspects: dict[str, list[str]] = {
            "Brand": [self.brand],
            "Model": [self.model],
        }
        if self.color:
            aspects["Color"] = [self.color]
        if self.storage:
            aspects["Storage Capacity"] = [self.storage]
        if self.network:
            aspects["Network"] = [self.network]
            aspects["Lock Status"] = ["Factory Unlocked"]
        if self.connectivity:
            aspects["Connectivity"] = [self.connectivity]
        if self.category_id == "111694":
            aspects["Type"] = ["Portable Speaker System"]
        return aspects

    @property
    def description(self) -> str:
        details = [self.title]
        if self.network:
            details.append(f"Network: {self.network}.")
        details.append(
            "A stock catalog image is included for product identification. "
            "Verify the exact physical condition, included accessories, and photos "
            "against the unit before publishing."
        )
        return " ".join(details)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["aspects"] = self.aspects
        payload["description"] = self.description
        return payload


def _spec(
    row: int,
    title: str,
    quantity: int,
    price: float,
    category_id: str,
    brand: str,
    model: str,
    *,
    color: str | None = None,
    storage: str | None = None,
    condition: str = "NEW_OTHER",
    condition_description: str = (
        "Open-box or like-new inventory. Verify the exact cosmetic condition and "
        "included accessories before publishing."
    ),
    network: str | None = None,
    connectivity: str | None = None,
    catalog_query: str | None = None,
) -> EbayDraftSpec:
    return EbayDraftSpec(
        sheet_row=row,
        sku=f"HW-WM-202607-{row:03d}",
        title=title[:80],
        quantity=quantity,
        price=price,
        category_id=category_id,
        condition=condition,
        condition_description=condition_description,
        brand=brand,
        model=model,
        color=color,
        storage=storage,
        network=network,
        connectivity=connectivity,
        catalog_query=catalog_query or title,
    )


def inventory_sheet_missing_drafts() -> list[EbayDraftSpec]:
    drafts: list[EbayDraftSpec] = []

    ipad_rows = [
        (2, "128 GB", "Blue", 20, 415),
        (3, "128 GB", "Silver", 1, 415),
        (4, "128 GB", "Yellow", 5, 415),
        (5, "128 GB", "Pink", 1, 415),
        (6, "256 GB", "Blue", 7, 455),
        (7, "256 GB", "Silver", 3, 455),
        (8, "256 GB", "Pink", 3, 455),
        (9, "512 GB", "Blue", 2, 495),
        (10, "512 GB", "Silver", 3, 495),
        (11, "512 GB", "Pink", 1, 495),
    ]
    for row, storage, color, quantity, price in ipad_rows:
        drafts.append(
            _spec(
                row,
                f"Apple iPad 11th Gen A16 {storage} Wi-Fi + Cellular - {color}",
                quantity,
                price,
                "171485",
                "Apple",
                "Apple iPad (A16)",
                color=color,
                storage=storage,
                connectivity="Wi-Fi + Cellular",
                catalog_query=f"Apple iPad A16 {storage} Cellular {color}",
            )
        )

    drafts.extend(
        [
            _spec(
                12,
                "Samsung Galaxy A36 5G 128GB Factory Unlocked",
                20,
                200,
                "9355",
                "Samsung",
                "Samsung Galaxy A36 5G",
                storage="128 GB",
                network="Unlocked",
            ),
            _spec(
                14,
                "Samsung Galaxy S25 128GB Factory Unlocked - Navy",
                5,
                475,
                "9355",
                "Samsung",
                "Samsung Galaxy S25",
                color="Navy",
                storage="128 GB",
                network="Unlocked",
            ),
            _spec(
                15,
                "Samsung Galaxy S25 128GB Factory Unlocked - Silver",
                5,
                475,
                "9355",
                "Samsung",
                "Samsung Galaxy S25",
                color="Silver",
                storage="128 GB",
                network="Unlocked",
            ),
            _spec(
                16,
                "Motorola One 5G Ace 64GB Factory Unlocked - New",
                20,
                100,
                "9355",
                "Motorola",
                "Motorola One 5G Ace",
                storage="64 GB",
                network="Unlocked",
                condition="NEW",
                condition_description="",
                catalog_query="Motorola One 5G Ace 64GB Unlocked",
            ),
            _spec(
                17,
                "Motorola Moto G 5G 128GB Factory Unlocked (2026)",
                10,
                150,
                "9355",
                "Motorola",
                "Motorola Moto G 5G (2026)",
                storage="128 GB",
                network="Unlocked",
            ),
        ]
    )

    refurbished_rows = [
        (18, "Samsung Galaxy S22 Ultra", "128 GB", "Black", 5, 390),
        (19, "Samsung Galaxy S22 Ultra", "128 GB", "Burgundy", 5, 390),
        (20, "Samsung Galaxy S22 Ultra", "128 GB", "Green", 5, 390),
        (21, "Samsung Galaxy S23 Ultra", "256 GB", "Black", 5, 490),
        (22, "Samsung Galaxy S23 Ultra", "256 GB", "Lavender", 5, 490),
        (23, "Samsung Galaxy S23 Ultra", "256 GB", "Cream", 5, 490),
        (24, "Samsung Galaxy S23 Ultra", "256 GB", "Green", 5, 490),
    ]
    for row, model, storage, color, quantity, price in refurbished_rows:
        drafts.append(
            _spec(
                row,
                f"{model} {storage} Factory Unlocked - {color} - Seller Refurbished",
                quantity,
                price,
                "9355",
                "Samsung",
                model,
                color=color,
                storage=storage,
                condition="SELLER_REFURBISHED",
                condition_description=(
                    "Seller-refurbished inventory. Verify the exact cosmetic grade, "
                    "battery health, and included accessories before publishing."
                ),
                network="Unlocked",
            )
        )

    s25_ultra_rows = [
        (25, "Titanium Silverblue"),
        (26, "Titanium Black"),
        (27, "Titanium Whitesilver"),
        (28, "Titanium Gray"),
    ]
    for row, color in s25_ultra_rows:
        drafts.append(
            _spec(
                row,
                f"Samsung Galaxy S25 Ultra 256GB Factory Unlocked - {color}",
                5,
                825,
                "9355",
                "Samsung",
                "Samsung Galaxy S25 Ultra",
                color=color,
                storage="256 GB",
                network="Unlocked",
            )
        )

    jbl_rows = [
        (29, "JBL Flip 6", "Black", 20, 80),
        (30, "JBL Flip 7", "Pink", 10, 115),
        (31, "JBL Flip 7", "Purple", 4, 115),
        (32, "JBL Go 4", "Black", 3, 50),
        (33, "JBL Go 4", "Red", 5, 50),
        (34, "JBL Go 4", "Purple", 5, 50),
        (35, "JBL Go 4", "Blue", 5, 50),
        (36, "JBL Go 4", "White", 5, 50),
        (37, "JBL Clip 5", "Black", 9, 60),
        (38, "JBL Go 3", "Gray", 6, 39),
        (39, "JBL Go 3", "Red", 3, 39),
        (40, "JBL Wind 3", "Black", 12, 49),
    ]
    for row, model, color, quantity, price in jbl_rows:
        drafts.append(
            _spec(
                row,
                f"{model} Portable Bluetooth Speaker - {color}",
                quantity,
                price,
                "111694",
                "JBL",
                model,
                color=color,
                connectivity="Bluetooth",
            )
        )

    iphone_rows = [
        (41, "Apple iPhone 13 Pro Max", "128 GB", "Graphite", 5, 475),
        (42, "Apple iPhone 13 Pro Max", "128 GB", "Gold", 5, 475),
        (43, "Apple iPhone 13 Pro Max", "128 GB", "Sierra Blue", 5, 475),
        (44, "Apple iPhone 13 Pro Max", "128 GB", "Silver", 5, 475),
        (45, "Apple iPhone 13 Pro Max", "128 GB", "Alpine Green", 5, 475),
        (46, "Apple iPhone 13 Pro Max", "256 GB", "Graphite", 5, 525),
        (47, "Apple iPhone 13 Pro Max", "256 GB", "Gold", 5, 525),
        (48, "Apple iPhone 13 Pro Max", "256 GB", "Sierra Blue", 5, 525),
        (49, "Apple iPhone 13 Pro Max", "256 GB", "Silver", 5, 525),
        (50, "Apple iPhone 13 Pro Max", "256 GB", "Alpine Green", 5, 525),
        (51, "Apple iPhone 14 Pro Max", "128 GB", "Space Black", 5, 590),
        (52, "Apple iPhone 14 Pro Max", "128 GB", "Silver", 5, 590),
        (53, "Apple iPhone 14 Pro Max", "128 GB", "Deep Purple", 5, 590),
        (55, "Apple iPhone 14 Pro Max", "256 GB", "Space Black", 5, 625),
        (56, "Apple iPhone 14 Pro Max", "256 GB", "Silver", 5, 625),
        (57, "Apple iPhone 14 Pro Max", "256 GB", "Gold", 5, 625),
        (58, "Apple iPhone 14 Pro Max", "256 GB", "Deep Purple", 5, 625),
        (59, "Apple iPhone 13", "256 GB", "Midnight", 10, 350),
        (60, "Apple iPhone 13", "256 GB", "Blue", 5, 350),
        (61, "Apple iPhone 13", "256 GB", "(PRODUCT)RED", 10, 350),
        (62, "Apple iPhone 13", "256 GB", "Starlight", 3, 350),
        (63, "Apple iPhone 14", "256 GB", "Midnight", 10, 425),
        (64, "Apple iPhone 14", "256 GB", "Blue", 5, 425),
        (65, "Apple iPhone 12 Pro Max", "128 GB", "Graphite", 5, 390),
        (66, "Apple iPhone 12 Pro Max", "128 GB", "Pacific Blue", 5, 390),
        (67, "Apple iPhone 12 Pro Max", "128 GB", "Silver", 5, 390),
        (68, "Apple iPhone 12 Pro Max", "128 GB", "Gold", 5, 390),
        (69, "Apple iPhone 12 Pro Max", "256 GB", "Graphite", 5, 425),
        (70, "Apple iPhone 12 Pro Max", "256 GB", "Pacific Blue", 5, 425),
        (71, "Apple iPhone 12 Pro Max", "256 GB", "Silver", 5, 425),
        (72, "Apple iPhone 12 Pro Max", "256 GB", "Gold", 5, 425),
    ]
    for row, model, storage, color, quantity, price in iphone_rows:
        drafts.append(
            _spec(
                row,
                f"{model} {storage} Factory Unlocked - {color}",
                quantity,
                price,
                "9355",
                "Apple",
                model,
                color=color,
                storage=storage,
                network="Unlocked",
            )
        )

    return sorted(drafts, key=lambda draft: draft.sheet_row)

