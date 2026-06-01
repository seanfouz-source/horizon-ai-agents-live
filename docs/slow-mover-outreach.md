# Slow-Mover Social Outreach

Use this workflow for eBay items that are not getting enough movement. It
creates engagement-first social posts, unique comment keywords, ManyChat reply
copy, and Metricool-ready payloads.

## Endpoint

```text
POST https://YOUR-PUBLIC-URL/webhooks/zapier/slow-mover-outreach
```

Local API test endpoint:

```text
POST /agent/slow-mover-outreach
```

## Basic Zapier Body

```json
{
  "query": "all phones",
  "max_items": 5,
  "angles_per_item": 2,
  "platforms": ["facebook", "instagram", "tiktok", "linkedin"],
  "cross_post_to_all_platforms": true,
  "brand_name": "Horizon Wireless",
  "as_draft": true,
  "auto_publish": false
}
```

Start with drafts. After the copy and cadence look good, switch to:

```json
{
  "as_draft": false,
  "auto_publish": true
}
```

## Better Slow-Mover Metrics

If Zapier can pull eBay listing performance into the request, pass metrics so
the outreach queue prioritizes the weakest items first:

```json
{
  "slow_mover_metrics": [
    {
      "sku": "EBAY-366419891578",
      "listing_age_days": 21,
      "days_since_sale": 21,
      "views": 8,
      "watchers": 0,
      "quantity_sold": 0,
      "notes": "No sale after latest price review"
    }
  ],
  "max_items": 5,
  "angles_per_item": 2,
  "brand_name": "Horizon Wireless",
  "as_draft": true,
  "auto_publish": false
}
```

If metrics are missing, the app falls back to in-stock phone inventory and
labels the priority reason as a fallback.

## Zapier Flow

```text
Schedule by Zapier -> Webhooks by Zapier -> Looping by Zapier -> Metricool Schedule Post
```

Loop over `metricool_payloads` or the returned `metricool_*_items` arrays.

Metricool loop mapping:

```text
Facebook -> metricool_facebook_items
Instagram -> metricool_instagram_items
Tiktok -> metricool_tiktok_items
LinkedIn -> metricool_linkedin_items
Publication Date/Time -> publicationDate_items
Post content / Text -> metricool_post_content_items
Media 01 -> metricool_media_01_items
As draft -> draft_items
Auto publish -> metricool_auto_publish_items
Post type -> metricool_post_type_items
```

ManyChat/comment tracking fields:

```text
Comment keyword -> comment_keyword_items or metricool_comment_keyword_items
ManyChat reply -> manychat_reply_items or metricool_manychat_reply_items
Slow-mover reason -> slow_mover_reason_items
SKU -> slow_mover_sku_items
```

The generated captions ask shoppers to comment a unique keyword such as
`LINK891578`. Connect those keywords in ManyChat to the matching reply text.

## Outreach Rules

- Use public posts and inbound comments/DMs.
- Do not cold-DM group members.
- Review Facebook Group rules before posting in groups.
- Do not invent discounts, scarcity, warranties, shipping promises, or bundle
  terms that are not actually available.
