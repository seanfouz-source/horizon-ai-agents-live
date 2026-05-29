import asyncio

import app.agents as agents_module
from app.models import CustomerAnswer, GroupReplyRequest, InventoryItem


async def fake_answer_customer_question(question):
    return CustomerAnswer(
        reply="Yes, we have a Samsung Galaxy Z Flip available. View it on eBay: https://www.ebay.com/itm/366436069804",
        channel=question.channel,
        matched_items=[
            InventoryItem(
                sku="EBAY-366436069804",
                title="Samsung Galaxy Z Flip 5 - Black 256GB & 512GB (Unlocked)",
                price=450.0,
                quantity=1,
                ebay_url="https://www.ebay.com/itm/366436069804",
            )
        ],
        needs_human=False,
    )


def test_group_comment_reply_requires_manual_review(monkeypatch):
    seen = {}

    async def fake_answer(question):
        seen["message"] = question.message
        seen["metadata"] = question.metadata
        return await fake_answer_customer_question(question)

    monkeypatch.setattr(agents_module, "answer_customer_question", fake_answer)

    draft = asyncio.run(
        agents_module.draft_group_reply(
            GroupReplyRequest(
                message="Do you have any Galaxy Z Flip phones?",
                group_name="Phone Resellers",
                interaction_type="group_comment",
            )
        )
    )

    assert draft.can_auto_send is False
    assert draft.manual_review_required is True
    assert "Draft only" in draft.compliance_notes
    assert draft.matched_items[0].sku == "EBAY-366436069804"
    assert seen["message"] == "Do you have any Galaxy Z Flip phones?"
    assert seen["metadata"]["group_name"] == "Phone Resellers"


def test_opted_in_page_dm_can_auto_send(monkeypatch):
    monkeypatch.setattr(agents_module, "answer_customer_question", fake_answer_customer_question)

    draft = asyncio.run(
        agents_module.draft_group_reply(
            GroupReplyRequest(
                message="Can you send me the eBay link?",
                interaction_type="page_dm",
                user_opted_in=True,
            )
        )
    )

    assert draft.can_auto_send is True
    assert draft.manual_review_required is False
    assert "supported inbound DM" in draft.compliance_notes
