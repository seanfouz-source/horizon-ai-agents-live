from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from app.config import BASE_DIR, get_settings

if TYPE_CHECKING:
    from app.models import SocialDraftRequest


CAMPAIGN_VIDEO_DIR = BASE_DIR / "public" / "campaign-videos"
CAMPAIGN_VIDEOS = {
    "wholesale": {
        "title": "Horizon Wireless Wholesale Video",
        "filename": "horizon-wireless-wholesale.mp4",
        "goal": "Promote Horizon Wireless wholesale device buying and bulk sourcing.",
    },
    "ebay-retail-store": {
        "title": "Horizon Wireless eBay Retail Store Video",
        "filename": "horizon-wireless-ebay-retail-store.mp4",
        "goal": "Promote the Horizon Wireless eBay retail store and current listings.",
    },
}
CAMPAIGN_VIDEO_ALIASES = {
    "ebay": "ebay-retail-store",
    "ebay-store": "ebay-retail-store",
    "retail": "ebay-retail-store",
    "retail-store": "ebay-retail-store",
    "store": "ebay-retail-store",
}


def normalize_campaign_video_slug(value: str | None) -> str | None:
    if not value:
        return None
    slug = value.strip().lower().replace("_", "-").replace(" ", "-")
    slug = CAMPAIGN_VIDEO_ALIASES.get(slug, slug)
    if slug not in CAMPAIGN_VIDEOS:
        return None
    return slug


def campaign_video_path(slug: str | None) -> Path | None:
    normalized_slug = normalize_campaign_video_slug(slug)
    if not normalized_slug:
        return None
    return CAMPAIGN_VIDEO_DIR / CAMPAIGN_VIDEOS[normalized_slug]["filename"]


def campaign_video_public_url(slug: str | None) -> str | None:
    normalized_slug = normalize_campaign_video_slug(slug)
    if not normalized_slug:
        return None
    base_url = get_settings().public_base_url.rstrip("/")
    return f"{base_url}/media/campaigns/{quote(normalized_slug, safe='')}.mp4"


def campaign_video_catalog() -> list[dict[str, object]]:
    catalog = []
    for slug, metadata in CAMPAIGN_VIDEOS.items():
        path = campaign_video_path(slug)
        catalog.append(
            {
                "slug": slug,
                "title": metadata["title"],
                "goal": metadata["goal"],
                "media_url": campaign_video_public_url(slug),
                "file_exists": bool(path and path.exists()),
            }
        )
    return catalog


def request_campaign_media_url(request: "SocialDraftRequest | None") -> str | None:
    if request is None:
        return None
    if request.media_url:
        return request.media_url
    return campaign_video_public_url(request.campaign_video)
