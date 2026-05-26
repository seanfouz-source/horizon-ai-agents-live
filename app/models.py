from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


Channel = Literal["facebook", "instagram", "tiktok", "whatsapp", "telegram", "web", "unknown"]
SocialPlatform = Literal["facebook", "instagram", "tiktok"]


class InventoryItem(BaseModel):
    sku: str
    title: str
    description: str | None = None
    condition: str | None = None
    price: float | None = None
    currency: str = "USD"
    quantity: int = 0
    ebay_item_id: str | None = None
    ebay_url: str | None = None
    image_url: str | None = None
    category: str | None = None
    item_specifics: dict[str, str] = Field(default_factory=dict)
    source: str = "manual"
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InventorySearchResult(BaseModel):
    total: int
    items: list[InventoryItem]


class EbayStoreImportRequest(BaseModel):
    store_url: str
    max_pages: int = Field(default=1, ge=1, le=10)


class CustomerQuestion(BaseModel):
    message: str
    channel: Channel = "unknown"
    user_id: str | None = None
    first_name: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class CustomerAnswer(BaseModel):
    reply: str
    channel: Channel = "unknown"
    matched_items: list[InventoryItem] = Field(default_factory=list)
    needs_human: bool = False


class SocialDraftRequest(BaseModel):
    query: str | None = None
    sku: str | None = None
    campaign_goal: str = "Drive shoppers to the eBay store."
    tone: str = "friendly, clear, and sales-focused without hype"
    platforms: list[SocialPlatform] = Field(default_factory=lambda: ["facebook", "instagram", "tiktok"])
    posts_per_platform: int = Field(default=1, ge=1, le=5)
    brand_name: str | None = None
    publish_after: str | None = None
    as_draft: bool = True
    auto_publish: bool = False


class SocialPost(BaseModel):
    platform: SocialPlatform
    text: str
    product_sku: str | None = None
    product_title: str | None = None
    ebay_url: str | None = None
    media_url: str | None = None
    suggested_schedule: str | None = None
    post_type: str = "post"
    hashtags: list[str] = Field(default_factory=list)


class SocialDraftPlan(BaseModel):
    campaign_name: str
    posts: list[SocialPost]
    notes: str = ""


class SocialDraftBatch(BaseModel):
    campaign_name: str
    posts: list[SocialPost]
    metricool_payloads: list[dict[str, object]] = Field(default_factory=list)
    notes: str = ""
