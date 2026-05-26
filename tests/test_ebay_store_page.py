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
