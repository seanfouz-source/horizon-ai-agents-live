from datetime import datetime, time, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.campaigns import request_campaign_media_url
from app.config import get_settings
from app.models import CustomerAnswer, SocialDraftBatch, SocialDraftRequest, SocialPost


POSTING_TIMEZONE = ZoneInfo("America/Chicago")
POSTING_MINIMUM_LEAD_TIME = timedelta(minutes=30)
METRICOOL_PUBLICATION_FORMAT = "%Y-%m-%d %H:%M:%S"
TIKTOK_DAILY_POST_CAP_NOTE = "TikTok auto-publish disabled to stay under the daily TikTok API post cap."
DEFAULT_DAILY_POSTING_SLOTS = (time(9, 0), time(18, 0))


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
    facebook_enabled = _platform_enabled(post, request, "facebook")
    instagram_enabled = _platform_enabled(post, request, "instagram")
    tiktok_enabled = _platform_enabled(post, request, "tiktok")
    linkedin_enabled = _platform_enabled(post, request, "linkedin")
    facebook_groups = request.facebook_groups if facebook_enabled and request.facebook_groups else None
    payload: dict[str, object] = {
        "brand_name": request.brand_name,
        "facebook": facebook_enabled,
        "instagram": instagram_enabled,
        "tiktok": tiktok_enabled,
        "linkedin": linkedin_enabled,
        "publish_to_facebook_groups": request.publish_to_facebook_groups if facebook_enabled else None,
        "facebook_groups": facebook_groups,
        "publication_date_time": publication_date_time,
        "publicationDate": publication_date_time,
        "post_content": post.text,
        "media_01": media_url,
        "as_draft": request.as_draft,
        "draft": request.as_draft,
        "auto_publish": request.auto_publish,
        "post_type": "POST",
        "social_post_type": post.post_type,
        "product_sku": post.product_sku,
        "product_title": post.product_title,
        "ebay_url": post.ebay_url,
        "buy_url": post.ebay_url,
        "link_url": post.ebay_url,
        "facebook_link_url": post.ebay_url,
    }
    return {key: value for key, value in payload.items() if value is not None}


def apply_tiktok_daily_post_cap(payloads: list[dict[str, object]], daily_cap: int) -> int:
    """Disable extra TikTok placements before Metricool asks TikTok to publish them."""
    if daily_cap < 0:
        daily_cap = 0

    scheduled_counts: dict[str, int] = {}
    suppressed_count = 0
    for payload in payloads:
        if not payload.get("tiktok"):
            continue
        if not _payload_counts_against_tiktok_cap(payload):
            continue

        scheduled_day = _payload_publication_day(payload)
        current_count = scheduled_counts.get(scheduled_day, 0)
        if current_count >= daily_cap:
            payload["tiktok"] = False
            payload["tiktok_throttle_reason"] = TIKTOK_DAILY_POST_CAP_NOTE
            payload["tiktok_daily_post_cap"] = daily_cap
            suppressed_count += 1
            continue

        scheduled_counts[scheduled_day] = current_count + 1
        payload["tiktok_daily_post_cap"] = daily_cap

    return suppressed_count


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
    publication_date_time = first_payload.get("publication_date_time") or first_payload.get("publicationDate")
    as_draft = first_payload.get("as_draft")
    if as_draft is None:
        as_draft = first_payload.get("draft")
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
        "metricool_publication_date_time": publication_date_time,
        "metricool_post_content": first_payload.get("post_content"),
        "metricool_media_01": flat_media_url,
        "metricool_as_draft": as_draft,
        "metricool_auto_publish": first_payload.get("auto_publish"),
        "metricool_post_type": first_payload.get("post_type"),
        "metricool_social_post_type": first_payload.get("social_post_type"),
        "metricool_product_sku": first_payload.get("product_sku"),
        "metricool_product_title": first_payload.get("product_title"),
        "metricool_ebay_url": first_payload.get("ebay_url"),
        "metricool_buy_url": first_payload.get("buy_url"),
        "metricool_link_url": first_payload.get("link_url"),
        "metricool_facebook_link_url": first_payload.get("facebook_link_url"),
        "metricool_comment_keyword": first_payload.get("comment_keyword"),
        "metricool_manychat_reply": first_payload.get("manychat_reply"),
        "metricool_history_id": first_payload.get("history_id"),
        "metricool_tiktok_enabled_count": sum(1 for payload in batch.metricool_payloads if payload.get("tiktok")),
        "metricool_tiktok_suppressed_count": sum(
            1 for payload in batch.metricool_payloads if payload.get("tiktok_throttle_reason")
        ),
        "publicationDate": publication_date_time,
        "draft": as_draft,
    }
    response.update({key: value for key, value in flat_fields.items() if value is not None})
    response.update(_metricool_line_items(batch.metricool_payloads))
    return response


def _metricool_line_items(payloads: list[dict[str, object]]) -> dict[str, object]:
    if not payloads:
        return {"metricool_payload_count": 0}
    fields = (
        "brand_name",
        "facebook",
        "instagram",
        "tiktok",
        "linkedin",
        "publish_to_facebook_groups",
        "facebook_groups",
        "publication_date_time",
        "post_content",
        "media_01",
        "as_draft",
        "auto_publish",
        "post_type",
        "social_post_type",
        "product_sku",
        "product_title",
        "ebay_url",
        "buy_url",
        "link_url",
        "facebook_link_url",
        "comment_keyword",
        "manychat_reply",
        "history_id",
        "tiktok_daily_post_cap",
        "tiktok_throttle_reason",
    )
    line_items: dict[str, object] = {"metricool_payload_count": len(payloads)}
    for field in fields:
        line_items[f"metricool_{field}_items"] = [
            _csv_value(payload.get(field)) if field == "facebook_groups" else payload.get(field)
            for payload in payloads
        ]
    line_items["publicationDate_items"] = [
        payload.get("publication_date_time") or payload.get("publicationDate")
        for payload in payloads
    ]
    line_items["draft_items"] = [
        payload.get("as_draft") if payload.get("as_draft") is not None else payload.get("draft")
        for payload in payloads
    ]
    return line_items


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
    needs_tiktok_safe_media = post.platform == "tiktok" or (
        bool(request and request.promote_all_inventory and request.cross_post_to_all_platforms)
        and "tiktok" in (request.platforms if request else [])
    )
    if media_url:
        if not needs_tiktok_safe_media or _is_tiktok_supported_media(media_url):
            return media_url
        return generated_product_media_url(post.product_sku)
    return generated_product_media_url(post.product_sku)


def _platform_enabled(post: SocialPost, request: SocialDraftRequest, platform: str) -> bool:
    if request.promote_all_inventory and request.cross_post_to_all_platforms:
        return platform in request.platforms
    return post.platform == platform


def _payload_counts_against_tiktok_cap(payload: dict[str, object]) -> bool:
    return bool(payload.get("auto_publish")) or payload.get("as_draft") is False or payload.get("draft") is False


def _payload_publication_day(payload: dict[str, object]) -> str:
    value = payload.get("publication_date_time") or payload.get("publicationDate")
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return "unscheduled"


def generated_product_media_url(sku: str | None, extension: str = "jpg") -> str | None:
    if not sku:
        return None
    clean_extension = extension.lower().lstrip(".")
    if clean_extension not in {"jpg", "jpeg", "png", "webp"}:
        clean_extension = "jpg"
    base_url = get_settings().public_base_url.rstrip("/")
    return f"{base_url}/media/products/{quote(sku, safe='')}.{clean_extension}"


def _metricool_publication_time(post: SocialPost, request: SocialDraftRequest) -> str:
    return (
        _valid_metricool_publication_time(post.suggested_schedule)
        or _valid_metricool_publication_time(request.publish_after)
        or default_metricool_publication_time()
    )


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


def default_metricool_publication_times(
    count: int,
    now: datetime | None = None,
    start_at: str | datetime | None = None,
) -> list[str]:
    if count <= 0:
        return []

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    local_now = current_time.astimezone(POSTING_TIMEZONE)
    minimum_time = local_now + POSTING_MINIMUM_LEAD_TIME
    schedule_start = _coerce_metricool_schedule_start(start_at)
    if schedule_start and schedule_start > minimum_time:
        minimum_time = schedule_start

    publication_times: list[str] = []
    day_offset = 0
    start_date = minimum_time.date()
    posting_slots = _configured_daily_posting_slots()

    while len(publication_times) < count:
        candidate_date = start_date + timedelta(days=day_offset)
        for slot in posting_slots:
            candidate = datetime.combine(candidate_date, slot, tzinfo=POSTING_TIMEZONE)
            if candidate >= minimum_time:
                publication_times.append(candidate.strftime("%Y-%m-%d %H:%M:%S"))
                if len(publication_times) == count:
                    return publication_times
        day_offset += 1

    return publication_times


def _configured_daily_posting_slots() -> tuple[time, ...]:
    settings = get_settings()
    configured_slots = [
        _parse_posting_time(settings.metricool_morning_post_time),
        _parse_posting_time(settings.metricool_evening_post_time),
    ]
    slots = tuple(sorted({slot for slot in configured_slots if slot is not None}))
    if not slots:
        slots = DEFAULT_DAILY_POSTING_SLOTS
    daily_limit = max(1, min(int(settings.metricool_daily_post_limit or 2), 2, len(slots)))
    return slots[:daily_limit]


def _parse_posting_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hour, minute = value.strip().split(":", maxsplit=1)
        return time(int(hour), int(minute))
    except (TypeError, ValueError):
        return None


def _coerce_metricool_schedule_start(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        candidate = value
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=POSTING_TIMEZONE)
        return candidate.astimezone(POSTING_TIMEZONE)
    publication_time = _valid_metricool_publication_time(value)
    if not publication_time:
        return None
    return datetime.strptime(publication_time, METRICOOL_PUBLICATION_FORMAT).replace(tzinfo=POSTING_TIMEZONE)
