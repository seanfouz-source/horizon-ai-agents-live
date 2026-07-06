import json

from fastapi.testclient import TestClient

from app.models import CustomerAnswer


async def fake_refresh_inventory():
    return {"status": "ok"}


async def fake_answer_customer_question(question):
    assert question.message == "Do you have any iPhones?"
    assert question.channel == "instagram"
    assert question.user_id == "123456789"
    assert question.first_name == "Test"
    assert question.metadata["ebay_item_id"] == "123456789"
    assert question.metadata["conversation_id"] == "conv_12345"
    return CustomerAnswer(
        reply="Yes, we have iPhones available. Buy direct on eBay: https://www.ebay.com/itm/123456789",
        redirect_to_ebay=False,
        conversation_allowed=True,
        ebay_listing_url="https://www.ebay.com/itm/123456789",
        ebay_item_id="123456789",
    )


def manychat_zapier_payload():
    return {
        "message": "Do you have any iPhones?",
        "channel": "instagram",
        "user_id": "123456789",
        "subscriber_id": "123456789",
        "first_name": "Test",
        "conversation_id": "conv_12345",
        "post_id": "post_12345",
        "custom_fields": {
            "ebay_item_id": "123456789",
            "product_sku": "SKU-12345",
            "ebay_url": "https://www.ebay.com/itm/123456789",
            "metricool_post_id": "metricool_12345",
            "history_id": "hist_12345",
        },
    }


def test_zapier_customer_question_accepts_stringified_json_payload(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", None)
    monkeypatch.setattr(main_module, "_refresh_inventory_for_social_posts", fake_refresh_inventory)
    monkeypatch.setattr(main_module, "answer_customer_question", fake_answer_customer_question)

    client = TestClient(main_module.app)
    response = client.post("/webhooks/zapier/customer-question", json=json.dumps(manychat_zapier_payload()))

    assert response.status_code == 200
    body = response.json()
    assert body["reply"].startswith("Yes, we have iPhones available.")
    assert body["redirect_to_ebay"] is False
    assert body["conversation_allowed"] is True
    assert body["ebay_listing_url"] == "https://www.ebay.com/itm/123456789"
    assert body["ebay_item_id"] == "123456789"
    assert body["recommended_items"] == []


def test_zapier_customer_question_accepts_data_wrapped_payload(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", None)
    monkeypatch.setattr(main_module, "_refresh_inventory_for_social_posts", fake_refresh_inventory)
    monkeypatch.setattr(main_module, "answer_customer_question", fake_answer_customer_question)

    client = TestClient(main_module.app)
    response = client.post(
        "/webhooks/zapier/customer-question",
        json={"data": json.dumps(manychat_zapier_payload())},
    )

    assert response.status_code == 200
    assert response.json()["reply"].startswith("Yes, we have iPhones available.")
