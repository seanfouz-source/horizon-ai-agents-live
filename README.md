# Horizon AI Agents

This is a starter agent hub for promoting an eBay store and answering product questions from Facebook, Instagram, TikTok, Manychat, Zapier, and Metricool workflows.

## What It Does

- Imports current eBay listings into a local inventory database.
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
- `POST /inventory/sync/store-page` refreshes from the configured default eBay store URL.
- `POST /inventory/sync/ebay` syncs from eBay Inventory API when `EBAY_ACCESS_TOKEN` is set.
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

1. The `render.yaml` blueprint includes a `horizon-daily-report-email` Cron Job scheduled at `10 8 * * *`.
2. Add Render environment variables: `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and optionally `SMTP_PORT`, `SMTP_SECURITY`, `REPORT_EMAIL_TO`, `REPORT_EMAIL_FROM`, and `REPORT_EMAIL_FROM_NAME`.
3. The Cron Job command is `python scripts/send_render_daily_report_email.py`.
4. For a manual test from the live web service, `POST /reports/daily/email?dry_run=true` prepares the email, and `POST /reports/daily/email` sends it.

Example social draft request:

```json
{
  "promote_all_inventory": true,
  "query": "all phones",
  "max_products_per_run": 50,
  "platforms": ["facebook", "instagram", "tiktok", "linkedin"],
  "tiktok_daily_post_cap": 3,
  "brand_name": "Horizon Wireless",
  "as_draft": false,
  "auto_publish": true
}
```

When `promote_all_inventory` is true, the app creates one Metricool payload per
in-stock listing. By default each payload cross-posts to every requested
platform, so 18 in-stock phones produce 18 scheduled Metricool posts instead of
only the first phone. The app staggers those posts across the daily schedule,
including Saturday and Sunday. When auto-publishing, TikTok is capped at
`tiktok_daily_post_cap` placements per scheduled day so TikTok's API does not
reject the run for too many automated posts; Facebook, Instagram, and LinkedIn
continue receiving the full queue. Product captions end with a visible `Buy on eBay:` line,
and the Zapier response also includes `metricool_link_url` fields for Metricool
link/URL mappings when that field is available. For Metricool's required
`Publication Date/Time` and `As draft` fields, the response includes both the
readable `metricool_publication_date_time` / `metricool_as_draft` fields and
Zapier's internal `publicationDate` / `draft` aliases.

## eBay Inventory

Start with CSV import from Seller Hub or your own listing export. Required columns are:

```text
sku,title,description,condition,price,currency,quantity,ebay_item_id,ebay_url,image_url,category,item_specifics
```

`item_specifics` should be JSON, such as:

```json
{"Brand":"Sony","Color":"Black","Size":"Large"}
```

Live sync uses the eBay Sell Inventory API and needs `EBAY_ACCESS_TOKEN`. The service fetches inventory items and offers, then stores SKU, title, quantity, image, price, and eBay listing URL when available.

## eBay Store URL Workaround

Until official eBay API access is ready, the app treats the ExactSpec public store page as the default inventory source:

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
