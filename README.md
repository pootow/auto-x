# tele - Telegram Message Processing Pipeline

A command-line tool for processing Telegram messages with filtering, incremental processing, and pipeline integration.

## Features

- **Message fetching**: Get messages from chats with incremental support
- **Search**: Use Telegram's search API to find messages
- **DSL filtering**: Filter messages using a powerful expression language
- **Pipeline integration**: Output to stdout for downstream processing
- **Mark processed messages**: Add reactions to track processed messages
- **Bot mode**: Daemon mode for continuous message processing
- **Persistence & Retry**: Crash recovery with pending queue and retry logic
- **Rich Reply**: Processors can return rich media replies

## Installation

```bash
pip install tele
```

Or install from source:

```bash
cd auto-x
pip install -e .
```

## Configuration

Create a config file at `~/.tele/config.yaml`:

```yaml
telegram:
  api_id: 12345  # Or set TELEGRAM_API_ID env var
  api_hash: "your_api_hash"  # Or set TELEGRAM_API_HASH env var
  session_name: "tele_tool"

defaults:
  chat: "default_chat_name"
  reaction: "✅"
  batch_size: 100
```

Get your API credentials from https://my.telegram.org/apps.

## Usage

### App Mode (MTProto API)

```bash
# Get new messages from a chat
tele --chat "chat_name"

# Search messages
tele --chat "chat_name" --search "keywords"

# Filter messages with DSL
tele --chat "chat_name" --filter 'contains("important") && !has_reaction("✅")'

# Full processing (ignore incremental state)
tele --chat "chat_name" --full

# Pipeline: filter → process → mark
tele --chat "chat_name" --filter 'contains("important")' | \
  your_processor | \
  tele --mark --reaction "✅"
```

### Bot Mode (Bot API)

```bash
# Start daemon monitoring a chat
tele --bot --chat 12345 --exec "my-processor"

# Use -- to pass command with args
tele --bot --chat 12345 -- python processor.py --arg value

# Retry dead-letter messages
tele --retry-dead ~/.tele/state/bot_123_dead.jsonl
```

## DSL Filter Expressions

The filter DSL supports:

### Functions
- `contains("keyword")` - Message text contains keyword
- `has_reaction("✅")` - Message has specified reaction

### Fields
- `sender_id` - Sender's user ID
- `sender_name` - Sender's name
- `message_id` - Message ID
- `date` - Message date
- `is_forwarded` - Is a forwarded message
- `has_media` - Contains media

### Operators
- `&&` - Logical AND
- `||` - Logical OR
- `!` - Logical NOT
- `==`, `!=`, `<`, `<=`, `>`, `>=` - Comparisons

### Examples

```bash
# Messages containing "urgent" or "important"
tele --chat "work" --filter 'contains("urgent") || contains("important")'

# Unprocessed messages from specific user
tele --chat "support" --filter '!has_reaction("✅") && sender_id == 12345678'

# Messages from a specific date
tele --chat "news" --filter 'date > "2024-01-01"'
```

## Output Format

Messages are output as JSON Lines (one JSON object per line):

```json
{"id": 123, "text": "Message content", "sender_id": 456, "date": "2024-01-15T10:00:00Z", "chat_id": 789}
```

## Processor Protocol

Processors read JSON Lines from stdin and write results to stdout.

### Input Format

Each line is a JSON object with message data.

### Output Format

Each result must include `id`, `chat_id`, and `status`:

```json
{"id": 123, "chat_id": 456, "status": "success"}
```

### Status Values

| Status | Meaning | Action |
|--------|---------|--------|
| `success` | Processed successfully | Remove from pending, mark ✅ |
| `error` | Retriable failure | Retry up to 3 times, then dead-letter |
| `fatal` | Non-retriable | Remove from pending, log to fatal.jsonl |

### Rich Reply

Processors can return a `reply` array with text and media:

```json
{
  "id": 123,
  "chat_id": 456,
  "status": "success",
  "reply": [
    {
      "text": "# Video Title\n_Duration: 5:30_",
      "media": {"type": "video", "url": "https://..."}
    }
  ]
}
```

**Media types:**
- `video` - Send video by URL (must be ≤50MB)
- `image` - Send photo by URL

Each reply item is sent as a separate Telegram message.

## Persistence & Retry

### File Structure

```
~/.tele/state/
├── bot_{chat_id}.json           # Offset state
├── bot_{chat_id}_pending.jsonl  # Messages waiting to be processed
├── bot_{chat_id}_dead.jsonl     # Retriable errors after 3 retries
└── bot_{chat_id}_fatal.jsonl    # Fatal errors (no retry value)
```

### Retry Logic

- Processor crashes: retry up to 3 times with exponential backoff (5s, 15s, 45s)
- After 3 failures: move to dead-letter queue
- Fatal errors (404, 403, etc.): no retry, logged to fatal.jsonl

### Manual Retry

```bash
# View dead letters
cat ~/.tele/state/bot_123_dead.jsonl

# Retry with original processor
tele --retry-dead ~/.tele/state/bot_123_dead.jsonl

# Retry with different processor
tele --retry-dead ~/.tele/state/bot_123_dead.jsonl --exec "new-processor"
```

## Incremental Processing

The tool tracks processed messages in `~/.tele/state/{chat_id}.json`:

```json
{
  "last_message_id": 12345,
  "last_processed_at": "2024-01-15T10:30:00Z"
}
```

Use `--full` to process all messages, ignoring this state.

## License

MIT