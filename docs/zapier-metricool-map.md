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

Video campaign body:

```json
{
  "campaign_video": "wholesale",
  "campaign_goal": "Promote Horizon Wireless wholesale device availability to resellers and bulk buyers.",
  "platforms": ["facebook", "instagram", "tiktok", "linkedin"],
  "posts_per_platform": 1,
  "brand_name": "Horizon Wireless",
  "as_draft": false,
  "auto_publish": true
}
```

Use `campaign_video: "ebay-retail-store"` for the eBay retail store video.
The public media URLs are:

```text
https://YOUR-PUBLIC-URL/media/campaigns/wholesale.mp4
https://YOUR-PUBLIC-URL/media/campaigns/ebay-retail-store.mp4
```

When `publish_after` is omitted, the agent staggers posts throughout every day
in Central time: 07:30, 09:00, 10:30, 12:00, 13:30, 15:00, 16:30, 18:00,
19:30, 21:00, and 22:30. If more posts are generated than slots left today,
the schedule continues on the next day.

Response fields:

```text
metricool_payloads
metricool_publication_date_time
metricool_post_content
metricool_facebook
metricool_instagram
metricool_tiktok
metricool_linkedin
metricool_media_01
metricool_publish_to_facebook_groups
metricool_facebook_groups
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
LinkedIn -> metricool_linkedin
Publication Date/Time -> metricool_publication_date_time
Post content / Text -> metricool_post_content
Media 01 -> metricool_media_01
As draft -> metricool_as_draft
Auto publish -> metricool_auto_publish
Post type -> POST
```

If the Metricool Zap action exposes Facebook Group destination fields, map:

```text
Publish to Facebook Groups -> metricool_publish_to_facebook_groups
Facebook Groups / Destinations -> metricool_facebook_groups
```

If those fields are not available, schedule the post to the connected Facebook
Page and share it manually to approved groups. Manychat's Facebook comment
automation works on Page posts, not Facebook Group posts.

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
