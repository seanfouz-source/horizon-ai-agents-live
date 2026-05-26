from app.ebay_store_page import parse_store_page


def test_parse_store_page_finds_listing_card():
    html = """
    <li class="s-item">
      <a class="s-item__link" href="https://www.ebay.com/itm/Demo-Keyboard/123456789012?hash=abc">
        <img src="https://i.ebayimg.com/images/demo.jpg" alt="Demo Gaming Keyboard">
        <span class="s-item__title">Demo Gaming Keyboard</span>
      </a>
      <span class="s-item__price">$44.50</span>
    </li>
    """

    items = parse_store_page(html, "https://www.ebay.com/str/demo")

    assert len(items) == 1
    assert items[0].sku == "EBAY-123456789012"
    assert items[0].title == "Demo Gaming Keyboard"
    assert items[0].price == 44.5
    assert items[0].quantity == 1
    assert items[0].source == "ebay-store-page"


def test_parse_store_page_finds_storefront_state_cards():
    html = """
    <script>
    window.__state__ = {
      "LISTINGS_MODULE": {
        "_type": "ContainerModule",
        "containers": [{
          "_type": "CardContainer",
          "cards": [{
            "_type": "StoreFrontItemCard",
            "listingId": "366436027346",
            "action": {
              "_type": "Action",
              "URL": "https://www.ebay.com/itm/366436027346?hash=item55514a0bd2:g:M6YAAeSw5AhqFgxb"
            },
            "title": {
              "_type": "TextualDisplay",
              "textSpans": [{"_type": "TextSpan", "text": "Samsung Galaxy Z Fold5"}]
            },
            "image": {
              "_type": "Image",
              "URL": "https://i.ebayimg.com/images/g/M6YAAeSw5AhqFgxb/s-l300.jpg"
            },
            "displayPrice": {
              "_type": "TextualDisplayValue",
              "value": {"value": 675, "currency": "USD"},
              "textSpans": [{"_type": "TextSpan", "text": "$675.00"}]
            }
          }]
        }]
      }
    };
    </script>
    """

    items = parse_store_page(html, "https://ebay.us/m/GDmaKw")

    assert len(items) == 1
    assert items[0].sku == "EBAY-366436027346"
    assert items[0].title == "Samsung Galaxy Z Fold5"
    assert items[0].price == 675.0
    assert items[0].image_url == "https://i.ebayimg.com/images/g/M6YAAeSw5AhqFgxb/s-l300.jpg"
