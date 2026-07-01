import json
import logging
import re
from datetime import datetime, timedelta
from typing import cast

from agents import Agent, Runner, function_tool

from app.campaigns import request_campaign_media_url
from app.config import get_settings
from app.integrations import (
    METRICOOL_PUBLICATION_FORMAT,
    apply_tiktok_daily_post_cap,
    default_metricool_publication_times,
    metricool_payload,
)
from app.inventory import InventoryRepository
from app.metricool import scheduled_post_counts_by_day
from app.models import (
    CustomerAnswer,
    CustomerQuestion,
    GroupOutreachPlan,
    GroupOutreachRequest,
    GroupReplyDraft,
    GroupReplyRequest,
    InventoryItem,
    SlowMoverMetric,
    SlowMoverOutreachDraft,
    SlowMoverOutreachPlan,
    SlowMoverOutreachRequest,
    SocialDraftBatch,
    SocialDraftPlan,
    SocialDraftRequest,
    SocialPlatform,
    SocialPost,
)


logger = logging.getLogger(__name__)


def get_repository() -> InventoryRepository:
    settings = get_settings()
    return InventoryRepository(settings.resolved_database_path)


def _item_summary(item) -> dict[str, object]:
    return {
        "sku": item.sku,
        "title": item.title,
        "description": item.description,
        "condition": item.condition,
        "price": item.price,
        "currency": item.currency,
        "quantity": item.quantity,
        "ebay_url": item.ebay_url,
        "image_url": item.image_url,
        "image_urls": item.image_urls,
        "category": item.category,
        "listing_status": item.listing_status,
        "item_specifics": item.item_specifics,
    }


@function_tool
def search_stock(query: str, limit: int = 6) -> str:
    """Search current eBay inventory by SKU, title, description, category, or item specifics."""
    items = get_repository().search(query, limit=limit)
    return json.dumps([_item_summary(item) for item in items])


@function_tool
def get_stock_item(sku: str) -> str:
    """Get full details for one inventory item by SKU."""
    item = get_repository().get(sku)
    if item is None:
        return json.dumps({"error": "No item found for that SKU."})
    return json.dumps(_item_summary(item))


@function_tool
def list_promotable_stock(limit: int = 8) -> str:
    """List in-stock eBay items that are ready to promote."""
    items = get_repository().all_promotable(limit=limit)
    return json.dumps([_item_summary(item) for item in items])


STOPWORDS = {
    "about",
    "available",
    "carry",
    "have",
    "hello",
    "iphone",
    "iphones",
    "need",
    "please",
    "stock",
    "there",
    "with",
    "you",
    "your",
}

PHONE_KEYWORDS = {
    "iphone",
    "samsung",
    "galaxy",
    "motorola",
    "moto",
    "pixel",
    "phone",
    "smartphone",
    "oneplus",
    "nokia",
    "xperia",
    "flip",
    "edge",
}


def _candidate_inventory_queries(message: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9]+", message.lower())
    candidates: list[str] = []
    for token in tokens:
        normalized = token[:-1] if token.endswith("s") and len(token) > 4 else token
        if normalized == "iphon":
            normalized = "iphone"
        if normalized in STOPWORDS and normalized != "iphone":
            continue
        if len(normalized) < 3:
            continue
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _matched_items_for_message(message: str):
    repository = get_repository()
    matched_items = [item for item in repository.search(message, limit=3) if _is_active_inventory_answer_item(item)]
    if matched_items:
        return matched_items
    for query in _candidate_inventory_queries(message):
        matched_items = [item for item in repository.search(query, limit=3) if _is_active_inventory_answer_item(item)]
        if matched_items:
            return matched_items
    return []


def _is_active_inventory_answer_item(item: InventoryItem) -> bool:
    if item.quantity <= 0:
        return False
    status = (item.listing_status or "ACTIVE").strip().upper()
    return status in {"ACTIVE", "IN_STOCK", "PUBLISHED", "LIVE"}


CUSTOMER_AGENT_INSTRUCTIONS = """
You answer shopper questions for Horizon's eBay inventory.

Rules:
- Always use inventory tools before answering questions about availability, price, condition, fit, specs, or links.
- Only say an item is available when inventory data shows quantity above zero.
- If you cannot find the exact item, ask one short clarifying question and offer the closest matches.
- Keep replies short enough for social DMs.
- Include the eBay link when there is a relevant listing URL.
- Do not invent discounts, shipping promises, warranties, compatibility, or stock details.
- If a buyer asks for negotiation, returns, order problems, or personal account details, suggest a human follow-up.
"""


SOCIAL_AGENT_INSTRUCTIONS = """
You create social media post drafts for promoting Horizon's eBay listings.

Rules:
- Use inventory tools to ground every post in real in-stock products.
- Write platform-native copy for Facebook, Instagram, TikTok, and LinkedIn.
- Make the eBay listing the call to action when an eBay URL is available.
- Do not invent sale prices, discounts, free shipping, scarcity, or claims that are not in inventory data.
- Avoid spammy wording, excessive hashtags, all caps, or engagement bait.
- For TikTok, write caption-style copy that can accompany a short product video.
- For LinkedIn, write more professional product copy for a business/audience feed.
- Leave suggested_schedule blank; the backend assigns exact Metricool publish times.
- Return structured output only.
"""


GROUP_OUTREACH_AGENT_INSTRUCTIONS = """
You create compliant Facebook Group outreach plans for Horizon Wireless.

Rules:
- Do not tell anyone to auto-join groups, scrape members, cold-DM members, or bypass group rules.
- Treat Facebook Group posts and comments as manual-review work unless the user has an approved, supported inbox/DM trigger.
- Prioritize groups only when the audience and rules are compatible with eBay listings, wholesale phones, resellers, repair shops, or electronics buyers.
- If rules are missing or unclear, recommend review instead of posting.
- Draft short, non-spammy posts that disclose Horizon Wireless and avoid hype, fake scarcity, discounts, or unsupported claims.
- Use the eBay store and campaign video when provided.
- Return structured output only.
"""


def _customer_agent() -> Agent:
    settings = get_settings()
    return Agent(
        name="eBay Customer Support Agent",
        model=settings.openai_model,
        instructions=CUSTOMER_AGENT_INSTRUCTIONS,
        tools=[search_stock, get_stock_item],
    )


def _social_agent() -> Agent:
    settings = get_settings()
    return Agent(
        name="Social Promotion Agent",
        model=settings.openai_model,
        instructions=SOCIAL_AGENT_INSTRUCTIONS,
        tools=[search_stock, get_stock_item, list_promotable_stock],
        output_type=SocialDraftPlan,
    )


def _group_outreach_agent() -> Agent:
    settings = get_settings()
    return Agent(
        name="Facebook Group Outreach Planner",
        model=settings.openai_model,
        instructions=GROUP_OUTREACH_AGENT_INSTRUCTIONS,
        tools=[search_stock, list_promotable_stock],
        output_type=GroupOutreachPlan,
    )


async def answer_customer_question(question: CustomerQuestion) -> CustomerAnswer:
    matched_items = _matched_items_for_message(question.message)
    needs_human = _customer_needs_human(question.message)
    if matched_items and not needs_human:
        reply = _manychat_inventory_reply(question.message, matched_items)
    elif matched_items:
        reply = (
            "I can help with the product info, and a team member should review the order/account part.\n\n"
            + _manychat_inventory_reply(question.message, matched_items)
        )
    else:
        reply = (
            "I don't see an exact match in our active eBay inventory right now. "
            "You can browse current listings here: "
            f"{get_settings().ebay_store_backup_url or get_settings().ebay_store_url}\n\n"
            "A team member can help if you want a similar option."
        )
        needs_human = True
    logger.info(
        "ManyChat inventory reply matched %s item(s); needs_human=%s.",
        len(matched_items),
        needs_human,
    )
    return CustomerAnswer(
        reply=reply,
        channel=question.channel,
        matched_items=matched_items,
        needs_human=needs_human,
    )


def _customer_needs_human(message: str) -> bool:
    normalized = message.lower()
    return any(keyword in normalized for keyword in ["refund", "return", "order", "tracking", "complaint", "warranty"])


def _manychat_inventory_reply(message: str, matched_items: list[InventoryItem]) -> str:
    items_to_send = matched_items[:3] if _message_requests_multiple_options(message) else matched_items[:1]
    if len(items_to_send) == 1:
        item = items_to_send[0]
        return (
            "Yes, this item is currently available.\n\n"
            f"{item.title}\n"
            f"Condition: {item.condition or 'See eBay listing'}\n"
            f"Price: {_manychat_price(item)}\n\n"
            f"You can view or buy it here: {_buy_url_for_item(item)}"
        )

    lines = ["Here are a few active listings that match:"]
    for item in items_to_send:
        lines.append(
            "\n"
            f"{item.title}\n"
            f"Condition: {item.condition or 'See eBay listing'}\n"
            f"Price: {_manychat_price(item)}\n"
            f"Link: {_buy_url_for_item(item)}"
        )
    return "\n".join(lines)


def _message_requests_multiple_options(message: str) -> bool:
    normalized = message.lower()
    return any(
        phrase in normalized
        for phrase in (
            "do you have",
            "what do you have",
            "show me",
            "options",
            "any",
            "iphones",
            "phones",
            "tablets",
            "watches",
            "computers",
        )
    )


def _manychat_price(item: InventoryItem) -> str:
    if item.price is None:
        return "See eBay listing"
    if float(item.price).is_integer():
        return f"${int(item.price)}"
    return f"${item.price:.2f}"


def _matched_items_from_reply(reply: str):
    repository = get_repository()
    items = []
    seen_skus = set()
    item_ids = re.findall(r"ebay\.com/itm/(?:[^/?#\s]+/)?(\d+)", reply)
    item_ids.extend(re.findall(r"\bEBAY-(\d+)\b", reply))
    for item_id in item_ids:
        sku = f"EBAY-{item_id}"
        if sku in seen_skus:
            continue
        item = repository.get(sku)
        if item:
            items.append(item)
            seen_skus.add(sku)
    return items


def _reply_indicates_no_inventory_match(reply: str) -> bool:
    normalized = reply.lower().replace("\u2019", "'")
    no_match_phrases = (
        "don't see",
        "do not see",
        "dont see",
        "don't have",
        "do not have",
        "dont have",
        "not currently",
        "not in our inventory",
        "not available",
        "no matching",
        "no exact",
    )
    return any(phrase in normalized for phrase in no_match_phrases)


async def create_social_drafts(request: SocialDraftRequest) -> SocialDraftBatch:
    if request.promote_all_inventory:
        return await _create_all_inventory_social_drafts(request)

    repository = get_repository()
    campaign_media_url = request_campaign_media_url(request)
    prompt = (
        "Create social drafts for this eBay promotion request.\n"
        f"{request.model_dump_json(indent=2)}"
    )
    if campaign_media_url:
        prompt += (
            "\nUse this campaign media URL for every generated post and write the copy so it fits the video: "
            f"{campaign_media_url}"
        )
    result = await Runner.run(_social_agent(), prompt, max_turns=6)
    plan = result.final_output
    if isinstance(plan, SocialDraftPlan):
        batch = SocialDraftBatch(
            campaign_name=plan.campaign_name,
            posts=plan.posts,
            notes=plan.notes,
        )
    else:
        batch = SocialDraftBatch(
            campaign_name="eBay product promotion",
            posts=[],
            notes=str(plan),
        )
    if campaign_media_url:
        for post in batch.posts:
            post.media_url = campaign_media_url
    if batch.posts:
        metricool_counts = await _metricool_existing_counts(len(batch.posts), request)
        batch.posts = _schedule_metricool_posts(repository, batch.posts, request, metricool_counts)
    batch.metricool_payloads = [metricool_payload(post, request) for post in batch.posts]
    _apply_tiktok_cap_to_batch(batch, request.tiktok_daily_post_cap)
    _record_metricool_payloads(repository, batch.posts, batch.metricool_payloads)
    return batch


def create_slow_mover_outreach(request: SlowMoverOutreachRequest) -> SlowMoverOutreachPlan:
    repository = get_repository()
    items = _slow_mover_items_for_outreach(repository, request)
    if not items:
        return SlowMoverOutreachPlan(
            campaign_name="Slow-mover social outreach",
            notes="No in-stock inventory items matched the slow-mover outreach request.",
        )

    metrics_by_sku = {metric.sku: metric for metric in request.slow_mover_metrics}
    drafts: list[SlowMoverOutreachDraft] = []
    posts: list[SocialPost] = []
    for item in items:
        metric = metrics_by_sku.get(item.sku)
        score, reason = _slow_mover_priority(item, metric)
        keyword = _comment_keyword_for_item(item)
        item_posts = _slow_mover_posts_for_item(item, request, keyword)
        drafts.append(
            SlowMoverOutreachDraft(
                sku=item.sku,
                title=item.title,
                ebay_url=_buy_url_for_item(item),
                priority_score=score,
                reason=reason,
                comment_keyword=keyword,
                manychat_reply=_slow_mover_manychat_reply(item),
                outreach_posts=item_posts,
                manual_outreach_notes=(
                    "Use this for public posts and replies to inbound comments only. "
                    "Do not cold-DM group members; review group rules before posting in groups."
                ),
            )
        )
        posts.extend(item_posts)

    social_request = SocialDraftRequest(
        brand_name=request.brand_name,
        platforms=request.platforms,
        promote_all_inventory=request.cross_post_to_all_platforms,
        cross_post_to_all_platforms=request.cross_post_to_all_platforms,
        publish_after=request.publish_after,
        tiktok_daily_post_cap=request.tiktok_daily_post_cap,
        as_draft=request.as_draft,
        auto_publish=request.auto_publish,
    )
    posts = _schedule_metricool_posts(repository, posts, social_request)
    metricool_payloads = [metricool_payload(post, social_request) for post in posts]
    suppressed_tiktok = apply_tiktok_daily_post_cap(metricool_payloads, request.tiktok_daily_post_cap)
    for payload, post in zip(metricool_payloads, posts, strict=False):
        payload["comment_keyword"] = _comment_keyword_for_sku(post.product_sku)
        payload["manychat_reply"] = _slow_mover_manychat_reply_from_post(post)
    _record_metricool_payloads(repository, posts, metricool_payloads)

    return SlowMoverOutreachPlan(
        campaign_name="Slow-mover social outreach",
        drafts=drafts,
        posts=posts,
        metricool_payloads=metricool_payloads,
        manychat_keywords=[draft.comment_keyword for draft in drafts],
        notes=(
            f"Generated {len(posts)} engagement-focused outreach posts for {len(drafts)} slow-moving items. "
            "Use Looping by Zapier over metricool_payloads to schedule every post, and connect the comment keywords to ManyChat replies."
            + _tiktok_cap_note(suppressed_tiktok, request.tiktok_daily_post_cap)
        ),
    )


def _slow_mover_items_for_outreach(
    repository: InventoryRepository,
    request: SlowMoverOutreachRequest,
) -> list[InventoryItem]:
    metrics_by_sku = {metric.sku: metric for metric in request.slow_mover_metrics}
    requested_skus = [*request.skus, *metrics_by_sku.keys()]
    items: list[InventoryItem] = []
    seen_skus: set[str] = set()

    for sku in requested_skus:
        item = repository.get(sku)
        if item and item.quantity > 0 and item.sku not in seen_skus:
            items.append(item)
            seen_skus.add(item.sku)

    if not items:
        query = request.query.strip().lower() if request.query else ""
        if query in {"all phones", "phones"}:
            phone_candidate_limit = max(request.max_items * 4, request.max_items + 10)
            items = [
                item
                for item in repository.all_promotable(limit=phone_candidate_limit)
                if _looks_like_phone(item)
            ]
        elif query and query not in {"all", "all inventory", "daily inventory"}:
            items = repository.search(request.query, limit=request.max_items)
        else:
            items = repository.all_promotable(limit=request.max_items)

    return sorted(
        items,
        key=lambda item: _slow_mover_priority(item, metrics_by_sku.get(item.sku))[0],
        reverse=True,
    )[: request.max_items]


def _slow_mover_priority(item: InventoryItem, metric: SlowMoverMetric | None) -> tuple[int, str]:
    if not metric:
        return (
            45,
            "Fallback slow-mover candidate from in-stock inventory; pass eBay views, watchers, and sales metrics for sharper ranking.",
        )

    score = 40
    reasons: list[str] = []
    age_days = metric.days_since_sale if metric.days_since_sale is not None else metric.listing_age_days
    if age_days is not None:
        score += min(age_days, 45)
        reasons.append(f"{age_days} days without a sale or listing movement")
    if metric.views is not None and metric.views <= 25:
        score += 15
        reasons.append(f"low views ({metric.views})")
    if metric.watchers is not None and metric.watchers <= 1:
        score += 10
        reasons.append(f"low watchers ({metric.watchers})")
    if metric.quantity_sold == 0:
        score += 10
        reasons.append("no recorded sales")
    if item.quantity > 1:
        score += min(item.quantity, 10)
        reasons.append(f"{item.quantity} units still in stock")
    if metric.notes:
        reasons.append(metric.notes)
    return min(score, 100), "; ".join(reasons) or "Slow-mover metrics supplied by Zapier."


def _slow_mover_posts_for_item(
    item: InventoryItem,
    request: SlowMoverOutreachRequest,
    keyword: str,
) -> list[SocialPost]:
    angle_names = ("question", "use_case", "comparison")[: request.angles_per_item]
    posts: list[SocialPost] = []
    if request.cross_post_to_all_platforms:
        platform = request.platforms[0] if request.platforms else "facebook"
        for angle in angle_names:
            posts.append(_slow_mover_social_post(item, request, platform, keyword, angle))
        return posts

    for angle in angle_names:
        for platform in request.platforms:
            posts.append(_slow_mover_social_post(item, request, platform, keyword, angle))
    return posts


def _slow_mover_social_post(
    item: InventoryItem,
    request: SlowMoverOutreachRequest,
    platform: str,
    keyword: str,
    angle: str,
) -> SocialPost:
    return SocialPost(
        platform=cast(SocialPlatform, platform),
        text=_slow_mover_post_text(item, request, platform, keyword, angle),
        product_sku=item.sku,
        product_title=item.title,
        ebay_url=_buy_url_for_item(item),
        media_url=item.image_url,
        hashtags=_hashtags_for_item(item),
        post_type="engagement",
    )


def _slow_mover_post_text(
    item: InventoryItem,
    request: SlowMoverOutreachRequest,
    platform: str,
    keyword: str,
    angle: str,
) -> str:
    brand = request.brand_name
    title = item.title.strip()
    price = _price_text(item)
    condition = f" Condition: {item.condition}." if item.condition else ""
    url = _buy_url_for_item(item)
    link_line = f"Comment {keyword} for the eBay link, or buy now: {url}"

    if angle == "use_case":
        lead = f"{brand} practical pick: {title}.{price}{condition}"
        hook = "Good fit for a backup phone, reseller shelf, repair-shop customer, or everyday replacement."
    elif angle == "comparison":
        lead = f"Quick comparison check from {brand}: {title}.{price}{condition}"
        hook = "Would you choose this model for value, storage, condition, or unlocked compatibility?"
    else:
        lead = f"{brand} slow-mover spotlight: {title}.{price}{condition}"
        hook = "Who is looking for a clean phone option without paying full flagship retail?"

    if platform == "tiktok":
        hook = "Worth a closer look for shoppers comparing phone value."
    elif platform == "linkedin":
        hook = "Useful for resellers, repair shops, and teams sourcing reliable device inventory."

    return f"{lead}\n{hook}\n{link_line}"


def _comment_keyword_for_item(item: InventoryItem) -> str:
    return _comment_keyword_for_sku(item.sku)


def _comment_keyword_for_sku(sku: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", sku or "").upper()
    suffix = cleaned[-6:] if cleaned else "PHONE"
    return f"LINK{suffix}"


def _slow_mover_manychat_reply(item: InventoryItem) -> str:
    return f"Here is the eBay link for {item.title}: {_buy_url_for_item(item)}"


def _slow_mover_manychat_reply_from_post(post: SocialPost) -> str:
    title = post.product_title or "that Horizon Wireless listing"
    url = post.ebay_url or get_settings().ebay_store_url
    return f"Here is the eBay link for {title}: {url}"


async def _create_all_inventory_social_drafts(request: SocialDraftRequest) -> SocialDraftBatch:
    repository = get_repository()
    items = _inventory_items_for_daily_promotion(repository, request)
    if not items:
        return SocialDraftBatch(
            campaign_name="Daily all-inventory promotion",
            posts=[],
            notes="No in-stock inventory items matched the daily promotion request.",
        )

    posts: list[SocialPost] = []
    campaign_media_url = request_campaign_media_url(request)
    if request.cross_post_to_all_platforms:
        platform = request.platforms[0] if request.platforms else "facebook"
        posts = [
            _inventory_social_post(item, request, platform=platform, media_url=campaign_media_url)
            for item in items
        ]
    else:
        for item in items:
            for platform in request.platforms:
                posts.append(_inventory_social_post(item, request, platform=platform, media_url=campaign_media_url))

    metricool_counts = await _metricool_existing_counts(len(posts), request)
    posts = _schedule_metricool_posts(repository, posts, request, metricool_counts)

    batch = SocialDraftBatch(
        campaign_name=_inventory_campaign_name(request),
        posts=posts,
        notes=(
            f"Generated {len(posts)} scheduled Summer Sale post payloads from {len(items)} in-stock inventory items. "
            "Use the metricool_*_items fields or loop over metricool_payloads in Zapier to schedule every item "
            "at the two-posts-per-day Metricool cadence."
        ),
    )
    batch.metricool_payloads = [metricool_payload(post, request) for post in batch.posts]
    _apply_tiktok_cap_to_batch(batch, request.tiktok_daily_post_cap)
    _record_metricool_payloads(repository, batch.posts, batch.metricool_payloads)
    return batch


def _schedule_metricool_posts(
    repository: InventoryRepository,
    posts: list[SocialPost],
    request: SocialDraftRequest,
    external_daily_counts: dict[str, int] | None = None,
) -> list[SocialPost]:
    if not posts:
        return []

    if not _repository_supports_post_history(repository):
        default_schedule = default_metricool_publication_times(len(posts), start_at=request.publish_after)
        for post, publication_time in zip(posts, default_schedule, strict=False):
            post.suggested_schedule = publication_time
        return posts

    schedule = _available_metricool_publication_times(
        repository,
        len(posts),
        request.publish_after,
        external_daily_counts or {},
    )
    scheduled_posts = posts[: len(schedule)]
    for post, publication_time in zip(scheduled_posts, schedule, strict=False):
        post.suggested_schedule = publication_time
    return scheduled_posts


def _available_metricool_publication_times(
    repository: InventoryRepository,
    count: int,
    start_at: str | None,
    external_daily_counts: dict[str, int],
) -> list[str]:
    if count <= 0:
        return []

    daily_limit = _metricool_daily_post_limit()
    publication_times: list[str] = []
    daily_counts: dict[str, int] = {}
    probe_start = start_at

    for _ in range(370):
        candidates = default_metricool_publication_times(max(count * 3, 8), start_at=probe_start)
        if not candidates:
            break

        for candidate in candidates:
            scheduled_day = candidate[:10]
            if scheduled_day not in daily_counts:
                daily_counts[scheduled_day] = max(
                    repository.social_post_count_for_day(scheduled_day),
                    external_daily_counts.get(scheduled_day, 0),
                )
            if daily_counts[scheduled_day] >= daily_limit:
                continue
            publication_times.append(candidate)
            daily_counts[scheduled_day] += 1
            if len(publication_times) == count:
                return publication_times

        last_candidate = datetime.strptime(candidates[-1], METRICOOL_PUBLICATION_FORMAT)
        next_day = (last_candidate + timedelta(days=1)).date().isoformat()
        probe_start = f"{next_day} 00:00:00"

    return publication_times


async def _metricool_existing_counts(
    post_count: int,
    request: SocialDraftRequest,
) -> dict[str, int]:
    lookahead_days = max(7, (post_count // _metricool_daily_post_limit()) + 3)
    return await scheduled_post_counts_by_day(start_at=request.publish_after, days=lookahead_days)


def _metricool_daily_post_limit() -> int:
    settings = get_settings()
    return max(1, min(int(settings.metricool_daily_post_limit or 2), 2))


def _record_metricool_payloads(
    repository: InventoryRepository,
    posts: list[SocialPost],
    payloads: list[dict[str, object]],
) -> None:
    if not _repository_supports_post_history(repository):
        return

    for post, payload in zip(posts, payloads, strict=False):
        scheduled_at = payload.get("publication_date_time") or payload.get("publicationDate")
        if not isinstance(scheduled_at, str) or not scheduled_at:
            continue
        history_id = repository.record_social_post(
            ebay_item_id=_post_ebay_item_id(post),
            sku=post.product_sku,
            title=post.product_title or "Horizon Wireless eBay listing",
            item_url=post.ebay_url,
            image_url=str(payload.get("media_01") or post.media_url or ""),
            caption=post.text,
            scheduled_at=scheduled_at,
            platform=_metricool_platform_label(payload),
            metricool_post_id=str(payload.get("metricool_post_id") or "") or None,
            status="scheduled",
        )
        payload["history_id"] = history_id
        logger.info(
            "Reserved Metricool payload for eBay item %s at %s on %s.",
            _post_ebay_item_id(post) or post.product_sku,
            scheduled_at,
            _metricool_platform_label(payload),
        )


def _repository_supports_post_history(repository: object) -> bool:
    return all(
        callable(getattr(repository, method, None))
        for method in (
            "social_post_count_for_day",
            "recently_promoted_ebay_item_ids",
            "last_social_post_at_by_ebay_item_id",
            "record_social_post",
        )
    )


def _metricool_platform_label(payload: dict[str, object]) -> str:
    platforms = [
        platform
        for platform in ("facebook", "instagram", "tiktok", "linkedin")
        if payload.get(platform)
    ]
    return ",".join(platforms) if platforms else "unknown"


def _post_ebay_item_id(post: SocialPost) -> str | None:
    if post.ebay_url:
        match = re.search(r"/itm/(?:[^/?#]+/)?(\d+)", post.ebay_url)
        if match:
            return match.group(1)
    if post.product_sku and post.product_sku.startswith("EBAY-"):
        return post.product_sku.removeprefix("EBAY-")
    return post.product_sku


def _apply_tiktok_cap_to_batch(batch: SocialDraftBatch, daily_cap: int) -> None:
    suppressed_tiktok = apply_tiktok_daily_post_cap(batch.metricool_payloads, daily_cap)
    if suppressed_tiktok:
        batch.notes += _tiktok_cap_note(suppressed_tiktok, daily_cap)


def _tiktok_cap_note(suppressed_count: int, daily_cap: int) -> str:
    if not suppressed_count:
        return ""
    return (
        f" TikTok auto-publish was kept to {daily_cap} posts per scheduled day; "
        f"{suppressed_count} extra TikTok placements were disabled to avoid TikTok API daily-cap rejection."
    )


def _inventory_items_for_daily_promotion(repository: InventoryRepository, request: SocialDraftRequest) -> list[InventoryItem]:
    candidate_limit = max(request.max_products_per_run * 4, request.max_products_per_run + 10)
    if request.sku:
        item = repository.get(request.sku)
        candidates = [item] if item and _is_active_promotable_item(item) and _is_ebay_listing(item) else []
        return _rotate_inventory_items(repository, candidates, request.max_products_per_run)
    query = request.query.strip().lower() if request.query else ""
    if query in {"all phones", "phones"}:
        candidates = [
            item
            for item in repository.all_promotable(limit=candidate_limit)
            if _is_ebay_listing(item) and _looks_like_phone(item)
        ]
        return _rotate_inventory_items(repository, candidates, request.max_products_per_run)
    if query and query not in {"all", "all inventory", "daily inventory"}:
        candidates = [item for item in repository.search(request.query, limit=candidate_limit) if _is_ebay_listing(item)]
        return _rotate_inventory_items(repository, candidates, request.max_products_per_run)
    return _rotate_inventory_items(
        repository,
        [item for item in repository.all_promotable(limit=candidate_limit) if _is_ebay_listing(item)],
        request.max_products_per_run,
    )


def _rotate_inventory_items(
    repository: InventoryRepository,
    items: list[InventoryItem],
    limit: int,
) -> list[InventoryItem]:
    active_items = [item for item in items if _is_active_promotable_item(item)]
    if not _repository_supports_post_history(repository):
        return active_items[:limit]

    settings = get_settings()
    recent_item_ids = repository.recently_promoted_ebay_item_ids(settings.metricool_repost_cooldown_days)
    last_posted_at = repository.last_social_post_at_by_ebay_item_id()

    eligible_items = [
        item
        for item in active_items
        if (_item_ebay_item_id(item) not in recent_item_ids)
    ]
    if not eligible_items:
        return []

    return sorted(
        eligible_items,
        key=lambda item: last_posted_at.get(_item_ebay_item_id(item) or "", ""),
    )[:limit]


def _is_active_promotable_item(item: InventoryItem) -> bool:
    if item.quantity <= 0:
        return False
    if not item.image_url:
        return False
    status = (item.listing_status or "ACTIVE").strip().upper()
    return status in {"ACTIVE", "IN_STOCK", "PUBLISHED", "LIVE"}


def _is_ebay_listing(item: InventoryItem) -> bool:
    if item.source.startswith("ebay-"):
        return True
    return item.sku.startswith("EBAY-")


def _item_ebay_item_id(item: InventoryItem) -> str | None:
    if item.ebay_item_id:
        return item.ebay_item_id
    if item.ebay_url:
        match = re.search(r"/itm/(?:[^/?#]+/)?(\d+)", item.ebay_url)
        if match:
            return match.group(1)
    if item.sku.startswith("EBAY-"):
        return item.sku.removeprefix("EBAY-")
    return None


def _looks_like_phone(item: InventoryItem) -> bool:
    haystack = " ".join(
        [
            item.title,
            item.description or "",
            item.category or "",
            " ".join(str(value) for value in item.item_specifics.values()),
        ]
    ).lower()
    return any(keyword in haystack for keyword in PHONE_KEYWORDS)


def _inventory_social_post(
    item: InventoryItem,
    request: SocialDraftRequest,
    platform: str,
    media_url: str | None = None,
) -> SocialPost:
    return SocialPost(
        platform=cast(SocialPlatform, platform),
        text=_inventory_post_text(item, request, platform),
        product_sku=item.sku,
        product_title=item.title,
        ebay_url=_buy_url_for_item(item),
        media_url=media_url or request.media_url or _sale_media_url_for_request(request) or item.image_url,
        hashtags=_hashtags_for_item(item),
    )


def _inventory_post_text(item: InventoryItem, request: SocialDraftRequest, platform: str) -> str:
    brand = request.brand_name or "Horizon Wireless"
    sale_name = (request.sale_name or f"{brand} eBay Store Sale").strip()
    store_url = _store_url_for_request(request)
    price = f"Price: ${item.price:,.2f}" if item.price is not None else "Price: See eBay listing"
    condition = f"Condition: {item.condition}" if item.condition else "Condition: See eBay listing"
    url = _buy_url_for_item(item)
    title = item.title.strip()
    return (
        f"{sale_name} spotlight: {title}\n\n"
        f"{condition}\n"
        f"{price}\n\n"
        f"Shop the full {brand} sale on our eBay store: {store_url}\n"
        f"View this listing: {url}"
    )


def _inventory_campaign_name(request: SocialDraftRequest) -> str:
    sale_name = (request.sale_name or "").strip()
    if sale_name:
        return f"{sale_name} inventory promotion"
    brand = request.brand_name or "Horizon Wireless"
    return f"{brand} inventory promotion"


def _store_url_for_request(request: SocialDraftRequest) -> str:
    configured = (request.store_url or "").strip()
    if configured:
        return configured
    return get_settings().ebay_store_url


def _sale_media_url_for_request(request: SocialDraftRequest) -> str | None:
    configured = (request.sale_media_url or "").strip()
    if configured:
        return configured
    return get_settings().ebay_store_sale_media_url


def _buy_url_for_item(item: InventoryItem) -> str:
    if item.ebay_item_id:
        return f"https://www.ebay.com/itm/{item.ebay_item_id}"
    if item.ebay_url:
        canonical = _canonical_ebay_item_url(item.ebay_url)
        return canonical or item.ebay_url
    return get_settings().ebay_store_url


def _canonical_ebay_item_url(url: str) -> str | None:
    match = re.search(r"/itm/(?:[^/?#]+/)?(\d+)", url)
    if not match:
        return None
    return f"https://www.ebay.com/itm/{match.group(1)}"


def _price_text(item: InventoryItem) -> str:
    if item.price is None:
        return ""
    if float(item.price).is_integer():
        return f" Price: ${int(item.price)}."
    return f" Price: ${item.price:.2f}."


def _hashtags_for_item(item: InventoryItem) -> list[str]:
    normalized = item.title.lower()
    hashtags = ["HorizonWireless", "eBayFinds"]
    if "iphone" in normalized:
        hashtags.append("iPhone")
    if "samsung" in normalized or "galaxy" in normalized:
        hashtags.append("SamsungGalaxy")
    if "pixel" in normalized:
        hashtags.append("GooglePixel")
    return hashtags


async def create_group_outreach_plan(request: GroupOutreachRequest) -> GroupOutreachPlan:
    prompt = (
        "Create a compliant Facebook Group outreach plan.\n"
        f"{request.model_dump_json(indent=2)}"
    )
    result = await Runner.run(_group_outreach_agent(), prompt, max_turns=5)
    plan = result.final_output
    if isinstance(plan, GroupOutreachPlan):
        return plan
    return GroupOutreachPlan(
        summary="Manual review required before Facebook Group outreach.",
        join_request_draft="Hi, I work with Horizon Wireless. I am interested in joining to learn and share relevant phone inventory only when it follows the group rules.",
        compliance_checklist=[
            "Do not auto-join groups.",
            "Do not post unless the group rules allow relevant business posts.",
            "Do not cold-message group members.",
        ],
        notes=str(plan),
    )


async def draft_group_reply(request: GroupReplyRequest) -> GroupReplyDraft:
    answer = await answer_customer_question(
        CustomerQuestion(
            message=request.message,
            channel=request.channel,
            user_id=request.author_name,
            first_name=request.author_name,
            metadata={
                "group_name": request.group_name or "",
                "group_url": request.group_url or "",
                "interaction_type": request.interaction_type,
                "post_context": request.post_context or "",
                "rules_text": request.rules_text or "",
            },
        )
    )
    can_auto_send = _can_auto_send_group_reply(request)
    return GroupReplyDraft(
        reply=answer.reply,
        channel=answer.channel,
        matched_items=answer.matched_items,
        needs_human=answer.needs_human,
        manual_review_required=not can_auto_send,
        can_auto_send=can_auto_send,
        compliance_notes=_group_reply_compliance_note(request, can_auto_send),
    )

def _can_auto_send_group_reply(request: GroupReplyRequest) -> bool:
    return request.interaction_type in {"group_dm_to_page", "page_dm", "instagram_dm"} and request.user_opted_in


def _group_reply_compliance_note(request: GroupReplyRequest, can_auto_send: bool) -> str:
    if can_auto_send:
        return "Can be sent through a supported inbound DM automation because the user messaged Horizon and opted in."
    return "Draft only. Facebook Group comments and member interactions require manual review; do not auto-send, cold-DM, or bypass group rules."
