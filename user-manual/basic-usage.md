# Basic Usage

## Two Modes

`tele` has two modes with different use cases:

| Mode | Command | Best For |
|------|---------|----------|
| App | `tele --chat "name"` | One-off queries, scheduled jobs, full history |
| Bot | `tele --bot --chat "id" --exec "cmd"` | Continuous monitoring, automation |

---

## App Mode

### List available chats

```bash
# Use "me" for Saved Messages
uv run tele --chat "me"
```

### Get new messages

```bash
uv run tele --chat "chat_name"
```

This outputs JSON Lines to stdout. Each line is one message:

```json
{"id": 123, "text": "Hello world", "sender_id": 456, "date": "2024-01-15T10:00:00Z", "chat_id": 789, "status": "pending"}
```

### Search messages

```bash
uv run tele --chat "chat_name" --search "keyword"
```

### Filter messages

```bash
uv run tele --chat "chat_name" --filter 'contains("urgent")'
```

See [Filter Guide](filter-guide.md) for filter syntax.

### Process all messages (ignore history)

By default, `tele` only fetches new messages since your last run. Use `--full` to get all messages:

```bash
uv run tele --chat "chat_name" --full
```

### Mark messages as processed

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

### App Mode Options

| Option | Description |
|--------|-------------|
| `--chat, -c` | Chat name or ID (required) |
| `--search, -s` | Search query |
| `--filter, -f` | Filter expression |
| `--full` | Process all messages, not just new |
| `--mark` | Mark mode (read IDs from stdin) |
| `--reaction, -r` | Emoji for marking (default: ✅) |
| `--page-size` | Messages per output batch (default: 10) |
| `--limit, -l` | Max messages to fetch |
| `--help` | Show all options |

---

## Bot Mode

Bot mode runs as a foreground daemon, polling for new messages and processing them through an external command.

### Basic usage

```bash
# Process all messages the bot can see
uv run tele --bot --exec "my-processor"

# Filter to specific chat (optional)
uv run tele --bot --chat "-1001234567890" --exec "my-processor"
```

### What the bot can see

| Source | Messages received |
|--------|------------------|
| Private DMs | All messages |
| Group (privacy ON) | @mentions and commands only |
| Group (privacy OFF) | All messages |
| Channel (admin required) | All posts |

Set privacy mode via @BotFather: `/setprivacy`

### How it works

1. Bot polls for new messages from the specified chat
2. Applies `--filter` if provided (default: all messages)
3. Accumulates messages until `--page-size` reached OR `--interval` seconds of silence
4. Pipes batch to `--exec` command via stdin (JSON Lines)
5. Reads stdout for results with `status` field
6. Marks messages: ✅ for success, ❌ for failure

### The exec command

Your processor receives JSON Lines on stdin and should output JSON Lines on stdout.

#### Input format (what your processor receives)

```json
{"id": 123, "chat_id": -1001234567890, "text": "Hello world", "sender_id": 456, "date": "2024-01-15T10:00:00Z"}
```

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | number | Message ID (for marking) |
| `chat_id` | number | Chat/channel ID (for marking) |
| `text` | string/null | Message text content |
| `sender_id` | number/null | Sender's user ID |
| `date` | string/null | ISO 8601 timestamp |

**Optional fields (when present):**

| Field | Type | Description |
|-------|------|-------------|
| `is_forwarded` | boolean | Message is forwarded |
| `forward_from_id` | number/null | Original sender ID |
| `has_media` | boolean | Message has media attachment |
| `media_type` | string/null | Type: "photo", "video", "document", "audio", etc. |
| `reactions` | array | Existing reactions: `[{emoji, count}]` |

#### Output format (what your processor must return)

```json
{"id": 123, "chat_id": -1001234567890, "status": "success"}
```

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | number | Message ID being marked |
| `chat_id` | number | Chat ID (required for API) |
| `status` | string | `"success"` or `"failed"` |

#### Example processor (Python)

```python
#!/usr/bin/env python3
import sys
import json

for line in sys.stdin:
    msg = json.loads(line)

    # Your processing logic here
    text = msg.get("text", "")
    chat_id = msg["chat_id"]
    msg_id = msg["id"]

    # Determine result
    status = "success"  # or "failed"

    # Output result
    print(json.dumps({
        "id": msg_id,
        "chat_id": chat_id,
        "status": status
    }))
```

### Bot Mode Options

| Option | Description |
|--------|-------------|
| `--bot` | Enable bot mode |
| `--chat, -c` | Filter to specific chat ID (optional) |
| `--exec` | Command to process messages (required) |
| `--` | Pass remaining args to exec command |
| `--filter, -f` | Filter expression (default: all messages) |
| `--page-size` | Max messages per batch (default: 10) |
| `--interval` | Debounce seconds (default: 3) |
| `--mark` | Success reaction emoji (default: ✅) |
| `--failed-mark` | Failure reaction emoji (default: ❌) |

### Avoiding shell quoting issues

Use `--` to pass arguments directly to your command:

```bash
# Without -- (quoting hell)
uv run tele --bot --chat "123" --exec "python -c 'print(input())'"

# With -- (cleaner)
uv run tele --bot --chat "123" -- python -c "print(input())"
```

### At-least-once delivery

Bot mode guarantees no message loss, but may deliver duplicates if:

- Processing fails (non-zero exit)
- Marking fails
- Bot crashes

**Your processor must be idempotent** - handle the same message multiple times safely.

---

## How incremental processing works

### App Mode

`tele` tracks the last message ID processed in `~/.tele/state/`. On subsequent runs, it only fetches messages newer than that ID.

Use `--full` to ignore this and process everything.

### Bot Mode

`tele` tracks the last `update_id` processed. The offset only advances when:
1. The exec command exits successfully (exit 0)
2. Reactions are applied successfully

If either fails, messages will be re-delivered on the next poll.