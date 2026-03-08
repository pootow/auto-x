# Basic Usage

## List available chats

```bash
# Use "me" for Saved Messages
uv run tele --chat "me"
```

## Get new messages

```bash
uv run tele --chat "chat_name"
```

This outputs JSON Lines to stdout. Each line is one message:

```json
{"id": 123, "text": "Hello world", "sender_id": 456, "date": "2024-01-15T10:00:00Z", "chat_id": 789}
```

## Search messages

```bash
uv run tele --chat "chat_name" --search "keyword"
```

## Filter messages

```bash
uv run tele --chat "chat_name" --filter 'contains("urgent")'
```

See [Filter Guide](filter-guide.md) for filter syntax.

## Process all messages (ignore history)

By default, `tele` only fetches new messages since your last run. Use `--full` to get all messages:

```bash
uv run tele --chat "chat_name" --full
```

## Mark messages as processed

Add a reaction to track which messages you've handled:

```bash
# Pipe messages through your processor, then mark
uv run tele --chat "chat_name" | your-processor | uv run tele --mark
```

This reads message IDs from stdin and adds a ✅ reaction.

Use a different reaction:

```bash
uv run tele --mark --reaction "👍"
```

## Common options

| Option | Description |
|--------|-------------|
| `--chat, -c` | Chat name or ID (required) |
| `--search, -s` | Search query |
| `--filter, -f` | Filter expression |
| `--full` | Process all messages, not just new |
| `--mark` | Mark mode (read IDs from stdin) |
| `--reaction, -r` | Emoji for marking (default: ✅) |
| `--limit, -l` | Max messages to fetch |
| `--help` | Show all options |

## How incremental processing works

`tele` tracks the last message ID processed in `~/.tele/state/`. On subsequent runs, it only fetches messages newer than that ID.

This reduces API calls and avoids reprocessing.

Use `--full` to ignore this and process everything.