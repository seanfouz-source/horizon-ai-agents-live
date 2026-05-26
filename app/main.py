import asyncio
import json
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from app.agents import answer_customer_question, create_social_drafts
from app.config import get_settings
from app.ebay import EbayClient
from app.integrations import extract_customer_message, manychat_dynamic_response, normalize_channel, zapier_social_drafts_response
from app.inventory import InventoryRepository
from app.inventory_seed import seed_inventory_if_empty
from app.models import CustomerQuestion, EbayStoreImportRequest, InventoryItem, InventorySearchResult, SocialDraftRequest
from app.store_sync import StorePageSyncer


settings = get_settings()
repository = InventoryRepository(settings.resolved_database_path)
store_syncer = StorePageSyncer(settings, repository)
app = FastAPI(title=settings.app_name)


def verify_secret(x_horizon_secret: str | None, query_secret: str | None = None) -> None:
    expected = settings.webhook_shared_secret
    if not expected:
        return
    if x_horizon_secret != expected and query_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": settings.app_name, "store_sync": store_syncer.last_status}


@app.on_event("startup")
async def startup_store_page_sync() -> None:
    seed_inventory_if_empty(repository, settings.seed_inventory_csv)
    if settings.sync_store_page_on_startup:
        asyncio.create_task(store_syncer.sync())


@app.get("/inventory/search", response_model=InventorySearchResult)
def search_inventory(q: str = "", limit: int = 8) -> InventorySearchResult:
    items = repository.search(q, limit=limit)
    return InventorySearchResult(total=len(items), items=items)


@app.post("/inventory/import")
async def import_inventory(
    items: list[InventoryItem],
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, int]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    count = repository.upsert_items(items)
    return {"imported": count}


@app.post("/inventory/sync/ebay")
async def sync_ebay_inventory(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, int]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    client = EbayClient(settings)
    items = await client.fetch_inventory_items()
    count = repository.upsert_items(items)
    return {"synced": count}


@app.post("/inventory/sync/store-page")
async def sync_default_store_page(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    return await store_syncer.sync()


@app.post("/inventory/import/ebay-store-page")
async def import_ebay_store_page(
    import_request: EbayStoreImportRequest,
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    return await store_syncer.sync(import_request.store_url, import_request.max_pages)


@app.post("/agent/customer-answer", response_model=dict[str, Any])
async def customer_answer(question: CustomerQuestion) -> dict[str, Any]:
    answer = await answer_customer_question(question)
    return answer.model_dump()


@app.post("/agent/social-drafts", response_model=dict[str, Any])
async def social_drafts(request: SocialDraftRequest) -> dict[str, Any]:
    batch = await create_social_drafts(request)
    return batch.model_dump()


@app.post("/webhooks/manychat")
async def manychat_webhook(
    payload: dict[str, Any],
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    message = extract_customer_message(payload)
    if not message:
        raise HTTPException(status_code=400, detail="No customer message found in payload.")
    question = CustomerQuestion(
        message=message,
        channel=normalize_channel(payload.get("channel") or payload.get("platform")),
        user_id=str(payload.get("subscriber_id") or payload.get("user_id") or ""),
        first_name=str(payload.get("first_name") or ""),
        metadata={key: str(value) for key, value in payload.items() if isinstance(value, (str, int, float, bool))},
    )
    answer = await answer_customer_question(question)
    return manychat_dynamic_response(answer)


@app.post("/webhooks/zapier/customer-question")
async def zapier_customer_question(
    payload: dict[str, Any],
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    message = extract_customer_message(payload)
    if not message:
        raise HTTPException(status_code=400, detail="No customer message found in payload.")
    answer = await answer_customer_question(
        CustomerQuestion(
            message=message,
            channel=normalize_channel(payload.get("channel") or payload.get("platform")),
            user_id=str(payload.get("user_id") or payload.get("subscriber_id") or ""),
            first_name=str(payload.get("first_name") or ""),
            metadata={key: str(value) for key, value in payload.items() if isinstance(value, (str, int, float, bool))},
        )
    )
    return answer.model_dump()


@app.post("/webhooks/zapier/social-drafts")
async def zapier_social_drafts(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    draft_request = SocialDraftRequest.model_validate(await parse_zapier_body(request))
    batch = await create_social_drafts(draft_request)
    return zapier_social_drafts_response(batch)


@app.post("/webhooks/metricool/inbox")
async def metricool_inbox_webhook(
    payload: dict[str, Any],
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    message = extract_customer_message(payload)
    if not message:
        raise HTTPException(status_code=400, detail="No conversation text found in payload.")
    answer = await answer_customer_question(
        CustomerQuestion(
            message=message,
            channel=normalize_channel(payload.get("provider") or payload.get("channel")),
            user_id=str(payload.get("recipient") or payload.get("conversation") or ""),
            metadata={key: str(value) for key, value in payload.items() if isinstance(value, (str, int, float, bool))},
        )
    )
    return {
        "reply": answer.reply,
        "needs_human": answer.needs_human,
        "matched_items": [item.model_dump() for item in answer.matched_items],
    }


async def parse_zapier_body(request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    if not raw_body:
        return {}

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload: Any = json.loads(raw_body)
    else:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            form = await request.form()
            payload = dict(form)

    if isinstance(payload, str):
        payload = json.loads(payload)

    if isinstance(payload, dict) and isinstance(payload.get("data"), str):
        payload = json.loads(payload["data"])

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Zapier payload must be a JSON object.")

    return payload
