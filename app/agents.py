import json
import re

from agents import Agent, Runner, function_tool

from app.campaigns import request_campaign_media_url
from app.config import get_settings
from app.integrations import metricool_payload
from app.inventory import InventoryRepository
from app.models import (
    CustomerAnswer,
    CustomerQuestion,
    GroupOutreachPlan,
    GroupOutreachRequest,
    GroupReplyDraft,
    GroupReplyRequest,
    SocialDraftBatch,
    SocialDraftPlan,
    SocialDraftRequest,
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


async def create_social_drafts(request: SocialDraftRequest) -> SocialDraftBatch:
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
    batch.metricool_payloads = [metricool_payload(post, request) for post in batch.posts]
    return batch


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
