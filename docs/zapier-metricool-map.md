# Zapier And Metricool Field Map

Use this guide for the two main Zaps.

## Zap 1: Customer Questions To AI Reply

Trigger options:

- Manychat new message
- Metricool new inbox conversation
- Webhooks by Zapier Catch Hook

Action:

```text
Webhooks by Zapier -> Custom Request
```

Method:

```text
POST
```

URL:

```text
https://YOUR-PUBLIC-URL/webhooks/zapier/customer-question
```

Headers:

```text
Content-Type: application/json
x-horizon-secret: YOUR_SHARED_SECRET
```

Body:

```json
{
  "message": "MESSAGE_FROM_TRIGGER",
  "channel": "instagram",
  "user_id": "USER_OR_SUBSCRIBER_ID",
  "first_name": "FIRST_NAME"
}
```

Use the response field named `reply` as the message text in the next Manychat or Metricool action.

## Zap 2: Generate Social Posts For Metricool

Trigger options:

- Manual Zapier trigger
- Schedule by Zapier
- New row in a spreadsheet
- New item imported to inventory

Action:

```text
Webhooks by Zapier -> Custom Request
```

Method:

```text
POST
```

URL:

```text
https://YOUR-PUBLIC-URL/webhooks/zapier/social-drafts
```

Body:

```json
{
  "query": "keyboard",
  "platforms": ["facebook", "instagram", "tiktok"],
  "posts_per_platform": 1,
  "brand_name": "Horizon",
  "as_draft": false,
  "auto_publish": true
}
```

When `publish_after` is omitted, the agent chooses the next weekday busy window
in Central time: Monday 12:30 or 15:30; Tuesday-Thursday 12:30, 14:30, or
16:30; Friday 14:30 or 16:30.

Response fields:

```text
metricool_payloads
metricool_publication_date_time
metricool_post_content
metricool_facebook
metricool_instagram
metricool_tiktok
metricool_as_draft
metricool_auto_publish
metricool_post_type
```

Each item in `metricool_payloads` maps to one Metricool `Schedule Post` action.
For the simplest Zapier setup, map the first post from the flat `metricool_*`
fields. Use `metricool_payloads` only when you are building a loop for multiple
Metricool posts.

## Metricool Schedule Post Mapping

For the first generated post, map these flat Zapier fields:

```text
Brand Name -> choose the connected Metricool brand in the dropdown
Facebook -> metricool_facebook
Instagram -> metricool_instagram
Tiktok -> metricool_tiktok
Publication Date/Time -> metricool_publication_date_time
Post content / Text -> metricool_post_content
Media 01 -> leave blank unless metricool_media_01 has a value
As draft -> metricool_as_draft
Auto publish -> metricool_auto_publish
Post type -> POST
```

Optional tracking fields:

```text
Product SKU -> product_sku
Product Title -> product_title
eBay URL -> ebay_url
```

Review-first mode:

```text
As draft: true
Auto publish: false
```

Auto-publish mode:

```text
As draft: false
Auto publish: true
```

Review-first mode sends generated posts to Metricool for approval. Auto-publish
mode lets Metricool publish at the scheduled time.

For auto-publish, the flat Instagram field is only true when a media URL exists,
and the flat TikTok field is only true when a TikTok-safe media URL exists. The
app uses generated `.jpg` product cards by default because TikTok Business photo
posts reject `.png` media.
