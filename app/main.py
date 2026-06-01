import asyncio
import json
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse

from app.agents import (
    answer_customer_question,
    create_group_outreach_plan,
    create_slow_mover_outreach,
    create_social_drafts,
    draft_group_reply,
)
from app.campaigns import campaign_video_catalog, campaign_video_path
from app.config import get_settings
from app.ebay import EbayClient
from app.integrations import extract_customer_message, manychat_dynamic_response, normalize_channel, zapier_social_drafts_response
from app.inventory import InventoryRepository
from app.inventory_seed import seed_inventory_if_empty
from app.media import product_card_for_item, product_card_jpeg_for_item
from app.models import (
    CustomerQuestion,
    EbayStoreImportRequest,
    GroupOutreachRequest,
    GroupReplyRequest,
    InventoryItem,
    InventorySearchResult,
    SlowMoverOutreachPlan,
    SlowMoverOutreachRequest,
    SocialDraftBatch,
    SocialDraftRequest,
)
from app.reports import (
    MetricoolReportError,
    REPORT_TIMEZONE,
    build_daily_metricool_report,
    flatten_report_for_zapier,
    format_daily_report_markdown,
    format_daily_report_pdf,
    report_attachment_filename,
)
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


@app.get("/media/products/{sku}.png")
def product_media(sku: str) -> Response:
    item = repository.get(sku)
    if item is None:
        raise HTTPException(status_code=404, detail="No inventory item found for that SKU.")
    return Response(
        content=product_card_for_item(item),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.head("/media/products/{sku}.png")
def product_media_head(sku: str) -> Response:
    item = repository.get(sku)
    if item is None:
        raise HTTPException(status_code=404, detail="No inventory item found for that SKU.")
    content = product_card_for_item(item)
    return Response(
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Length": str(len(content)),
        },
    )


@app.get("/media/products/{sku}.jpeg")
@app.get("/media/products/{sku}.jpg")
def product_media_jpeg(sku: str) -> Response:
    item = repository.get(sku)
    if item is None:
        raise HTTPException(status_code=404, detail="No inventory item found for that SKU.")
    return Response(
        content=product_card_jpeg_for_item(item),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.head("/media/products/{sku}.jpeg")
@app.head("/media/products/{sku}.jpg")
def product_media_jpeg_head(sku: str) -> Response:
    item = repository.get(sku)
    if item is None:
        raise HTTPException(status_code=404, detail="No inventory item found for that SKU.")
    content = product_card_jpeg_for_item(item)
    return Response(
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Length": str(len(content)),
        },
    )


@app.get("/campaigns/videos")
def campaign_videos() -> dict[str, object]:
    return {"videos": campaign_video_catalog()}


@app.get("/reports/daily")
async def daily_report(
    request: Request,
    date: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    try:
        report = await build_daily_metricool_report(_parse_report_date(date))
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    report["inventory"] = {"total_items": repository.count(), "store_sync": store_syncer.last_status}
    return report


@app.get("/reports/daily.md")
async def daily_report_markdown(
    request: Request,
    date: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> Response:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    try:
        report = await build_daily_metricool_report(_parse_report_date(date))
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    report["inventory"] = {"total_items": repository.count(), "store_sync": store_syncer.last_status}
    return Response(content=format_daily_report_markdown(report), media_type="text/markdown")


@app.get("/reports/daily.pdf")
async def daily_report_pdf(
    request: Request,
    date: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> Response:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    try:
        report = await build_daily_metricool_report(_parse_report_date(date))
        report["inventory"] = {"total_items": repository.count(), "store_sync": store_syncer.last_status}
        content = format_daily_report_pdf(report)
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    filename = report_attachment_filename(report)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.api_route("/webhooks/zapier/daily-report", methods=["GET", "POST"])
async def zapier_daily_report(
    request: Request,
    date: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    body = await parse_zapier_body(request) if request.method == "POST" else {}
    report_date = _parse_report_date(date or body.get("date")) or datetime.now(REPORT_TIMEZONE).date()
    try:
        report = await build_daily_metricool_report(report_date)
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    report["inventory"] = {"total_items": repository.count(), "store_sync": store_syncer.last_status}
    return flatten_report_for_zapier(report)


@app.get("/media/campaigns/{slug}.mp4")
def campaign_video_media(slug: str) -> FileResponse:
    path = campaign_video_path(slug)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="No campaign video found for that slug.")
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.head("/media/campaigns/{slug}.mp4")
def campaign_video_media_head(slug: str) -> Response:
    path = campaign_video_path(slug)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="No campaign video found for that slug.")
    return Response(
        media_type="video/mp4",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Accept-Ranges": "bytes",
            "Content-Length": str(path.stat().st_size),
        },
    )


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


@app.post("/agent/slow-mover-outreach", response_model=dict[str, Any])
async def slow_mover_outreach(request: SlowMoverOutreachRequest) -> dict[str, Any]:
    plan = create_slow_mover_outreach(request)
    return plan.model_dump()


@app.post("/agent/group-outreach-plan", response_model=dict[str, Any])
async def group_outreach_plan(request: GroupOutreachRequest) -> dict[str, Any]:
    plan = await create_group_outreach_plan(request)
    return plan.model_dump()


@app.post("/agent/group-reply", response_model=dict[str, Any])
async def group_reply(request: GroupReplyRequest) -> dict[str, Any]:
    draft = await draft_group_reply(request)
    return draft.model_dump()


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


@app.post("/webhooks/zapier/slow-mover-outreach")
async def zapier_slow_mover_outreach(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    outreach_request = SlowMoverOutreachRequest.model_validate(await parse_zapier_body(request))
    plan = create_slow_mover_outreach(outreach_request)
    return _zapier_slow_mover_outreach_response(plan)


@app.post("/webhooks/zapier/group-reply")
async def zapier_group_reply(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    reply_request = GroupReplyRequest.model_validate(await parse_zapier_body(request))
    draft = await draft_group_reply(reply_request)
    return draft.model_dump()


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


def _zapier_slow_mover_outreach_response(plan: SlowMoverOutreachPlan) -> dict[str, Any]:
    response = plan.model_dump()
    social_fields = zapier_social_drafts_response(
        SocialDraftBatch(
            campaign_name=plan.campaign_name,
            posts=plan.posts,
            metricool_payloads=plan.metricool_payloads,
            notes=plan.notes,
        )
    )
    response.update(
        {
            key: value
            for key, value in social_fields.items()
            if key not in {"campaign_name", "posts", "metricool_payloads", "notes"}
        }
    )
    response["slow_mover_count"] = len(plan.drafts)
    response["slow_mover_sku_items"] = [draft.sku for draft in plan.drafts]
    response["slow_mover_reason_items"] = [draft.reason for draft in plan.drafts]
    response["comment_keyword_items"] = [draft.comment_keyword for draft in plan.drafts]
    response["manychat_reply_items"] = [draft.manychat_reply for draft in plan.drafts]
    return response


def _parse_report_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="Report date must be a YYYY-MM-DD string.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Report date must use YYYY-MM-DD format.") from exc
