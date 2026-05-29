# Facebook Group Outreach Workflow

This workflow keeps Horizon Wireless visible in relevant Facebook Groups without
using risky auto-join, auto-post, scraping, or cold-message behavior.

## What The Agent Can Do

- Review candidate group names, URLs, rules, audience notes, and member counts.
- Score each group for Horizon Wireless eBay and wholesale relevance.
- Draft join request answers for a human to submit.
- Draft group posts using the wholesale or eBay retail campaign videos.
- Draft replies to group comments or member questions.
- Flag whether a reply can be auto-sent or must stay manual-review.

## What The Agent Must Not Do

- Auto-join Facebook Groups.
- Scrape group members.
- Cold-message group members.
- Auto-post into a Facebook Group unless Meta, the group, and the connected tool
  explicitly support it.
- Auto-reply to Facebook Group comments from an unsupported automation path.

## Group Outreach Plan

Request:

```text
POST https://YOUR-PUBLIC-URL/agent/group-outreach-plan
```

Body:

```json
{
  "campaign_video": "wholesale",
  "campaign_goal": "Find reseller and wholesale phone buyer communities for Horizon Wireless.",
  "audience_keywords": ["phone resellers", "electronics wholesale", "repair shops"],
  "group_leads": [
    {
      "name": "Phone Resellers USA",
      "url": "https://facebook.com/groups/example",
      "member_count": 12000,
      "rules_text": "No spam. Business posts allowed on Fridays.",
      "allows_promotions": true
    }
  ]
}
```

Response includes `candidate_groups`, `join_request_draft`, `post_drafts`, and
`compliance_checklist`.

## Group Reply Drafts

Request:

```text
POST https://YOUR-PUBLIC-URL/agent/group-reply
```

Body for a group comment:

```json
{
  "message": "Do you have any unlocked Samsung phones?",
  "group_name": "Phone Resellers USA",
  "interaction_type": "group_comment",
  "user_opted_in": false
}
```

The response will include:

```json
{
  "manual_review_required": true,
  "can_auto_send": false
}
```

Body for an opted-in inbox message:

```json
{
  "message": "Can you send me the eBay link?",
  "interaction_type": "page_dm",
  "user_opted_in": true
}
```

The response can include:

```json
{
  "manual_review_required": false,
  "can_auto_send": true
}
```

Only use `can_auto_send: true` when the message is coming through a supported
inbound DM or inbox trigger, such as Messenger, Instagram DM, or another
approved Horizon-owned channel.

## Zapier Hook

For group comments captured by a manual workflow, spreadsheet, or approved
third-party trigger:

```text
POST https://YOUR-PUBLIC-URL/webhooks/zapier/group-reply
```

Include the same body as `/agent/group-reply`. Map the returned `reply` into a
review queue unless `can_auto_send` is true.
