# tele - Telegram Message Processing Pipeline

A command-line tool for processing Telegram messages with filtering, incremental processing, and pipeline integration.

## Features

- **Message fetching**: Get messages from chats with incremental support
- **Search**: Use Telegram's search API to find messages
- **DSL filtering**: Filter messages using a powerful expression language
- **Pipeline integration**: Output to stdout for downstream processing
- **Mark processed messages**: Add reactions to track processed messages

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

### Get new messages from a chat

```bash
tele --chat "chat_name"
```

### Search messages

```bash
tele --chat "chat_name" --search "keywords"
```

### Filter messages with DSL

```bash
tele --chat "chat_name" --filter 'contains("important") && !has_reaction("✅")'
```

### Full processing (ignore incremental state)

```bash
tele --chat "chat_name" --full
```

### Mark messages as processed

```bash
# Mark messages read from stdin
tele --chat "chat_name" --filter 'contains("important")' | \
  your_processor | \
  tele --mark --reaction "✅"
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