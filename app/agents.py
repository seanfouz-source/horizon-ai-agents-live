import json

from agents import Agent, Runner, function_tool

from app.config import get_settings
from app.integrations import metricool_payload
from app.inventory import InventoryRepository
from app.models import CustomerAnswer, CustomerQuestion, SocialDraftBatch, SocialDraftPlan, SocialDraftRequest


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
- Write platform-native copy for Facebook, Instagram, and TikTok.
- Make the eBay listing the call to action when an eBay URL is available.
- Do not invent sale prices, discounts, free shipping, scarcity, or claims that are not in inventory data.
- Avoid spammy wording, excessive hashtags, all caps, or engagement bait.
- For TikTok, write caption-style copy that can accompany a short product video.
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
    matched_items = get_repository().search(question.message, limit=3)
    reply = str(result.final_output).strip()
    needs_human = any(keyword in question.message.lower() for keyword in ["refund", "return", "order", "tracking", "complaint"])
    return CustomerAnswer(
        reply=reply,
        channel=question.channel,
        matched_items=matched_items,
        needs_human=needs_human,
    )


async def create_social_drafts(request: SocialDraftRequest) -> SocialDraftBatch:
    prompt = (
        "Create social drafts for this eBay promotion request.\n"
        f"{request.model_dump_json(indent=2)}"
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
    batch.metricool_payloads = [metricool_payload(post, request) for post in batch.posts]
    return batch
