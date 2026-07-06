import asyncio
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import date, datetime, timezone
from html import escape
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

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
    CustomerAnswer,
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
from app.report_email import (
    ReportEmailError,
    build_message_from_settings,
    exchange_gmail_authorization_code,
    gmail_oauth_credentials,
    send_message_from_settings,
)
from app.store_sync import StorePageSyncer


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_OAUTH_STATE_MAX_AGE_SECONDS = 15 * 60
settings = get_settings()
repository = InventoryRepository(settings.resolved_database_path)
store_syncer = StorePageSyncer(settings, repository)
ebay_sync_status: dict[str, Any] = {
    "source": "ebay-api",
    "status": "not_run",
    "imported": 0,
    "message": "eBay API sync has not run yet.",
    "last_attempt_at": None,
}
app = FastAPI(title=settings.app_name)
logger = logging.getLogger(__name__)


def verify_secret(x_horizon_secret: str | None, query_secret: str | None = None) -> None:
    expected = settings.webhook_shared_secret
    if not expected:
        return
    if x_horizon_secret != expected and query_secret != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "ebay_sync": ebay_sync_status,
        "store_sync": store_syncer.last_status,
    }


@app.get("/gmail/oauth/start")
def gmail_oauth_start(
    secret: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> RedirectResponse:
    verify_secret(x_horizon_secret, secret)
    try:
        credentials = gmail_oauth_credentials(settings=settings)
        state = _sign_gmail_oauth_state()
    except ReportEmailError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    redirect_uri = _gmail_oauth_redirect_uri()
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": credentials.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GMAIL_SEND_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "login_hint": settings.gmail_sender or settings.report_email_from or "sean.fouz@gmail.com",
        }
    )
    return RedirectResponse(authorization_url, status_code=302)


@app.get("/oauth2callback", response_class=HTMLResponse)
def gmail_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"Google authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Google authorization did not return a code.")
    if not state or not _verify_gmail_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired Google OAuth state.")

    try:
        token_payload = exchange_gmail_authorization_code(
            code=code,
            redirect_uri=_gmail_oauth_redirect_uri(),
            settings=settings,
        )
    except ReportEmailError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    refresh_token = token_payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise HTTPException(
            status_code=503,
            detail="Google did not return a refresh token. Remove the old app grant and retry the OAuth start URL.",
        )

    return HTMLResponse(
        _gmail_oauth_success_html(refresh_token),
        headers={"Cache-Control": "no-store"},
    )


@app.on_event("startup")
async def startup_inventory_sync() -> None:
    seed_inventory_if_empty(repository, settings.seed_inventory_csv)
    _cancel_test_inventory_social_history()
    asyncio.create_task(_startup_inventory_refresh())


def _cancel_test_inventory_social_history() -> None:
    """Temporary cleanup for production test rows that never reached Metricool."""
    now = datetime.now(timezone.utc).isoformat()
    with repository.connect() as connection:
        cursor = connection.execute(
            """
            UPDATE social_post_history
            SET status = 'cancelled',
                error_message = 'Cancelled temporary production test queue before live Zap run.',
                updated_at = ?
            WHERE status = 'scheduled'
            AND posted_at IS NULL
            AND (metricool_post_id IS NULL OR metricool_post_id = '')
            AND item_url LIKE '%ebay.com/itm/%'
            """,
            (now,),
        )
    if cursor.rowcount:
        logger.warning("Cancelled %s temporary inventory social history rows before live Zap run.", cursor.rowcount)


async def _startup_inventory_refresh() -> None:
    api_status: dict[str, Any] | None = None
    if settings.sync_ebay_api_on_startup and _has_ebay_sync_credentials():
        api_status = await _sync_ebay_api_inventory()
    if api_status and api_status.get("status") == "ok":
        return
    if settings.sync_store_page_on_startup:
        await store_syncer.sync()


async def _sync_ebay_api_inventory() -> dict[str, Any]:
    global ebay_sync_status
    attempted_at = datetime.now(timezone.utc).isoformat()
    if not _has_ebay_sync_credentials():
        ebay_sync_status = {
            "source": "ebay-api",
            "status": "skipped",
            "imported": 0,
            "message": "eBay API credentials are not configured.",
            "last_attempt_at": attempted_at,
        }
        return ebay_sync_status

    try:
        client = EbayClient(settings)
        items = await client.fetch_inventory_items()
        count = repository.replace_ebay_inventory_snapshot(items)
        ebay_sync_status = {
            "source": "ebay-api",
            "status": "ok" if count else "empty",
            "imported": count,
            "inventory_count": repository.count(),
            "message": f"Imported {count} active eBay API listings.",
            "last_attempt_at": attempted_at,
        }
    except Exception as exc:
        logger.warning("eBay API inventory sync failed: %s", exc)
        ebay_sync_status = {
            "source": "ebay-api",
            "status": "failed",
            "imported": 0,
            "inventory_count": repository.count(),
            "message": f"eBay API sync failed with {exc.__class__.__name__}.",
            "last_attempt_at": attempted_at,
        }
    return ebay_sync_status


def _has_ebay_sync_credentials() -> bool:
    if (settings.ebay_access_token or "").strip():
        return True
    if all(
        str(getattr(settings, field, "") or "").strip()
        for field in ("ebay_client_id", "ebay_client_secret", "ebay_refresh_token")
    ):
        return True
    return all(
        str(getattr(settings, field, "") or "").strip()
        for field in ("ebay_client_id", "ebay_client_secret")
    )


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
        report = await _build_daily_report(_parse_report_date(date))
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return report


@app.get("/reports/daily.md")
async def daily_report_markdown(
    request: Request,
    date: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> Response:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    try:
        report = await _build_daily_report(_parse_report_date(date))
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=format_daily_report_markdown(report), media_type="text/markdown")


@app.get("/reports/daily.pdf")
async def daily_report_pdf(
    request: Request,
    date: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> Response:
    content, filename = await _daily_report_pdf_content(request, date, x_horizon_secret)
    return Response(
        content=content,
        media_type="application/pdf",
        headers=_daily_report_pdf_headers(filename),
    )


@app.head("/reports/daily.pdf")
async def daily_report_pdf_head(
    request: Request,
    date: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> Response:
    content, filename = await _daily_report_pdf_content(request, date, x_horizon_secret)
    return Response(
        media_type="application/pdf",
        headers={**_daily_report_pdf_headers(filename), "Content-Length": str(len(content))},
    )


async def _daily_report_pdf_content(
    request: Request,
    date: str | None,
    x_horizon_secret: str | None,
) -> tuple[bytes, str]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    try:
        report = await _build_daily_report(_parse_report_date(date))
        content = format_daily_report_pdf(report)
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    filename = report_attachment_filename(report)
    return content, filename


@app.post("/reports/daily/email")
async def daily_report_email(
    request: Request,
    date: str | None = None,
    dry_run: bool = False,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    try:
        report = await _build_daily_report(_parse_report_date(date))
        report_fields = flatten_report_for_zapier(report)
        pdf_bytes = format_daily_report_pdf(report)
        message = build_message_from_settings(report_fields, pdf_bytes, settings)
        if not dry_run:
            send_message_from_settings(message, settings)
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ReportEmailError as exc:
        logger.error("Daily report email failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "prepared" if dry_run else "sent",
        "dry_run": dry_run,
        "report_date": report_fields["report_date"],
        "subject": message["Subject"],
        "to": message["To"],
        "attachment_filename": report_fields["attachment_filename"],
    }


def _daily_report_pdf_headers(filename: str) -> dict[str, str]:
    return {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


@app.api_route("/webhooks/zapier/daily-report", methods=["GET", "POST"])
async def zapier_daily_report(
    request: Request,
    date: str | None = None,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    body = await parse_zapier_body(request) if request.method == "POST" else {}
    report_date = _parse_report_date(date or body.get("date"))
    try:
        report = await _build_daily_report(report_date)
    except MetricoolReportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    return await _sync_ebay_api_inventory()


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
    batch, inventory_refresh = await _create_social_drafts_with_inventory_refresh(request)
    response = batch.model_dump()
    response["inventory_refresh"] = inventory_refresh
    return response


@app.post("/agent/slow-mover-outreach", response_model=dict[str, Any])
async def slow_mover_outreach(request: SlowMoverOutreachRequest) -> dict[str, Any]:
    inventory_refresh = await _refresh_inventory_for_social_posts()
    plan = create_slow_mover_outreach(request)
    response = plan.model_dump()
    response["inventory_refresh"] = inventory_refresh
    return response


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
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    payload = await parse_zapier_body(request)
    message = extract_customer_message(payload)
    if not message:
        raise HTTPException(status_code=400, detail="No customer message found in payload.")
    await _refresh_inventory_for_social_posts()
    question = _customer_question_from_payload(payload, message)
    answer = await answer_customer_question(question)
    _log_customer_inquiry("manychat", question, answer)
    return manychat_dynamic_response(answer)


@app.post("/webhooks/zapier/customer-question")
async def zapier_customer_question(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    payload = await parse_zapier_body(request)
    message = extract_customer_message(payload)
    if not message:
        raise HTTPException(status_code=400, detail="No customer message found in payload.")
    await _refresh_inventory_for_social_posts()
    question = _customer_question_from_payload(payload, message)
    answer = await answer_customer_question(question)
    _log_customer_inquiry("zapier_customer_question", question, answer)
    return answer.model_dump()


@app.post("/webhooks/zapier/facebook-comment-auto-reply")
async def zapier_facebook_comment_auto_reply(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    payload = await parse_zapier_body(request)
    message = extract_customer_message(payload)
    if not message:
        raise HTTPException(status_code=400, detail="No Facebook comment text found in payload.")

    comment_id = _facebook_comment_id_from_payload(payload)
    if not comment_id:
        raise HTTPException(status_code=400, detail="No Facebook comment_id found in payload.")

    if _is_facebook_page_self_comment(payload):
        return {
            "status": "skipped",
            "skipped": True,
            "reason": "Skipped Horizon Wireless page/admin comment.",
            "comment_id": comment_id,
            "reply": "",
            "facebook_comment_reply_status": "skipped",
        }

    await _refresh_inventory_for_social_posts()
    question = _customer_question_from_payload(payload, message)
    answer = await answer_customer_question(question)
    _log_customer_inquiry("zapier_facebook_comment_auto_reply", question, answer)
    facebook_reply = await _post_facebook_comment_reply(comment_id, answer.reply)
    response = answer.model_dump()
    response.update(
        {
            "status": "posted",
            "skipped": False,
            "comment_id": comment_id,
            "facebook_comment_reply_status": "posted",
            "facebook_comment_reply_id": facebook_reply.get("id"),
            "facebook_comment_id_used": facebook_reply.get("comment_id_used"),
            "facebook_comment_reply_endpoint": facebook_reply.get("graph_endpoint"),
            "facebook_graph_response": facebook_reply,
        }
    )
    return response


@app.get("/webhooks/meta/facebook")
async def meta_facebook_webhook_verify(request: Request) -> Response:
    mode = request.query_params.get("hub.mode")
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    expected_token = settings.facebook_webhook_verify_token or settings.webhook_shared_secret
    if not expected_token:
        raise HTTPException(status_code=503, detail="FACEBOOK_WEBHOOK_VERIFY_TOKEN is not configured.")
    if mode == "subscribe" and verify_token == expected_token and challenge is not None:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Invalid Facebook webhook verification token.")


@app.post("/webhooks/meta/facebook")
async def meta_facebook_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    raw_body = await request.body()
    _verify_facebook_webhook_signature(
        raw_body,
        request.headers.get("x-hub-signature-256") or request.headers.get("x-hub-signature"),
    )
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Facebook webhook payload must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Facebook webhook payload must be a JSON object.")

    comment_events = _facebook_comment_events_from_webhook(payload)
    messenger_events = _facebook_messenger_events_from_webhook(payload)
    queued = 0
    skipped = 0
    for event in comment_events:
        if _is_facebook_page_self_comment(event):
            skipped += 1
            logger.info("Meta Facebook webhook skipped page self-comment: comment_id=%s", event.get("comment_id"))
            continue
        background_tasks.add_task(_handle_meta_facebook_comment_event, event)
        queued += 1
    for event in messenger_events:
        if _is_facebook_page_self_message(event):
            skipped += 1
            logger.info("Meta Facebook webhook skipped page self-message: sender_id=%s", event.get("sender_id"))
            continue
        background_tasks.add_task(_handle_meta_facebook_messenger_event, event)
        queued += 1

    logger.info(
        "Meta Facebook webhook accepted: object=%s comment_events=%s messenger_events=%s queued=%s skipped=%s",
        payload.get("object"),
        len(comment_events),
        len(messenger_events),
        queued,
        skipped,
    )

    return {
        "status": "accepted",
        "object": payload.get("object"),
        "comment_events": len(comment_events),
        "messenger_events": len(messenger_events),
        "queued": queued,
        "skipped": skipped,
    }


@app.post("/webhooks/zapier/social-drafts")
async def zapier_social_drafts(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    draft_request = SocialDraftRequest.model_validate(await parse_zapier_body(request))
    batch, inventory_refresh = await _create_social_drafts_with_inventory_refresh(draft_request)
    response = zapier_social_drafts_response(batch)
    response.update(_inventory_refresh_zapier_fields(inventory_refresh))
    return response


@app.post("/webhooks/zapier/slow-mover-outreach")
async def zapier_slow_mover_outreach(
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    outreach_request = SlowMoverOutreachRequest.model_validate(await parse_zapier_body(request))
    inventory_refresh = await _refresh_inventory_for_social_posts()
    plan = create_slow_mover_outreach(outreach_request)
    response = _zapier_slow_mover_outreach_response(plan)
    response.update(_inventory_refresh_zapier_fields(inventory_refresh))
    return response


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
    request: Request,
    x_horizon_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_secret(x_horizon_secret, request.query_params.get("secret"))
    payload = await parse_zapier_body(request)
    message = extract_customer_message(payload)
    if not message:
        raise HTTPException(status_code=400, detail="No conversation text found in payload.")
    await _refresh_inventory_for_social_posts()
    question = _customer_question_from_payload(payload, message, channel_key="provider", user_key="recipient")
    answer = await answer_customer_question(question)
    _log_customer_inquiry("metricool_inbox", question, answer)
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


def _customer_question_from_payload(
    payload: dict[str, Any],
    message: str,
    *,
    channel_key: str = "channel",
    user_key: str = "user_id",
) -> CustomerQuestion:
    metadata = _customer_metadata_from_payload(payload)
    user_id = (
        payload.get(user_key)
        or payload.get("subscriber_id")
        or payload.get("user_id")
        or payload.get("profile_id")
        or payload.get("sender_id")
        or ""
    )
    conversation_id = payload.get("conversation_id") or payload.get("conversation") or payload.get("thread_id")
    if conversation_id is not None:
        metadata["conversation_id"] = str(conversation_id)
    return CustomerQuestion(
        message=message,
        channel=normalize_channel(payload.get(channel_key) or payload.get("platform") or payload.get("channel")),
        user_id=str(user_id),
        first_name=str(payload.get("first_name") or payload.get("name") or ""),
        metadata=metadata,
    )


def _customer_metadata_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)):
            metadata[str(key)] = str(value)
    custom_fields = payload.get("custom_fields")
    if isinstance(custom_fields, dict):
        for key, value in custom_fields.items():
            if isinstance(value, (str, int, float, bool)):
                metadata[str(key)] = str(value)
    return metadata


def _facebook_comment_id_from_payload(payload: dict[str, Any]) -> str:
    direct_keys = (
        "comment_id",
        "facebook_comment_id",
        "commentId",
        "commentID",
        "comment id",
        "id",
    )
    for key in direct_keys:
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()

    custom_fields = payload.get("custom_fields")
    if isinstance(custom_fields, dict):
        for key in direct_keys:
            value = custom_fields.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()
    return ""


def _facebook_comment_events_from_webhook(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("object") != "page":
        return []

    events: list[dict[str, Any]] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return events

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        page_id = str(entry.get("id") or "")
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or change.get("field") != "feed":
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            if str(value.get("item") or "").lower() != "comment":
                continue
            if str(value.get("verb") or "").lower() not in {"add", "edited"}:
                continue

            comment_id = _facebook_comment_id_from_webhook_value(value)
            message = _facebook_comment_message_from_webhook_value(value)
            if not comment_id or not message:
                continue

            author = value.get("from")
            author_id = ""
            author_name = ""
            if isinstance(author, dict):
                author_id = str(author.get("id") or "")
                author_name = str(author.get("name") or "")

            post_id = str(value.get("post_id") or "")
            parent_id = str(value.get("parent_id") or "")
            event = {
                "message": message,
                "channel": "facebook",
                "page_id": page_id,
                "post_id": post_id,
                "comment_id": comment_id,
                "parent_id": parent_id,
                "commenter_id": author_id,
                "from_id": author_id,
                "from_name": author_name,
                "user_id": author_id,
                "subscriber_id": author_id,
                "first_name": author_name,
                "custom_fields": {
                    "facebook_page_id": page_id,
                    "facebook_post_id": post_id,
                    "facebook_comment_id": comment_id,
                    "facebook_parent_id": parent_id,
                },
            }
            events.append(event)
    return events


def _facebook_comment_id_from_webhook_value(value: dict[str, Any]) -> str:
    for key in ("comment_id", "id"):
        comment_id = value.get(key)
        if isinstance(comment_id, (str, int)) and str(comment_id).strip():
            return str(comment_id).strip()
    return ""


def _facebook_comment_message_from_webhook_value(value: dict[str, Any]) -> str:
    for key in ("message", "text"):
        message = value.get(key)
        if isinstance(message, str) and message.strip():
            return message.strip()
    return ""


def _facebook_messenger_events_from_webhook(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("object") != "page":
        return []

    events: list[dict[str, Any]] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return events

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        page_id = str(entry.get("id") or "")
        messaging_events = entry.get("messaging")
        if not isinstance(messaging_events, list):
            continue

        for messaging_event in messaging_events:
            if not isinstance(messaging_event, dict):
                continue
            message_data = messaging_event.get("message")
            postback_data = messaging_event.get("postback")
            if isinstance(message_data, dict) and message_data.get("is_echo"):
                continue
            if not isinstance(message_data, dict) and not isinstance(postback_data, dict):
                continue

            message = _facebook_messenger_message_text(messaging_event)
            if not message:
                continue

            sender_id = _facebook_messenger_party_id(messaging_event.get("sender"))
            recipient_id = _facebook_messenger_party_id(messaging_event.get("recipient")) or page_id
            if not sender_id:
                continue

            mid = ""
            if isinstance(message_data, dict):
                mid = str(message_data.get("mid") or "")
            event = {
                "message": message,
                "channel": "messenger",
                "page_id": page_id or recipient_id,
                "recipient_id": recipient_id,
                "sender_id": sender_id,
                "user_id": sender_id,
                "subscriber_id": sender_id,
                "conversation_id": mid or sender_id,
                "messenger_mid": mid,
                "custom_fields": {
                    "facebook_page_id": page_id or recipient_id,
                    "messenger_sender_id": sender_id,
                    "messenger_recipient_id": recipient_id,
                    "messenger_mid": mid,
                },
            }
            events.append(event)
    return events


def _facebook_messenger_message_text(messaging_event: dict[str, Any]) -> str:
    message_data = messaging_event.get("message")
    if isinstance(message_data, dict):
        text = message_data.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

    postback_data = messaging_event.get("postback")
    if isinstance(postback_data, dict):
        for key in ("title", "payload"):
            text = postback_data.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _facebook_messenger_party_id(value: Any) -> str:
    if isinstance(value, dict):
        party_id = value.get("id")
        if isinstance(party_id, (str, int)) and str(party_id).strip():
            return str(party_id).strip()
    return ""


def _is_facebook_page_self_comment(payload: dict[str, Any]) -> bool:
    configured_page_id = str(settings.facebook_page_id or "").strip()
    configured_page_name = settings.facebook_page_name.strip().casefold()
    id_keys = ("commenter_id", "from_id", "user_id", "subscriber_id")
    name_keys = ("commenter_name", "from_name", "first_name", "name", "author_name")

    if configured_page_id:
        for key in id_keys:
            value = payload.get(key)
            if isinstance(value, (str, int)) and str(value).strip() == configured_page_id:
                return True

    if configured_page_name:
        for key in name_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip().casefold() == configured_page_name:
                return True

    return False


def _is_facebook_page_self_message(payload: dict[str, Any]) -> bool:
    configured_page_id = str(settings.facebook_page_id or "").strip()
    page_id = str(payload.get("page_id") or payload.get("recipient_id") or "").strip()
    sender_id = str(payload.get("sender_id") or payload.get("user_id") or payload.get("subscriber_id") or "").strip()
    if configured_page_id and sender_id == configured_page_id:
        return True
    if page_id and sender_id == page_id:
        return True
    return False


async def _handle_meta_facebook_comment_event(event: dict[str, Any]) -> None:
    comment_id = _facebook_comment_id_from_payload(event)
    message = extract_customer_message(event)
    try:
        if not comment_id or not message:
            logger.warning("Meta Facebook webhook skipped invalid comment event: %s", event)
            return
        await _refresh_inventory_for_social_posts()
        question = _customer_question_from_payload(event, message)
        answer = await answer_customer_question(question)
        _log_customer_inquiry("meta_facebook_webhook", question, answer)
        facebook_reply = await _post_facebook_comment_reply(comment_id, answer.reply)
        logger.info(
            "Meta Facebook comment reply posted: comment_id=%s reply_id=%s endpoint=%s",
            comment_id,
            facebook_reply.get("id"),
            facebook_reply.get("graph_endpoint"),
        )
    except Exception:
        logger.exception("Meta Facebook comment reply failed: comment_id=%s", comment_id)


async def _handle_meta_facebook_messenger_event(event: dict[str, Any]) -> None:
    sender_id = str(event.get("sender_id") or event.get("user_id") or event.get("subscriber_id") or "").strip()
    message = extract_customer_message(event)
    try:
        if not sender_id or not message:
            logger.warning("Meta Facebook webhook skipped invalid Messenger event: %s", event)
            return
        await _refresh_inventory_for_social_posts()
        question = _customer_question_from_payload(event, message)
        answer = await answer_customer_question(question)
        _log_customer_inquiry("meta_facebook_messenger", question, answer)
        messenger_reply = await _send_facebook_messenger_reply(sender_id, answer.reply)
        logger.info(
            "Meta Facebook Messenger reply sent: sender_id=%s message_id=%s endpoint=%s",
            sender_id,
            messenger_reply.get("message_id") or messenger_reply.get("id"),
            messenger_reply.get("graph_endpoint"),
        )
    except Exception:
        logger.exception("Meta Facebook Messenger reply failed: sender_id=%s", sender_id)


async def _post_facebook_comment_reply(comment_id: str, reply: str) -> dict[str, Any]:
    token = settings.facebook_page_access_token
    if not token:
        raise HTTPException(status_code=503, detail="FACEBOOK_PAGE_ACCESS_TOKEN is not configured.")

    api_version = settings.facebook_graph_api_version.strip().strip("/")
    message = reply[:1900]
    attempts: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20) as client:
        for candidate_id in _facebook_comment_id_candidates(comment_id):
            url = f"https://graph.facebook.com/{api_version}/{candidate_id}/comments"
            for attempt_number in range(3):
                try:
                    response = await client.post(
                        url,
                        json={"message": message},
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    result = payload if isinstance(payload, dict) else {"response": payload}
                    result["comment_id_used"] = candidate_id
                    result["graph_endpoint"] = url
                    result["attempts"] = attempts
                    return result
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    detail = _facebook_error_detail(exc.response)
                    attempts.append(
                        {
                            "comment_id": candidate_id,
                            "graph_endpoint": url,
                            "status_code": status_code,
                            "error": detail,
                        }
                    )
                    if status_code in {408, 425, 429, 500, 502, 503, 504} and attempt_number < 2:
                        await asyncio.sleep(0.5 * (2**attempt_number))
                        continue
                    break
                except httpx.HTTPError as exc:
                    attempts.append(
                        {
                            "comment_id": candidate_id,
                            "graph_endpoint": url,
                            "status_code": None,
                            "error": str(exc),
                        }
                    )
                    if attempt_number < 2:
                        await asyncio.sleep(0.5 * (2**attempt_number))
                        continue
                    break

    raise HTTPException(
        status_code=502,
        detail={
            "message": "Facebook comment reply failed.",
            "attempts": attempts,
            "required_permissions": ["pages_read_engagement", "pages_manage_engagement"],
        },
    )


async def _send_facebook_messenger_reply(recipient_id: str, reply: str) -> dict[str, Any]:
    token = settings.facebook_page_access_token
    if not token:
        raise HTTPException(status_code=503, detail="FACEBOOK_PAGE_ACCESS_TOKEN is not configured.")

    api_version = settings.facebook_graph_api_version.strip().strip("/")
    url = f"https://graph.facebook.com/{api_version}/me/messages"
    message = reply[:1900]
    attempts: list[dict[str, Any]] = []
    body = {
        "recipient": {"id": recipient_id},
        "messaging_type": "RESPONSE",
        "message": {"text": message},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        for attempt_number in range(3):
            try:
                response = await client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
                result = payload if isinstance(payload, dict) else {"response": payload}
                result["recipient_id"] = recipient_id
                result["graph_endpoint"] = url
                result["attempts"] = attempts
                return result
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                detail = _facebook_error_detail(exc.response)
                attempts.append({"graph_endpoint": url, "status_code": status_code, "error": detail})
                if status_code in {408, 425, 429, 500, 502, 503, 504} and attempt_number < 2:
                    await asyncio.sleep(0.5 * (2**attempt_number))
                    continue
                break
            except httpx.HTTPError as exc:
                attempts.append({"graph_endpoint": url, "status_code": None, "error": str(exc)})
                if attempt_number < 2:
                    await asyncio.sleep(0.5 * (2**attempt_number))
                    continue
                break

    raise HTTPException(
        status_code=502,
        detail={
            "message": "Facebook Messenger reply failed.",
            "attempts": attempts,
            "required_permissions": ["pages_messaging"],
        },
    )


def _facebook_comment_id_candidates(comment_id: str) -> list[str]:
    raw_id = str(comment_id).strip()
    candidates = [raw_id]
    parts = [part for part in raw_id.split("_") if part]
    if len(parts) > 1:
        candidates.append(parts[-1])
    if len(parts) > 2:
        candidates.append("_".join(parts[-2:]))

    unique_candidates: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique_candidates:
            unique_candidates.append(candidate)
    return unique_candidates


def _verify_facebook_webhook_signature(raw_body: bytes, signature_header: str | None) -> None:
    app_secret = settings.facebook_app_secret
    if not app_secret:
        return
    if not signature_header or "=" not in signature_header:
        logger.warning("Meta Facebook webhook rejected: missing signature header.")
        raise HTTPException(status_code=401, detail="Missing Facebook webhook signature.")

    algorithm_name, received_signature = signature_header.split("=", maxsplit=1)
    algorithm_name = algorithm_name.lower().strip()
    if algorithm_name == "sha256":
        digestmod = hashlib.sha256
    elif algorithm_name == "sha1":
        digestmod = hashlib.sha1
    else:
        logger.warning("Meta Facebook webhook rejected: unsupported signature algorithm=%s.", algorithm_name)
        raise HTTPException(status_code=401, detail="Unsupported Facebook webhook signature algorithm.")

    expected_signature = hmac.new(app_secret.encode("utf-8"), raw_body, digestmod).hexdigest()
    if not secrets.compare_digest(received_signature, expected_signature):
        logger.warning("Meta Facebook webhook rejected: invalid %s signature.", algorithm_name)
        raise HTTPException(status_code=401, detail="Invalid Facebook webhook signature.")


def _facebook_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            code = error.get("code")
            if message and code:
                return f"{message} (code {code})"
            if message:
                return str(message)
        return json.dumps(payload)[:500]
    return str(payload)[:500]


def _log_customer_inquiry(source: str, question: CustomerQuestion, answer: CustomerAnswer) -> None:
    matched_item = answer.matched_items[0] if answer.matched_items else None
    logger.info(
        "%s inquiry handled: customer_name=%r profile_id=%s post_id=%s conversation_id=%s incoming=%r "
        "matched_ebay_item_id=%s response=%r product_url=%s recommendations=%s stayed_in_messenger=%s "
        "redirected_to_ebay=%s needs_human=%s success=True",
        source,
        question.first_name,
        question.user_id,
        answer.social_post_id or question.metadata.get("post_id"),
        answer.messenger_conversation_id or question.metadata.get("conversation_id"),
        question.message[:500],
        answer.ebay_item_id or (matched_item.ebay_item_id if matched_item else None),
        answer.reply[:500],
        answer.ebay_listing_url or (matched_item.ebay_url if matched_item else None),
        [_item.ebay_item_id for _item in answer.recommended_items],
        answer.conversation_allowed,
        answer.redirect_to_ebay,
        answer.needs_human,
    )


async def _build_daily_report(report_date: date | None = None) -> dict[str, Any]:
    report = await build_daily_metricool_report(report_date)
    report["inventory"] = {"total_items": repository.count(), "store_sync": store_syncer.last_status}
    return report


async def _create_social_drafts_with_inventory_refresh(
    request: SocialDraftRequest,
) -> tuple[SocialDraftBatch, dict[str, Any]]:
    inventory_refresh = await _refresh_inventory_for_social_posts()
    if request.promote_all_inventory and inventory_refresh.get("status") != "ok":
        refresh_message = inventory_refresh.get("message")
        if not isinstance(refresh_message, str) or not refresh_message:
            refresh_message = "A fresh eBay API inventory sync did not complete."
        return (
            SocialDraftBatch(
                campaign_name="Daily all-inventory promotion",
                posts=[],
                notes=(
                    "Skipped automated inventory posts because the latest eBay API inventory "
                    f"was not confirmed. {refresh_message}"
                ),
            ),
            inventory_refresh,
        )
    batch = await create_social_drafts(request)
    _append_inventory_refresh_note(batch, inventory_refresh)
    return batch, inventory_refresh


async def _refresh_inventory_for_social_posts() -> dict[str, Any]:
    if not settings.sync_inventory_before_social_posts:
        return {
            "source": "pre-social-refresh",
            "status": "skipped",
            "message": "Automatic inventory refresh before social posts is disabled.",
            "ebay_sync": ebay_sync_status,
            "store_sync": store_syncer.last_status,
        }

    api_status = await _sync_ebay_api_inventory()
    store_status = store_syncer.last_status
    if api_status.get("status") == "ok":
        return {
            "source": "pre-social-refresh",
            "status": "ok",
            "message": "Inventory refreshed from the eBay API before social posts were generated.",
            "ebay_sync": api_status,
            "store_sync": store_status,
        }

    store_status = await store_syncer.sync()
    if store_status.get("status") == "ok":
        return {
            "source": "pre-social-refresh",
            "status": "fallback_ok",
            "message": "eBay API refresh did not complete; inventory refreshed from the public eBay store page fallback.",
            "ebay_sync": api_status,
            "store_sync": store_status,
        }

    if store_status.get("status") in {"cached", "fallback"}:
        return {
            "source": "pre-social-refresh",
            "status": str(store_status.get("status")),
            "message": "Inventory refresh did not complete; social posts used the best available cached inventory.",
            "ebay_sync": api_status,
            "store_sync": store_status,
        }

    return {
        "source": "pre-social-refresh",
        "status": "failed",
        "message": "Inventory refresh failed before social posts were generated; cached inventory was used if available.",
        "ebay_sync": api_status,
        "store_sync": store_status,
    }


def _append_inventory_refresh_note(batch: SocialDraftBatch, inventory_refresh: dict[str, Any]) -> None:
    message = inventory_refresh.get("message")
    if not isinstance(message, str) or not message:
        return
    separator = " " if batch.notes else ""
    batch.notes = f"{batch.notes}{separator}{message}"


def _inventory_refresh_zapier_fields(inventory_refresh: dict[str, Any]) -> dict[str, Any]:
    ebay_sync = inventory_refresh.get("ebay_sync")
    if not isinstance(ebay_sync, dict):
        ebay_sync = {}
    store_sync = inventory_refresh.get("store_sync")
    if not isinstance(store_sync, dict):
        store_sync = {}
    return {
        "inventory_refresh_status": inventory_refresh.get("status"),
        "inventory_refresh_message": inventory_refresh.get("message"),
        "inventory_refresh_source": inventory_refresh.get("source"),
        "ebay_sync_status": ebay_sync.get("status"),
        "ebay_sync_message": ebay_sync.get("message"),
        "ebay_sync_imported": ebay_sync.get("imported"),
        "ebay_sync_last_attempt_at": ebay_sync.get("last_attempt_at"),
        "store_sync_status": store_sync.get("status"),
        "store_sync_message": store_sync.get("message"),
        "store_sync_imported": store_sync.get("imported"),
        "store_sync_last_attempt_at": store_sync.get("last_attempt_at"),
    }


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


def _gmail_oauth_redirect_uri() -> str:
    return f"{settings.public_base_url.rstrip('/')}/oauth2callback"


def _sign_gmail_oauth_state() -> str:
    payload = {
        "ts": int(time.time()),
        "nonce": secrets.token_urlsafe(18),
    }
    encoded_payload = _urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _gmail_oauth_state_signature(encoded_payload)
    return f"{encoded_payload}.{signature}"


def _verify_gmail_oauth_state(value: str) -> bool:
    try:
        encoded_payload, signature = value.rsplit(".", 1)
    except ValueError:
        return False

    expected_signature = _gmail_oauth_state_signature(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        return False

    try:
        payload = json.loads(_urlsafe_b64decode(encoded_payload).decode("utf-8"))
        issued_at = int(payload["ts"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False

    return 0 <= time.time() - issued_at <= GMAIL_OAUTH_STATE_MAX_AGE_SECONDS


def _gmail_oauth_state_signature(encoded_payload: str) -> str:
    secret = _gmail_oauth_state_secret()
    digest = hmac.new(secret.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256).digest()
    return _urlsafe_b64encode(digest)


def _gmail_oauth_state_secret() -> str:
    if settings.webhook_shared_secret:
        return settings.webhook_shared_secret
    return gmail_oauth_credentials(settings=settings).client_secret


def _urlsafe_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _gmail_oauth_success_html(refresh_token: str) -> str:
    escaped_token = escape(refresh_token)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="robots" content="noindex">
  <title>Gmail connected</title>
</head>
<body>
  <h1>Gmail connected</h1>
  <p>Copy this value into Render for the <code>horizon-ai-agents</code> web service.</p>
  <pre>GMAIL_REFRESH_TOKEN_CURRENT={escaped_token}</pre>
  <p>After saving the environment variable, trigger the daily report cron again.</p>
</body>
</html>"""


def _parse_report_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="Report date must be a YYYY-MM-DD string.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Report date must use YYYY-MM-DD format.") from exc
