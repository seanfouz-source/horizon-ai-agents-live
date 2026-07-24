from __future__ import annotations

from dataclasses import asdict, dataclass


EBAY_INVENTORY_SHEET_BATCH_ID = "walmart-sheet-missing-2026-07-24"

APPLE_IPAD_IMAGE = (
    "https://store.storeimages.cdn-apple.com/1/as-images.apple.com/is/"
    "ipad-finish-select-202503-{color}-wifi?wid=1200&hei=1200&fmt=jpeg&qlt=90"
)
MANUAL_DRAFT_IMAGES: dict[int, tuple[tuple[str, ...], str]] = {
    2: ((APPLE_IPAD_IMAGE.format(color="blue"),), "APPLE_OFFICIAL"),
    3: ((APPLE_IPAD_IMAGE.format(color="silver"),), "APPLE_OFFICIAL"),
    4: ((APPLE_IPAD_IMAGE.format(color="yellow"),), "APPLE_OFFICIAL"),
    5: ((APPLE_IPAD_IMAGE.format(color="pink"),), "APPLE_OFFICIAL"),
    6: ((APPLE_IPAD_IMAGE.format(color="blue"),), "APPLE_OFFICIAL"),
    7: ((APPLE_IPAD_IMAGE.format(color="silver"),), "APPLE_OFFICIAL"),
    8: ((APPLE_IPAD_IMAGE.format(color="pink"),), "APPLE_OFFICIAL"),
    9: ((APPLE_IPAD_IMAGE.format(color="blue"),), "APPLE_OFFICIAL"),
    10: ((APPLE_IPAD_IMAGE.format(color="silver"),), "APPLE_OFFICIAL"),
    11: ((APPLE_IPAD_IMAGE.format(color="pink"),), "APPLE_OFFICIAL"),
    12: (
        (
            "https://images.samsung.com/is/image/samsung/p6pim/us/"
            "sm-a366uzkaxaa/gallery/us-galaxy-a36-5g-sm-a366-577014-"
            "sm-a366uzkaxaa-550736693",
        ),
        "SAMSUNG_OFFICIAL",
    ),
    14: (
        (
            "https://images.samsung.com/is/image/samsung/p6pim/us/"
            "sm-s931udbaxaa/gallery/us-galaxy-s25-s931-551170-"
            "sm-s931udbaxaa-547068504",
        ),
        "SAMSUNG_OFFICIAL",
    ),
    15: (
        (
            "https://images.samsung.com/is/image/samsung/p6pim/us/"
            "sm-s931uzsaxaa/gallery/us-galaxy-s25-s931-551170-"
            "sm-s931uzsaxaa-547069587",
        ),
        "SAMSUNG_OFFICIAL",
    ),
    17: (
        (
            "https://p1-ofp.static.pub/medias/"
            "28260394073_Moto_g_2026_Slipstream_202603060441051774329127205.png",
        ),
        "MOTOROLA_OFFICIAL",
    ),
    19: (
        ("https://i.ebayimg.com/images/g/NPEAAOSwiFJj4pM1/s-l1200.jpg",),
        "EBAY_CATALOG_MODEL_COLOR",
    ),
    20: (
        ("https://i.ebayimg.com/images/g/G~kAAOSwz6Nj4pNZ/s-l1600.jpg",),
        "EBAY_CATALOG_MODEL_COLOR",
    ),
    25: (
        (
            "https://images.samsung.com/is/image/samsung/p6pim/us/2501/gallery/"
            "us-galaxy-s25-s938-sm-s938uzbaxaa-544887986",
        ),
        "SAMSUNG_OFFICIAL",
    ),
    26: (
        (
            "https://images.samsung.com/is/image/samsung/p6pim/us/2501/gallery/"
            "us-galaxy-s25-s938-sm-s938uzkaxaa-544888023",
        ),
        "SAMSUNG_OFFICIAL",
    ),
    27: (
        (
            "https://images.samsung.com/is/image/samsung/p6pim/us/2501/gallery/"
            "us-galaxy-s25-s938-sm-s938uzsaxaa-544888060",
        ),
        "SAMSUNG_OFFICIAL",
    ),
    28: (
        (
            "https://images.samsung.com/is/image/samsung/p6pim/us/2501/gallery/"
            "us-galaxy-s25-s938-sm-s938uztaxaa-544888097",
        ),
        "SAMSUNG_OFFICIAL",
    ),
    29: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dw4e91d6eb/"
            "1_JBL_FLIP6_HERO_BLACK_29391_x2.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    30: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dw3b5c0498/"
            "JBL_FLIP_7_HERO_PINK_068_x1.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    31: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dwa1a4a194/"
            "JBL_FLIP_7_HERO_PURPLE_079_x2.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    32: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dw96fc93ec/"
            "JBL_GO_4_HERO_BLACK_48156_x4.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    33: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dw47165508/"
            "JBL_GO_4_FRONT_RED_48185_x1.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    34: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dwb12e221d/"
            "JBL_GO_4_FRONT_PURPLE_48186_x1.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    35: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dw15debaca/"
            "JBL_GO_4_HERO_BLUE_48170_x6.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    36: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dw9a696ae8/"
            "JBL_GO_4_FRONT_White_48184_x1.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    37: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dwf4fb1f8d/"
            "JBL_CLIP_5_HERO_BLACK_48128_x6.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    40: (
        (
            "https://www.jbl.com/dw/image/v2/BFND_PRD/on/demandware.static/-/"
            "Sites-masterCatalog_Harman/default/dw6d0063be/"
            "JBL_WIND_3_HERO_MOUNT_35254_x1.png?sh=535&sw=535",
        ),
        "JBL_OFFICIAL",
    ),
    43: (
        ("https://i.ebayimg.com/images/g/Wx4AAOSwSfljmu4X/s-l1600.jpg",),
        "EBAY_CATALOG_MODEL_COLOR",
    ),
    46: (
        ("https://i.ebayimg.com/images/g/GWwAAOSwAi1jmwM3/s-l1600.jpg",),
        "EBAY_CATALOG_MODEL_COLOR",
    ),
    67: (
        ("https://i.ebayimg.com/images/g/WYwAAOSwaRRiyqG3/s-l640.jpg",),
        "EBAY_CATALOG_MODEL_COLOR",
    ),
    72: (
        ("https://i.ebayimg.com/images/g/dLcAAOSw57pjIcWk/s-l640.jpg",),
        "EBAY_CATALOG_MODEL_COLOR",
    ),
}


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
    manual_image_urls: tuple[str, ...] = ()
    manual_image_source: str | None = None

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
    manual_image_urls, manual_image_source = MANUAL_DRAFT_IMAGES.get(
        row,
        ((), None),
    )
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
        manual_image_urls=manual_image_urls,
        manual_image_source=manual_image_source,
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
