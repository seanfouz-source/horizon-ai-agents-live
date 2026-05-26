# Manychat Payloads

Use these payloads in Manychat Dynamic Blocks or External Requests.

Replace `https://YOUR-PUBLIC-URL` with the public HTTPS URL for the agent hub.

## Instagram DM Product Q&A

Request URL:

```text
https://YOUR-PUBLIC-URL/webhooks/manychat
```

Method:

```text
POST
```

Headers:

```text
Content-Type: application/json
x-horizon-secret: YOUR_SHARED_SECRET
```

Body:

```json
{
  "message": "{{last_text_input}}",
  "channel": "instagram",
  "subscriber_id": "{{subscriber.id}}",
  "first_name": "{{first_name}}",
  "inbox_chat_url": "{{inbox_chat_url}}"
}
```

The agent hub returns Manychat Dynamic Block format:

```json
{
  "version": "v2",
  "content": {
    "type": "instagram",
    "messages": [
      {
        "type": "text",
        "text": "Reply text appears here"
      }
    ],
    "actions": [],
    "quick_replies": []
  }
}
```

## Facebook Messenger Product Q&A

Request URL:

```text
https://YOUR-PUBLIC-URL/webhooks/manychat
```

Body:

```json
{
  "message": "{{last_text_input}}",
  "channel": "facebook",
  "subscriber_id": "{{subscriber.id}}",
  "first_name": "{{first_name}}",
  "inbox_chat_url": "{{inbox_chat_url}}"
}
```

## Recommended Manychat Flow

1. Trigger on keyword, comment-to-DM, or default reply.
2. Add a Dynamic Block named `Ask Horizon Inventory Agent`.
3. Send the body above.
4. Add a fallback block that says a human will follow up if the external request fails.
5. Test with one phrase, such as `Do you have a blue switch keyboard?`
