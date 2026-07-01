import asyncio

import app.agents as agents_module
from app.models import CustomerQuestion, InventoryItem


class FakeRepository:
    def __init__(self, items):
        self.items = items

    def search(self, query, limit=8):
        query = query.lower()
        return [item for item in self.items if query in item.title.lower()][:limit]

    def get(self, sku):
        return next((item for item in self.items if item.sku == sku), None)


def test_customer_answer_returns_short_available_item_reply(monkeypatch):
    monkeypatch.setattr(
        agents_module,
        "get_repository",
        lambda: FakeRepository(
            [
                InventoryItem(
                    sku="EBAY-123",
                    ebay_item_id="123",
                    title="Samsung Galaxy S25 Blue 128GB",
                    condition="Open box",
                    price=525,
                    quantity=1,
                    ebay_url="https://www.ebay.com/itm/123",
                    listing_status="ACTIVE",
                )
            ]
        ),
    )

    answer = asyncio.run(
        agents_module.answer_customer_question(
            CustomerQuestion(message="Is the Samsung Galaxy S25 available?", channel="instagram")
        )
    )

    assert answer.needs_human is False
    assert answer.matched_items[0].ebay_item_id == "123"
    assert "Yes, this item is currently available." in answer.reply
    assert "https://www.ebay.com/itm/123" in answer.reply


def test_customer_answer_routes_unmatched_questions_to_human(monkeypatch):
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository([]))

    answer = asyncio.run(
        agents_module.answer_customer_question(
            CustomerQuestion(message="Do you have any Pixel phones?", channel="facebook")
        )
    )

    assert answer.needs_human is True
    assert answer.matched_items == []
    assert "browse current listings" in answer.reply
