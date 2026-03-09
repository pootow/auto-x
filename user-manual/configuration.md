# Configuration

## Config file location

Default: `~/.tele/config.yaml`

Custom location:

```bash
uv run tele --config /path/to/config.yaml --chat "me"
```

## Config file format

```yaml
telegram:
  # App mode credentials
  api_id: 12345           # Your API ID
  api_hash: "abc123..."   # Your API hash
  session_name: "tele_tool"  # Session file name

  # Bot mode credentials
  bot_token: "123456:ABC..."  # Bot token from @BotFather

defaults:
  chat: "work"            # Default chat (optional)
  reaction: "✅"          # Success reaction for marking
  failed_reaction: "❌"   # Failure reaction (bot mode)
  batch_size: 100         # Messages per API call (app mode)
  page_size: 10           # Messages per batch (bot mode)
  interval: 3             # Debounce seconds (bot mode)
```

## Environment variables

Override config file values:

### App Mode

```bash
export TELEGRAM_API_ID=12345
export TELEGRAM_API_HASH="abc123..."

uv run tele --chat "me"
```

### Bot Mode

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."

uv run tele --bot --chat "-1001234567890" --exec "processor"
```

Environment variables take priority over the config file.

## Session files

**App Mode:** `~/.tele/tele_tool.session`

This stores your Telegram authentication. Keep it secure - anyone with this file can access your account.

### Multiple sessions

Use different sessions for different purposes:

```yaml
telegram:
  session_name: "work_bot"  # Creates ~/.tele/work_bot.session
```

## State files

### App Mode

Location: `~/.tele/state/{chat_id}.json`

Tracks incremental processing:

```json
{
  "last_message_id": 12345,
  "last_processed_at": "2024-01-15T10:30:00Z"
}
```

### Bot Mode

Location: `~/.tele/state/bot_{chat_id}.json`

Tracks last processed update:

```json
{
  "last_update_id": 456,
  "last_processed_at": "2024-01-15T10:30:00Z"
}
```

### Reset state for a chat

```bash
# App mode
rm ~/.tele/state/CHAT_ID.json

# Bot mode
rm ~/.tele/state/bot_CHAT_ID.json
```

Or use `--full` to ignore state temporarily (app mode only).

## Troubleshooting

### "API ID not found" (App Mode)

Set credentials in config file or environment variables.

### "BOT_TOKEN required" (Bot Mode)

Set `TELEGRAM_BOT_TOKEN` or add to config file.

### "Not authorized" (App Mode)

Run interactively once to log in:

```bash
uv run tele --chat "me"
```

Enter your phone number and verification code when prompted.

### "Bot not in chat" (Bot Mode)

For reactions to work, the bot needs permission:
- Private chat: Works by default
- Group chat: Bot needs permission to add reactions
- Channel: Bot must be admin

If reactions fail, check bot permissions.

### "Could not resolve chat" (App Mode)

The chat name doesn't match exactly. Try:

- Using the chat ID (negative number for groups/channels)
- Checking the exact name in Telegram
- Using `@username` for public channels

### Session errors (App Mode)

If authentication issues persist:

```bash
# Remove session and re-login
rm ~/.tele/*.session
uv run tele --chat "me"
```

### Bot mode duplicates messages

Bot mode guarantees at-least-once delivery. If processing fails, messages may be re-delivered. Your processor should be idempotent (handle same message multiple times safely).