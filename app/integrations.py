from datetime import datetime, time, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models import CustomerAnswer, SocialDraftBatch, SocialDraftRequest, SocialPost


BUSY_POSTING_TIMEZONE = ZoneInfo("America/Chicago")
BUSY_POSTING_SLOTS = {
    0: (time(12, 30), time(15, 30)),
    1: (time(12, 30), time(14, 30), time(16, 30)),
    2: (time(12, 30), time(14, 30), time(16, 30)),
    3: (time(12, 30), time(14, 30), time(16, 30)),
    4: (time(14, 30), time(16, 30)),
}


def normalize_channel(value: object) -> str:
    channel = str(value or "unknown").strip().lower()
    aliases = {
        "fb": "facebook",
        "messenger": "facebook",
        "ig": "instagram",
        "insta": "instagram",
        "tik tok": "tiktok",
    }
    return aliases.get(channel, channel if channel in {"facebook", "instagram", "tiktok", "whatsapp", "telegram", "web"} else "unknown")


def extract_customer_message(payload: dict[str, object]) -> str:
    for key in ("message", "text", "question", "query", "last_input", "last_message", "user_message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    custom_fields = payload.get("custom_fields")
    if isinstance(custom_fields, dict):
        for key in ("message", "question", "last_input"):
            value = custom_fields.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return ""


def manychat_dynamic_response(answer: CustomerAnswer) -> dict[str, object]:
    content: dict[str, object] = {
        "messages": [
            {
                "type": "text",
                "text": answer.reply[:1900],
            }
        ],
        "actions": [],
        "quick_replies": [],
    }
    if answer.channel in {"instagram", "whatsapp", "telegram"}:
        content["type"] = answer.channel
    return {"version": "v2", "content": content}


def metricool_payload(post: SocialPost, request: SocialDraftRequest) -> dict[str, object]:
    publication_date_time = post.suggested_schedule or request.publish_after or default_metricool_publication_time()
    media_url = post.media_url or generated_product_media_url(post.product_sku)
    payload: dict[str, object] = {
        "brand_name": request.brand_name,
        "facebook": post.platform == "facebook",
        "instagram": post.platform == "instagram",
        "tiktok": post.platform == "tiktok",
        "publication_date_time": publication_date_time,
        "post_content": post.text,
        "media_01": media_url,
        "as_draft": request.as_draft,
        "auto_publish": request.auto_publish,
        "post_type": "POST",
        "social_post_type": post.post_type,
        "product_sku": post.product_sku,
        "product_title": post.product_title,
        "ebay_url": post.ebay_url,
    }
    return {key: value for key, value in payload.items() if value is not None}


def zapier_social_drafts_response(batch: SocialDraftBatch) -> dict[str, object]:
    response = batch.model_dump()
    first_payload = batch.metricool_payloads[0] if batch.metricool_payloads else {}
    if not first_payload:
        return response

    platform_flags = {
        "facebook": any(payload.get("facebook") for payload in batch.metricool_payloads),
        "instagram": any(payload.get("instagram") and payload.get("media_01") for payload in batch.metricool_payloads),
        "tiktok": any(
            payload.get("tiktok") and _is_tiktok_supported_media(payload.get("media_01"))
            for payload in batch.metricool_payloads
        ),
    }
    flat_fields = {
        "metricool_brand_name": first_payload.get("brand_name"),
        "metricool_facebook": platform_flags["facebook"],
        "metricool_instagram": platform_flags["instagram"],
        "metricool_tiktok": platform_flags["tiktok"],
        "metricool_publication_date_time": first_payload.get("publication_date_time"),
        "metricool_post_content": first_payload.get("post_content"),
        "metricool_media_01": first_payload.get("media_01"),
        "metricool_as_draft": first_payload.get("as_draft"),
        "metricool_auto_publish": first_payload.get("auto_publish"),
        "metricool_post_type": first_payload.get("post_type"),
        "metricool_social_post_type": first_payload.get("social_post_type"),
        "metricool_product_sku": first_payload.get("product_sku"),
        "metricool_product_title": first_payload.get("product_title"),
        "metricool_ebay_url": first_payload.get("ebay_url"),
        "publicationDate": first_payload.get("publication_date_time"),
    }
    response.update({key: value for key, value in flat_fields.items() if value is not None})
    return response


def _is_video_media(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return value.lower().split("?")[0].endswith((".mp4", ".mov", ".webm"))


def _is_tiktok_supported_media(value: object) -> bool:
    if not isinstance(value, str):
        return False
    path = value.lower().split("?")[0]
    return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"))


def generated_product_media_url(sku: str | None) -> str | None:
    if not sku:
        return None
    base_url = get_settings().public_base_url.rstrip("/")
    return f"{base_url}/media/products/{quote(sku, safe='')}.png"


def default_metricool_publication_time(now: datetime | None = None) -> str:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    local_now = current_time.astimezone(BUSY_POSTING_TIMEZONE)
    minimum_time = local_now + timedelta(minutes=30)
    for day_offset in range(8):
        candidate_date = local_now.date() + timedelta(days=day_offset)
        slots = BUSY_POSTING_SLOTS.get(candidate_date.weekday(), ())
        for slot in slots:
            candidate = datetime.combine(candidate_date, slot, tzinfo=BUSY_POSTING_TIMEZONE)
            if candidate > minimum_time:
                return candidate.strftime("%Y-%m-%d %H:%M:%S")

    fallback = minimum_time + timedelta(hours=1)
    return fallback.strftime("%Y-%m-%d %H:%M:%S")
