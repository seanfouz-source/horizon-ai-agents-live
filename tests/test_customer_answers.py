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

    def get_by_ebay_item_id(self, ebay_item_id):
        return next((item for item in self.items if item.ebay_item_id == ebay_item_id), None)

    def item_for_social_reference(self, reference):
        return next((item for item in self.items if item.item_specifics.get("Post ID") == reference), None)

    def all_promotable(self, limit=12):
        return [item for item in self.items if item.quantity > 0][:limit]


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


def test_customer_answer_keeps_unmatched_presale_questions_in_messenger(monkeypatch):
    monkeypatch.setattr(agents_module, "get_repository", lambda: FakeRepository([]))

    answer = asyncio.run(
        agents_module.answer_customer_question(
            CustomerQuestion(message="Do you have any Pixel phones?", channel="facebook")
        )
    )

    assert answer.needs_human is False
    assert answer.conversation_allowed is True
    assert answer.matched_items == []
    assert "Which carrier, model, storage size, color, and budget range" in answer.reply


def test_customer_answer_uses_post_context_for_item_specific_question(monkeypatch):
    monkeypatch.setattr(
        agents_module,
        "get_repository",
        lambda: FakeRepository(
            [
                InventoryItem(
                    sku="EBAY-456",
                    ebay_item_id="456",
                    title="Apple iPhone 15 Pro Max 256GB Blue Unlocked",
                    condition="Open box",
                    price=799,
                    quantity=1,
                    ebay_url="https://www.ebay.com/itm/456",
                    listing_status="ACTIVE",
                    item_specifics={"Lock Status": "Unlocked", "Storage Capacity": "256 GB", "Post ID": "fb-post-1"},
                )
            ]
        ),
    )

    answer = asyncio.run(
        agents_module.answer_customer_question(
            CustomerQuestion(
                message="Is this unlocked?",
                channel="facebook",
                metadata={"post_id": "fb-post-1"},
            )
        )
    )

    assert answer.needs_human is False
    assert answer.redirect_to_ebay is False
    assert answer.ebay_item_id == "456"
    assert answer.social_post_id == "fb-post-1"
    assert "Unlocked" in answer.reply
    assert "https://www.ebay.com/itm/456" in answer.reply


def test_customer_answer_redirects_offers_to_ebay(monkeypatch):
    monkeypatch.setattr(
        agents_module,
        "get_repository",
        lambda: FakeRepository(
            [
                InventoryItem(
                    sku="EBAY-789",
                    ebay_item_id="789",
                    title="Samsung Galaxy Z Fold5 512GB",
                    condition="Open box",
                    price=900,
                    quantity=1,
                    ebay_url="https://www.ebay.com/itm/789",
                    listing_status="ACTIVE",
                )
            ]
        ),
    )

    answer = asyncio.run(
        agents_module.answer_customer_question(
            CustomerQuestion(message="Can you do a lower price or offer?", metadata={"ebay_item_id": "789"})
        )
    )

    assert answer.redirect_to_ebay is True
    assert answer.conversation_allowed is False
    assert answer.needs_human is False
    assert "Pricing and offers are handled through eBay" in answer.reply
    assert "https://www.ebay.com/itm/789" in answer.reply


def test_customer_answer_redirects_order_support_to_ebay_messages(monkeypatch):
    monkeypatch.setattr(
        agents_module,
        "get_repository",
        lambda: FakeRepository(
            [
                InventoryItem(
                    sku="EBAY-321",
                    ebay_item_id="321",
                    title="Motorola Moto G 5G",
                    quantity=1,
                    ebay_url="https://www.ebay.com/itm/321",
                    listing_status="ACTIVE",
                )
            ]
        ),
    )

    answer = asyncio.run(
        agents_module.answer_customer_question(
            CustomerQuestion(message="What is my order tracking?", metadata={"ebay_item_id": "321"})
        )
    )

    assert answer.redirect_to_ebay is True
    assert answer.needs_human is True
    assert "through eBay messages" in answer.reply


def test_customer_answer_handles_return_policy_as_presale_question(monkeypatch):
    monkeypatch.setattr(
        agents_module,
        "get_repository",
        lambda: FakeRepository(
            [
                InventoryItem(
                    sku="EBAY-654",
                    ebay_item_id="654",
                    title="Apple iPhone 14 128GB",
                    quantity=1,
                    ebay_url="https://www.ebay.com/itm/654",
                    listing_status="ACTIVE",
                    item_specifics={"Return Policy": "30 day returns accepted"},
                )
            ]
        ),
    )

    answer = asyncio.run(
        agents_module.answer_customer_question(
            CustomerQuestion(message="What is the return policy?", metadata={"ebay_item_id": "654"})
        )
    )

    assert answer.redirect_to_ebay is False
    assert answer.needs_human is False
    assert "30 day returns accepted" in answer.reply
    assert "https://www.ebay.com/itm/654" in answer.reply


def test_customer_answer_recommends_matching_inventory(monkeypatch):
    monkeypatch.setattr(
        agents_module,
        "get_repository",
        lambda: FakeRepository(
            [
                InventoryItem(
                    sku="EBAY-1",
                    ebay_item_id="1",
                    title="Apple iPhone 13 Blue 128GB Unlocked",
                    condition="Open box",
                    price=350,
                    quantity=1,
                    ebay_url="https://www.ebay.com/itm/1",
                    listing_status="ACTIVE",
                ),
                InventoryItem(
                    sku="EBAY-2",
                    ebay_item_id="2",
                    title="Apple iPhone 15 Black 256GB Unlocked",
                    condition="Open box",
                    price=725,
                    quantity=1,
                    ebay_url="https://www.ebay.com/itm/2",
                    listing_status="ACTIVE",
                ),
            ]
        ),
    )

    answer = asyncio.run(
        agents_module.answer_customer_question(
            CustomerQuestion(message="What is your cheapest iPhone under $400?", channel="instagram")
        )
    )

    assert answer.matched_items[0].ebay_item_id == "1"
    assert "Apple iPhone 13 Blue 128GB Unlocked" in answer.reply
    assert "https://www.ebay.com/itm/1" in answer.reply
