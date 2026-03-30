# Multi-Endpoint Routing for Bot API

## Summary

Allow configuring multiple Bot API endpoints with method-level routing, enabling use of local Bot API servers for specific operations (e.g., large file uploads) while using official Telegram servers for others.

## Motivation

Local Bot API servers can send files up to 2GB, while the official endpoint has a 50MB limit. Users want to route specific API methods to different endpoints based on their capabilities.

## Configuration

### New Config Format

```yaml
telegram:
  bot_token: your_bot_token
  bot_api_endpoint: api.telegram.org  # Default endpoint (fallback)

  # Endpoint routing rules
  endpoint_routing:
    "local-bot-api.local:8081":
      methods: [sendVideo, sendPhoto, sendMessage]
    "api.telegram.org":
      methods: [getUpdates, setMessageReaction]
```

### Rules

1. `bot_api_endpoint` is the default endpoint
2. Methods listed in `endpoint_routing` use their assigned endpoint
3. Methods not listed anywhere use the default endpoint
4. If a method appears in multiple routing entries, the last one wins

### Supported Methods

| Method | Description |
|--------|-------------|
| `getUpdates` | Fetch new messages (polling) |
| `setMessageReaction` | Add emoji reaction |
| `sendVideo` | Send video file |
| `sendPhoto` | Send image file |
| `sendMessage` | Send text message |

## Implementation

### Config Layer

**File: `tele/config.py`**

- Add `endpoint_routing` field to `TelegramConfig` dataclass as `Dict[str, List[str]]`
- Create helper method `get_endpoint_for_method(method: str) -> str`
  - Iterate through routing dict, find method in any `methods` list
  - Return matching endpoint, or fallback to `bot_api_endpoint`

### BotClient Layer

**File: `tele/bot_client.py`**

- Pass `endpoint_routing` config to BotClient constructor
- Modify `_call_api_internal` to look up endpoint for each method before building URL
- No method name translation needed - use API method names directly

### Backward Compatibility

- If `endpoint_routing` is not configured, all methods use `bot_api_endpoint`
- Existing configs work without modification

## Testing

- Unit tests for config parsing with routing scenarios
- Unit tests for endpoint lookup logic (default, routed, fallback)
- Integration test verifying correct URL construction per method