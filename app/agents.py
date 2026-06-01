import json
import re
from typing import cast

from agents import Agent, Runner, function_tool

from app.campaigns import request_campaign_media_url
from app.config import get_settings
from app.integrations import default_metricool_publication_times, metricool_payload
from app.inventory import InventoryRepository
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
        "category": item.category,
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
    matched_items = repository.search(message, limit=3)
    if matched_items:
        return matched_items
    for query in _candidate_inventory_queries(message):
        matched_items = repository.search(query, limit=3)
        if matched_items:
            return matched_items
    return []


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
    context = {
        "channel": question.channel,
        "user_id": question.user_id,
        "first_name": question.first_name,
        "message": question.message,
        "metadata": question.metadata,
    }
    prompt = (
        "Answer this shopper using current inventory only.\n"
        f"{json.dumps(context, indent=2)}"
    )
    result = await Runner.run(_customer_agent(), prompt, max_turns=5)
    matched_items = _matched_items_for_message(question.message)
    reply = str(result.final_output).strip()
    mentioned_items = _matched_items_from_reply(reply)
    if mentioned_items:
        matched_items = mentioned_items
    elif _reply_indicates_no_inventory_match(reply):
        matched_items = []
    needs_human = any(keyword in question.message.lower() for keyword in ["refund", "return", "order", "tracking", "complaint"])
    return CustomerAnswer(
        reply=reply,
        channel=question.channel,
        matched_items=matched_items,
        needs_human=needs_human,
    )


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
        return _create_all_inventory_social_drafts(request)

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
        default_schedule = default_metricool_publication_times(len(batch.posts), start_at=request.publish_after)
        for post, publication_time in zip(batch.posts, default_schedule, strict=False):
            post.suggested_schedule = publication_time
    batch.metricool_payloads = [metricool_payload(post, request) for post in batch.posts]
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

    schedule = default_metricool_publication_times(len(posts), start_at=request.publish_after)
    for post, publication_time in zip(posts, schedule, strict=False):
        post.suggested_schedule = publication_time

    social_request = SocialDraftRequest(
        brand_name=request.brand_name,
        platforms=request.platforms,
        promote_all_inventory=request.cross_post_to_all_platforms,
        cross_post_to_all_platforms=request.cross_post_to_all_platforms,
        publish_after=request.publish_after,
        as_draft=request.as_draft,
        auto_publish=request.auto_publish,
    )
    metricool_payloads = [metricool_payload(post, social_request) for post in posts]
    for payload, post in zip(metricool_payloads, posts, strict=False):
        payload["comment_keyword"] = _comment_keyword_for_sku(post.product_sku)
        payload["manychat_reply"] = _slow_mover_manychat_reply_from_post(post)

    return SlowMoverOutreachPlan(
        campaign_name="Slow-mover social outreach",
        drafts=drafts,
        posts=posts,
        metricool_payloads=metricool_payloads,
        manychat_keywords=[draft.comment_keyword for draft in drafts],
        notes=(
            f"Generated {len(posts)} engagement-focused outreach posts for {len(drafts)} slow-moving items. "
            "Use Looping by Zapier over metricool_payloads to schedule every post, and connect the comment keywords to ManyChat replies."
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


def _create_all_inventory_social_drafts(request: SocialDraftRequest) -> SocialDraftBatch:
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

    default_schedule = default_metricool_publication_times(len(posts), start_at=request.publish_after)
    for post, publication_time in zip(posts, default_schedule, strict=False):
        post.suggested_schedule = publication_time

    batch = SocialDraftBatch(
        campaign_name="Daily all-inventory promotion",
        posts=posts,
        notes=(
            f"Generated {len(posts)} scheduled post payloads from {len(items)} in-stock inventory items. "
            "Use the metricool_*_items fields or loop over metricool_payloads in Zapier to schedule every item."
        ),
    )
    batch.metricool_payloads = [metricool_payload(post, request) for post in batch.posts]
    return batch


def _inventory_items_for_daily_promotion(repository: InventoryRepository, request: SocialDraftRequest) -> list[InventoryItem]:
    if request.sku:
        item = repository.get(request.sku)
        return [item] if item and item.quantity > 0 else []
    query = request.query.strip().lower() if request.query else ""
    if query in {"all phones", "phones"}:
        return [
            item
            for item in repository.all_promotable(limit=request.max_products_per_run)
            if _looks_like_phone(item)
        ]
    if query and query not in {"all", "all inventory", "daily inventory"}:
        return repository.search(request.query, limit=request.max_products_per_run)
    return repository.all_promotable(limit=request.max_products_per_run)


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
        media_url=media_url or request.media_url,
        hashtags=_hashtags_for_item(item),
    )


def _inventory_post_text(item: InventoryItem, request: SocialDraftRequest, platform: str) -> str:
    brand = request.brand_name or "Horizon Wireless"
    price = _price_text(item)
    condition = f" Condition: {item.condition}." if item.condition else ""
    url = _buy_url_for_item(item)
    title = item.title.strip()
    buy_line = f"Buy on eBay: {url}"
    if request.cross_post_to_all_platforms:
        return (
            f"{brand} listing update: {title}.{price}{condition}\n"
            f"{buy_line}"
        )
    if platform == "instagram":
        return f"Now listed at {brand}: {title}.{price}{condition}\n{buy_line}"
    if platform == "tiktok":
        return f"{title} is live in the {brand} eBay store.{price}{condition}\n{buy_line}"
    if platform == "linkedin":
        return f"{brand} inventory update: {title}.{price}{condition}\n{buy_line}"
    return f"{title} is available now from {brand}.{price}{condition}\n{buy_line}"


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
