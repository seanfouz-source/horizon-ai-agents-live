# Horizon AI Agents Launch Checklist

Use this checklist to move from the local demo to live Facebook, Instagram, TikTok, Manychat, Zapier, Metricool, and eBay workflows.

## 1. Start The Agent Hub

From the project folder:

```bash
./scripts/start_service.sh
```

Open:

```text
http://127.0.0.1:8010/docs
```

Local testing works on your computer. Manychat, Zapier, and Metricool need a public HTTPS URL before they can call the hub. The local service listens on port `8010` unless you start it with a different `PORT`.

## 2. Choose A Public URL

For a quick test, use a secure tunnel such as ngrok or Cloudflare Tunnel that points to local port `8010`.

For production, deploy the service to a hosted server that supports:

- Python 3.11 or newer
- HTTPS
- environment variables
- a persistent database or scheduled inventory import

Do not rely on the local SQLite file for production unless the server has persistent disk storage.

## 3. Load Real eBay Inventory

Start with a Seller Hub CSV export:

```bash
.venv/bin/python scripts/import_inventory_csv.py path/to/your-ebay-export.csv
```

The CSV should include:

```text
sku,title,description,condition,price,currency,quantity,ebay_item_id,ebay_url,image_url,category,item_specifics
```

If the eBay export has different column names, make a copy and rename the columns before import.

If you cannot access the eBay API or export CSV yet, use the public store URL workaround. ExactSpec is already configured as the default:

```bash
.venv/bin/python scripts/import_ebay_store_url.py
```

The app also tries this refresh automatically when it starts, and you can schedule a Zapier webhook or cron job to call:

```text
POST https://YOUR-PUBLIC-URL/inventory/sync/store-page
```

This is good enough for basic Q&A and social posts, but it only sees public listing-card data. If eBay blocks a refresh, the database keeps the last successful inventory.

## 4. Connect Manychat

Create a Manychat Dynamic Block or External Request that sends the shopper's message to:

```text
https://YOUR-PUBLIC-URL/webhooks/manychat
```

Use the body in [manychat-payloads.md](./manychat-payloads.md).

## 5. Connect Zapier

Create two Zaps:

- Customer replies: incoming Manychat or Metricool message to `/webhooks/zapier/customer-question`
- Social posts: schedule/manual trigger to `/webhooks/zapier/social-drafts`, then Metricool Schedule Post

Use the field map in [zapier-metricool-map.md](./zapier-metricool-map.md).

## 6. Connect Metricool

Use Zapier's Metricool action named `Schedule Post`.

Start with `as_draft = true` and `auto_publish = false`. That keeps the first posts in Metricool for human approval before anything goes live.

For the Horizon Wireless videos, use the same social-drafts webhook with:

```json
{
  "campaign_video": "wholesale",
  "promote_all_inventory": true,
  "query": "all phones",
  "max_products_per_run": 50,
  "platforms": ["facebook", "instagram", "tiktok", "linkedin"],
  "brand_name": "Horizon Wireless",
  "as_draft": false,
  "auto_publish": true
}
```

Then repeat with:

```json
{
  "campaign_video": "ebay-retail-store",
  "promote_all_inventory": true,
  "query": "all phones",
  "max_products_per_run": 50,
  "platforms": ["facebook", "instagram", "tiktok", "linkedin"],
  "brand_name": "Horizon Wireless",
  "as_draft": false,
  "auto_publish": true
}
```

The app serves the videos at `/media/campaigns/wholesale.mp4` and
`/media/campaigns/ebay-retail-store.mp4` so Metricool receives public HTTPS MP4
links instead of local files.

For daily inventory coverage, the Zap must loop over the returned
`metricool_*_items` arrays. The flat `metricool_*` fields are only the first
post and are useful for testing one item.

Facebook Groups are only safe to automate when the group and scheduler support
the destination directly. If the Metricool Zap action does not show a group
destination field, schedule to the Facebook Page and share into approved groups
manually.

## 7. Go Live Carefully

Before turning on automation:

- Test with one product and one platform.
- Confirm the agent gives correct prices and stock counts.
- Confirm links open the right eBay listings.
- Keep replies short and product-specific.
- Keep all scheduled social posts as drafts until you approve the style.

## 8. Facebook Group Outreach

Use [facebook-group-outreach.md](./facebook-group-outreach.md) for group
research, join-request drafts, group post drafts, and group reply drafts.

Keep Facebook Group comments manual-review unless the user has messaged Horizon
through a supported inbox/DM flow. The app returns `can_auto_send` so Zapier or
Manychat can route safe inbound DMs differently from group comments.
