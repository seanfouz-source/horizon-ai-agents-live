# Horizon AI Agents

This is a starter agent hub for promoting an eBay store and answering product questions from Facebook, Instagram, TikTok, Manychat, Zapier, and Metricool workflows.

## What It Does

- Imports current active eBay listings into a local inventory database through the eBay API.
- Answers customer questions with an OpenAI-powered inventory agent.
- Returns Manychat Dynamic Block responses for Facebook and Instagram automations.
- Gives Zapier webhook endpoints for customer Q&A and social post generation.
- Produces Metricool-ready payloads that Zapier can map into Metricool's "Schedule Post" action.

## Launch Guides

- [Launch checklist](docs/launch-checklist.md)
- [Manychat payloads](docs/manychat-payloads.md)
- [Zapier and Metricool field map](docs/zapier-metricool-map.md)
- [Slow-mover social outreach](docs/slow-mover-outreach.md)

## Local Setup

1. Create a Python 3.11+ virtual environment and install dependencies:

   ```bash
   python3.12 -m venv .venv
   .venv/bin/python -m pip install -e '.[dev]'
   ```

2. Import sample inventory:

   ```bash
   .venv/bin/python scripts/import_inventory_csv.py data/inventory_sample.csv
   ```

3. Start the service:

   ```bash
   ./scripts/start_service.sh
   ```

4. Open:

   ```text
   http://127.0.0.1:8010/docs
   ```

## Main Endpoints

- `GET /health` checks that the service is running.
- `GET /inventory/search?q=keyboard` searches stock.
- `POST /inventory/import` imports JSON inventory items.
- `POST /inventory/import/ebay-store-page` imports public listing cards from an eBay store URL.
- `POST /inventory/sync/ebay` syncs active seller listings from the eBay API when `EBAY_ACCESS_TOKEN` is set.
- `POST /inventory/sync/store-page` refreshes from the configured default eBay store URL only as a fallback.
- `POST /webhooks/manychat` answers Manychat Dynamic Block or External Request calls.
- `POST /webhooks/zapier/customer-question` returns a JSON answer for Zapier.
- `POST /webhooks/zapier/social-drafts` creates Facebook, Instagram, and TikTok post drafts.
- `POST /webhooks/zapier/slow-mover-outreach` creates engagement-first posts for stale eBay items.
- `POST /webhooks/metricool/inbox` answers Metricool inbox/comment events routed through Zapier.
- `GET /reports/daily` returns a daily Metricool effectiveness report.
- `GET /reports/daily.md` returns the same report as email-ready Markdown.
- `GET /reports/daily.pdf` returns a polished PDF attachment.
- `GET` or `POST /webhooks/zapier/daily-report` returns Zapier-friendly report fields.

## Manychat Flow

Create a Dynamic Block or External Request in Manychat and send a JSON body like:

```json
{
  "message": "{{last_text_input}}",
  "channel": "instagram",
  "subscriber_id": "{{subscriber.id}}",
  "first_name": "{{first_name}}"
}
```

Point it to:

```text
https://your-public-service-url/webhooks/manychat
```

If you set `WEBHOOK_SHARED_SECRET`, send it as the `x-horizon-secret` header.

## Zapier And Metricool Flow

For product Q&A:

1. Trigger: Manychat, Metricool, or Webhooks by Zapier catches a new customer message.
2. Action: POST the message to `/webhooks/zapier/customer-question`.
3. Action: Send the returned `reply` back through Manychat or Metricool.

For advertising posts:

1. Trigger: Schedule by Zapier every day, new eBay listing, or manual webhook.
2. Action: POST a request to `/webhooks/zapier/social-drafts`.
3. Action: Use Looping by Zapier over the returned `metricool_*_items` fields, plus `publicationDate_items` and `draft_items`, then map each loop item into Metricool's `Schedule Post` action.

For stale eBay listings:

1. Trigger: Schedule by Zapier, a slow-mover report, or a manual webhook.
2. Action: POST slow item metrics to `/webhooks/zapier/slow-mover-outreach`.
3. Action: Loop over the returned Metricool fields for outreach posts, and connect `comment_keyword_items` to ManyChat keyword replies.

For daily reporting:

1. Trigger: Schedule by Zapier once per morning.
2. Action: Webhooks by Zapier `GET https://your-public-service-url/webhooks/zapier/daily-report`.
3. Optional query: `date=YYYY-MM-DD`. If omitted, the report uses yesterday in Central time.
4. Action: Email by Zapier, Gmail, Slack, or Google Sheets using `email_body` for the message and `attachment_url` for the report PDF.

GitHub Actions can send the same report without Zapier:

1. Workflow: `.github/workflows/daily-report-email.yml`, scheduled for `08:10 UTC` daily.
2. Script: `python scripts/send_daily_report_email.py`.
3. Required GitHub Secrets: `SMTP_HOST`, `SMTP_USERNAME`, and `SMTP_PASSWORD`.
4. Optional GitHub Secrets or Variables: `SMTP_PORT`, `SMTP_SECURITY`, `REPORT_BASE_URL`, `REPORT_EMAIL_TO`, `REPORT_EMAIL_FROM`, `REPORT_EMAIL_FROM_NAME`, and `WEBHOOK_SHARED_SECRET`.

Render can send the same report without Zapier or GitHub:

1. The `render.yaml` blueprint includes a `horizon-daily-report-email` Cron Job scheduled at `15 5 * * *`.
2. To send from Gmail, set `REPORT_EMAIL_PROVIDER=gmail`, `REPORT_EMAIL_FROM=sean.fouz@gmail.com`, and `GMAIL_SENDER=sean.fouz@gmail.com`.
3. Add Google OAuth variables to the web service in Render: `GMAIL_CLIENT_ID` plus either `GMAIL_CLIENT_SECRET`, `GMAIL_CLIENT_SECRET_FILE`, or `GMAIL_CLIENT_CREDENTIALS_FILE`. A Google OAuth JSON secret file can also be uploaded to Render as a secret file; Render mounts it at `/etc/secrets/<filename>`.
4. Add `https://horizon-ai-agents.onrender.com` as the Google OAuth JavaScript origin and `https://horizon-ai-agents.onrender.com/oauth2callback` as the authorized redirect URI.
5. Open `/gmail/oauth/start?secret=YOUR_WEBHOOK_SHARED_SECRET` on the Render web service, approve Gmail access, then copy the returned `GMAIL_REFRESH_TOKEN` into the Render web service environment.
6. The Cron Job runs `python scripts/post_render_daily_report_email.py`, which calls `POST https://horizon-ai-agents.onrender.com/reports/daily/email` and prints any error response body while Gmail and Metricool credentials stay on the web service.
7. For a manual test from the live web service, `POST /reports/daily/email?dry_run=true` prepares the email, and `POST /reports/daily/email` sends it.

Example social draft request:

```json
{
  "promote_all_inventory": true,
  "query": "all inventory",
  "max_products_per_run": 50,
  "platforms": ["facebook", "instagram", "tiktok", "linkedin"],
  "tiktok_daily_post_cap": 3,
  "brand_name": "Horizon Wireless",
  "sale_name": "Horizon Wireless Summer Sale",
  "store_url": "https://www.ebay.com/str/exactspec",
  "sale_media_url": "https://raw.githubusercontent.com/seanfouz-source/horizon-ai-agents-live/main/assets/horizon-summer-sale-square.jpg",
  "as_draft": false,
  "auto_publish": true
}
```

When `promote_all_inventory` is true, the app creates one Metricool payload per
eligible active eBay listing, using an Instagram-safe square version of the eBay
store's July Summer Sale banner as the default campaign media. If `sale_media_url` and `media_url` are omitted, the
app falls back to the selected eBay product image when available. Metricool remains the public social scheduler; the app only prepares
Metricool-ready payloads and records local scheduling history to prevent reruns
from duplicating posts. The hard default cap is 2 Metricool posts per calendar
day total, using `METRICOOL_MORNING_POST_TIME` and
`METRICOOL_EVENING_POST_TIME`. Items are not reposted within
`METRICOOL_REPOST_COOLDOWN_DAYS` by default. Summer Sale product captions include
the eBay store page plus a visible `View this listing:` eBay item link, and the
Zapier response also includes
`metricool_link_url` fields for Metricool link/URL mappings when that field is
available. For Metricool's required `Publication Date/Time` and `As draft`
fields, the response includes both the readable
`metricool_publication_date_time` / `metricool_as_draft` fields and Zapier's
internal `publicationDate` / `draft` aliases.

## eBay Inventory

Start with CSV import from Seller Hub or your own listing export. Required columns are:

```text
sku,title,description,condition,price,currency,quantity,ebay_item_id,ebay_url,image_url,category,item_specifics
```

`item_specifics` should be JSON, such as:

```json
{"Brand":"Sony","Color":"Black","Size":"Large"}
```

Live sync can use either `EBAY_ACCESS_TOKEN` or long-lived OAuth refresh
credentials. eBay access tokens are short-lived, so production should set
`EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, and `EBAY_REFRESH_TOKEN`; the app will
exchange the refresh token for a fresh access token before each inventory sync.
`EBAY_OAUTH_SCOPES` defaults to `https://api.ebay.com/oauth/api_scope`, which is
enough for the public Browse API fallback. Add eBay Sell Inventory scopes there
only if the refresh token was authorized for them.

The service tries the eBay Sell Inventory API first, then falls back to the eBay
Buy Browse API seller search/details endpoint when Seller Hub listings are not
represented as Sell Inventory records. It stores active, available listings
only: item ID, title, URL, price, condition, quantity, category, listing status,
best image URL, all returned image URLs, short description, and item specifics.

By default, social draft endpoints refresh inventory before generating Metricool
payloads (`SYNC_INVENTORY_BEFORE_SOCIAL_POSTS=true`). This lets newly changed
eBay listing photos flow into future `media_01` values automatically. If the
eBay API token is invalid or eBay does not return data, the app tries the public
store-page fallback and includes `inventory_refresh_*`, `ebay_sync_*`, and
`store_sync_*` fields in Zapier responses so the Zap can show whether fresh
listing photos were used or cached inventory was used.

## eBay Store URL Workaround

The app now uses the eBay API as the default inventory source. The ExactSpec
public store page remains configured only as a fallback:

```text
https://www.ebay.com/str/exactspec
```

The app tries to refresh from that store page when the service starts. You can also refresh it manually:

```bash
.venv/bin/python scripts/import_ebay_store_url.py
```

Or through the API:

```text
POST /inventory/sync/store-page
```

To override the store URL for a one-off import:

```bash
.venv/bin/python scripts/import_ebay_store_url.py "https://www.ebay.com/str/YOUR-STORE" 3
```

If eBay blocks a refresh, the app keeps the last successful inventory in the database. This workaround can usually capture public title, price, image, item ID, and listing URL. It cannot reliably capture exact quantity, private SKU, private item specifics, shipping rules, or unpublished inventory, so imported items are marked with `source = ebay-store-page` and `quantity = 1`.
