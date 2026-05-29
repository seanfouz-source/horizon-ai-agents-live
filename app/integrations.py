from datetime import datetime, time, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.campaigns import request_campaign_media_url
from app.config import get_settings
from app.models import CustomerAnswer, SocialDraftBatch, SocialDraftRequest, SocialPost


POSTING_TIMEZONE = ZoneInfo("America/Chicago")
POSTING_MINIMUM_LEAD_TIME = timedelta(minutes=30)
METRICOOL_PUBLICATION_FORMAT = "%Y-%m-%d %H:%M:%S"
DAILY_POSTING_SLOTS = (
    time(7, 30),
    time(9, 0),
    time(10, 30),
    time(12, 0),
    time(13, 30),
    time(15, 0),
    time(16, 30),
    time(18, 0),
    time(19, 30),
    time(21, 0),
    time(22, 30),
)


def normalize_channel(value: object) -> str:
    channel = str(value or "unknown").strip().lower()
    aliases = {
        "fb": "facebook",
        "messenger": "facebook",
        "ig": "instagram",
        "insta": "instagram",
        "tik tok": "tiktok",
        "linked in": "linkedin",
    }
    return aliases.get(
        channel,
        channel if channel in {"facebook", "instagram", "tiktok", "linkedin", "whatsapp", "telegram", "web"} else "unknown",
    )


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
    publication_date_time = _metricool_publication_time(post, request)
    media_url = _metricool_media_url(post, request)
    facebook_groups = request.facebook_groups if post.platform == "facebook" and request.facebook_groups else None
    payload: dict[str, object] = {
        "brand_name": request.brand_name,
        "facebook": post.platform == "facebook",
        "instagram": post.platform == "instagram",
        "tiktok": post.platform == "tiktok",
        "linkedin": post.platform == "linkedin",
        "publish_to_facebook_groups": request.publish_to_facebook_groups if post.platform == "facebook" else None,
        "facebook_groups": facebook_groups,
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
        "linkedin": any(payload.get("linkedin") for payload in batch.metricool_payloads),
    }
    flat_media_url = first_payload.get("media_01")
    if platform_flags["tiktok"] and not _is_tiktok_supported_media(flat_media_url):
        flat_media_url = next(
            (
                payload.get("media_01")
                for payload in batch.metricool_payloads
                if payload.get("tiktok") and _is_tiktok_supported_media(payload.get("media_01"))
            ),
            flat_media_url,
        )
    facebook_groups = next(
        (payload.get("facebook_groups") for payload in batch.metricool_payloads if payload.get("facebook_groups")),
        None,
    )
    flat_fields = {
        "metricool_brand_name": first_payload.get("brand_name"),
        "metricool_facebook": platform_flags["facebook"],
        "metricool_instagram": platform_flags["instagram"],
        "metricool_tiktok": platform_flags["tiktok"],
        "metricool_linkedin": platform_flags["linkedin"],
        "metricool_publish_to_facebook_groups": any(
            payload.get("publish_to_facebook_groups") for payload in batch.metricool_payloads
        ),
        "metricool_facebook_groups": _csv_value(facebook_groups),
        "metricool_publication_date_time": first_payload.get("publication_date_time"),
        "metricool_post_content": first_payload.get("post_content"),
        "metricool_media_01": flat_media_url,
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
    return path.endswith((".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"))


def _csv_value(value: object) -> str | None:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip()) or None
    if value:
        return str(value)
    return None


def _metricool_media_url(post: SocialPost, request: SocialDraftRequest | None = None) -> str | None:
    media_url = post.media_url or request_campaign_media_url(request)
    if media_url:
        if post.platform != "tiktok" or _is_tiktok_supported_media(media_url):
            return media_url
        return generated_product_media_url(post.product_sku)
    return generated_product_media_url(post.product_sku)


def generated_product_media_url(sku: str | None, extension: str = "jpg") -> str | None:
    if not sku:
        return None
    clean_extension = extension.lower().lstrip(".")
    if clean_extension not in {"jpg", "jpeg", "png", "webp"}:
        clean_extension = "jpg"
    base_url = get_settings().public_base_url.rstrip("/")
    return f"{base_url}/media/products/{quote(sku, safe='')}.{clean_extension}"


def _metricool_publication_time(post: SocialPost, request: SocialDraftRequest) -> str:
    return _valid_metricool_publication_time(post.suggested_schedule) or request.publish_after or default_metricool_publication_time()


def _valid_metricool_publication_time(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        datetime.strptime(candidate, METRICOOL_PUBLICATION_FORMAT)
    except ValueError:
        return None
    return candidate


def default_metricool_publication_time(now: datetime | None = None) -> str:
    return default_metricool_publication_times(1, now=now)[0]


def default_metricool_publication_times(count: int, now: datetime | None = None) -> list[str]:
    if count <= 0:
        return []

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    local_now = current_time.astimezone(POSTING_TIMEZONE)
    minimum_time = local_now + POSTING_MINIMUM_LEAD_TIME
    publication_times: list[str] = []
    day_offset = 0

    while len(publication_times) < count:
        candidate_date = local_now.date() + timedelta(days=day_offset)
        for slot in DAILY_POSTING_SLOTS:
            candidate = datetime.combine(candidate_date, slot, tzinfo=POSTING_TIMEZONE)
            if candidate >= minimum_time:
                publication_times.append(candidate.strftime("%Y-%m-%d %H:%M:%S"))
                if len(publication_times) == count:
                    return publication_times
        day_offset += 1

    return publication_times
