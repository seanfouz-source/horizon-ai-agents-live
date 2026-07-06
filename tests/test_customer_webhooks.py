import json

import httpx
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


def facebook_comment_payload():
    return {
        "message": "Do you have any iPhones?",
        "channel": "facebook",
        "commenter_id": "customer-123",
        "user_id": "customer-123",
        "subscriber_id": "customer-123",
        "first_name": "Customer",
        "post_id": "post_12345",
        "comment_id": "comment_12345",
        "permalink_url": "https://facebook.com/post/comment",
    }


async def fake_answer_facebook_comment(question):
    assert question.message == "Do you have any iPhones?"
    assert question.channel == "facebook"
    assert question.user_id == "customer-123"
    assert question.first_name == "Customer"
    assert question.metadata["comment_id"] == "comment_12345"
    return CustomerAnswer(
        reply="Yes, we have iPhones available. Buy direct on eBay: https://www.ebay.com/itm/123456789",
        redirect_to_ebay=False,
        conversation_allowed=True,
        ebay_listing_url="https://www.ebay.com/itm/123456789",
        ebay_item_id="123456789",
    )


class FakeFacebookAsyncClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, data):
        self.calls.append((url, data))
        request = httpx.Request("POST", url)
        return httpx.Response(200, json={"id": "reply_12345"}, request=request)


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


def test_facebook_comment_auto_reply_posts_threaded_reply(monkeypatch):
    import app.main as main_module

    FakeFacebookAsyncClient.calls = []
    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", None)
    monkeypatch.setattr(main_module.settings, "facebook_page_access_token", "page-token")
    monkeypatch.setattr(main_module.settings, "facebook_graph_api_version", "v20.0")
    monkeypatch.setattr(main_module.settings, "facebook_page_name", "Horizon Wireless")
    monkeypatch.setattr(main_module, "_refresh_inventory_for_social_posts", fake_refresh_inventory)
    monkeypatch.setattr(main_module, "answer_customer_question", fake_answer_facebook_comment)
    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeFacebookAsyncClient)

    client = TestClient(main_module.app)
    response = client.post("/webhooks/zapier/facebook-comment-auto-reply", json=facebook_comment_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "posted"
    assert body["reply"].startswith("Yes, we have iPhones available.")
    assert body["facebook_comment_reply_id"] == "reply_12345"
    assert FakeFacebookAsyncClient.calls == [
        (
            "https://graph.facebook.com/v20.0/comment_12345/comments",
            {
                "message": "Yes, we have iPhones available. Buy direct on eBay: https://www.ebay.com/itm/123456789",
                "access_token": "page-token",
            },
        )
    ]


def test_facebook_comment_auto_reply_skips_page_self_comment(monkeypatch):
    import app.main as main_module

    FakeFacebookAsyncClient.calls = []
    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", None)
    monkeypatch.setattr(main_module.settings, "facebook_page_name", "Horizon Wireless")

    payload = facebook_comment_payload()
    payload["first_name"] = "Horizon Wireless"

    client = TestClient(main_module.app)
    response = client.post("/webhooks/zapier/facebook-comment-auto-reply", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
    assert body["facebook_comment_reply_status"] == "skipped"
    assert FakeFacebookAsyncClient.calls == []


def test_facebook_comment_auto_reply_requires_page_token(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module.settings, "webhook_shared_secret", None)
    monkeypatch.setattr(main_module.settings, "facebook_page_access_token", None)
    monkeypatch.setattr(main_module.settings, "facebook_page_name", "Horizon Wireless")
    monkeypatch.setattr(main_module, "_refresh_inventory_for_social_posts", fake_refresh_inventory)
    monkeypatch.setattr(main_module, "answer_customer_question", fake_answer_facebook_comment)

    client = TestClient(main_module.app)
    response = client.post("/webhooks/zapier/facebook-comment-auto-reply", json=facebook_comment_payload())

    assert response.status_code == 503
    assert response.json()["detail"] == "FACEBOOK_PAGE_ACCESS_TOKEN is not configured."
