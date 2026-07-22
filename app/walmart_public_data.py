from typing import Final


# Product identifiers are limited to exact model/storage/color variants backed by
# public product records. Walmart's SPEC search is still required before any offer
# is submitted, so a stale or non-catalog identifier remains safely blocked.
PUBLIC_CATALOG_IDENTIFIERS: Final[dict[str, dict[str, str]]] = {
    "EBAY-366419905577": {
        "product_id_type": "UPC",
        "product_id": "887276429649",
        "source_url": "https://device.report/samsung/sm-n986u",
    },
    "EBAY-366425165401-068916ab9b": {
        "product_id_type": "UPC",
        "product_id": "195949561283",
        "source_url": (
            "https://www.nfm.com/apple-watch-series-10-gps-cellular-46mm-rose-gold-"
            "aluminum-case-with-light-blush-sport-band--sm-67155564/67155564.html"
        ),
    },
    "EBAY-366429558026-fc99d52961": {
        "product_id_type": "UPC",
        "product_id": "195949045974",
        "source_url": "https://www.ebay.com/itm/306774293606",
    },
    "EBAY-366429621102-5cf23d703e": {
        "product_id_type": "UPC",
        "product_id": "037635502944",
        "source_url": "https://www.walmart.com/ip/18715918638",
    },
    "EBAY-366429653088-5cb8aeb403": {
        "product_id_type": "UPC",
        "product_id": "195949721496",
        "source_url": "https://www.ebay.com/itm/326888042094",
    },
    "EBAY-366436027346-560edf95c0": {
        "product_id_type": "UPC",
        "product_id": "887276766539",
        "source_url": (
            "https://image-us.samsung.com/SamsungUS/samsungbusiness/solutions/industries/"
            "government/msrp-price-sheets/01242025/Samsung-HHP-MSRP-Price-File-Dec-2024.pdf"
        ),
    },
    "EBAY-366436027346-76da69e34e": {
        "product_id_type": "UPC",
        "product_id": "887276766515",
        "source_url": (
            "https://image-us.samsung.com/SamsungUS/samsungbusiness/solutions/industries/"
            "government/msrp-price-sheets/01242025/Samsung-HHP-MSRP-Price-File-Dec-2024.pdf"
        ),
    },
    "EBAY-366436069804-684d70474d": {
        "product_id_type": "UPC",
        "product_id": "887276765808",
        "source_url": (
            "https://image-us.samsung.com/SamsungUS/samsungbusiness/solutions/industries/"
            "government/msrp-price-sheets/01242025/Samsung-HHP-MSRP-Price-File-Dec-2024.pdf"
        ),
    },
}
