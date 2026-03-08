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
  api_id: 12345           # Your API ID
  api_hash: "abc123..."   # Your API hash
  session_name: "tele_tool"  # Session file name

defaults:
  chat: "work"            # Default chat (optional)
  reaction: "✅"          # Default reaction for marking
  batch_size: 100         # Messages per API call
```

## Environment variables

Override config file values:

```bash
export TELEGRAM_API_ID=12345
export TELEGRAM_API_HASH="abc123..."

uv run tele --chat "me"
```

Environment variables take priority over the config file.

## Session files

Location: `~/.tele/tele_tool.session`

This stores your Telegram authentication. Keep it secure - anyone with this file can access your account.

### Multiple sessions

Use different sessions for different purposes:

```yaml
telegram:
  session_name: "work_bot"  # Creates ~/.tele/work_bot.session
```

## State files

Location: `~/.tele/state/{chat_id}.json`

Tracks incremental processing:

```json
{
  "last_message_id": 12345,
  "last_processed_at": "2024-01-15T10:30:00Z"
}
```

### Reset state for a chat

```bash
# Delete state file to reprocess all messages
rm ~/.tele/state/CHAT_ID.json
```

Or use `--full` to ignore state temporarily.

## Troubleshooting

### "API ID not found"

Set credentials in config file or environment variables.

### "Not authorized"

Run interactively once to log in:

```bash
uv run tele --chat "me"
```

Enter your phone number and verification code when prompted.

### "Could not resolve chat"

The chat name doesn't match exactly. Try:

- Using the chat ID (negative number for groups/channels)
- Checking the exact name in Telegram
- Using `@username` for public channels

### Session errors

If authentication issues persist:

```bash
# Remove session and re-login
rm ~/.tele/*.session
uv run tele --chat "me"
```