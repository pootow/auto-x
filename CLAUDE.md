# tele - Telegram Message Pipeline

CLI tool for processing Telegram messages. Filter, transform, mark processed.

## Contents

| Section | When to Read |
|---------|--------------|
| [Quick Reference](#quick-reference) | Running commands |
| [Architecture](#architecture) | Modifying code, debugging |
| [Configuration](#configuration) | Setting up config file |
| [DSL Reference](#dsl-reference) | Writing filter expressions |
| [Processor Protocol](#processor-protocol) | Building processors |
| [Persistence](#persistence) | Understanding state files |

## Docs

| File | Purpose | Read When |
|------|---------|-----------|
| [docs/requirements.md](docs/requirements.md) | What/Why | Understanding intent, extending features |
| [docs/architecture.md](docs/architecture.md) | How components work | Modifying internals, debugging |
| [docs/contracts.md](docs/contracts.md) | Interfaces/types | Extending DSL, adding outputs |

## Quick Reference

```bash
# App mode (MTProto API)
tele --chat "name" [--search "q"] [--filter 'DSL'] [--full]  # Get messages
tele --mark [--reaction "✅"]                                # Mark from stdin

# Bot mode (Bot API daemon)
tele --bot --exec "processor" [--chat "id"] [--filter 'DSL'] [--page-size 10] [--interval 3]
tele --bot -- <command args...>               # Alternative: -- to avoid quoting

# Retry dead-letter queue
tele --retry-dead ~/.tele/state/bot_{chat_id}_dead.jsonl [--exec "processor"]
```

## Architecture

| Mode | API | State File | Use Case |
|------|-----|------------|----------|
| App | MTProto (Telethon) | `{chat_id}.json` | Manual queries, scheduled jobs |
| Bot | Bot API (HTTP) | `bot_{chat_id}.json` | Daemon monitoring, automation |

### Key Files

| File | Responsibility |
|------|---------------|
| `tele/cli.py` | Entry point, CLI parsing, orchestration |
| `tele/client.py` | Telethon wrapper (MTProto API) |
| `tele/bot_client.py` | Bot API client (HTTP polling) |
| `tele/filter.py` | DSL lexer/parser/evaluator |
| `tele/state.py` | Incremental processing state |
| `tele/output.py` | JSON Lines serialization |
| `tele/config.py` | YAML/env config loading |

### Dependencies

`telethon` (MTProto), `aiohttp` (HTTP), `click` (CLI), `pyyaml` (config)

## Configuration

Config file: `~/.tele/config.yaml`

```yaml
telegram:
  api_id: 12345
  api_hash: your_api_hash
  bot_token: your_bot_token        # For bot mode
  bot_api_endpoint: api.telegram.org  # Optional, for custom Bot API servers
  session_name: tele_tool

defaults:
  chat: work_chat
  reaction: "✅"
  batch_size: 100
```

Environment variables override config file:
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_BOT_TOKEN`

## DSL Reference

### Functions

| Function | Description |
|----------|-------------|
| `contains("keyword")` | Message text contains keyword |
| `has_reaction("✅")` | Message has specified reaction |

### Fields

`sender_id`, `sender_name`, `message_id`, `date`, `is_forwarded`, `has_media`

### Operators

`&&` (AND), `||` (OR), `!` (NOT), `==`, `!=`, `<`, `<=`, `>`, `>=`

### Examples

```bash
tele --chat "work" --filter 'contains("urgent") || contains("important")'
tele --chat "support" --filter '!has_reaction("✅") && sender_id == 12345678'
tele --chat "news" --filter 'date > "2024-01-01"'
```

## Processor Protocol

Processors read JSON Lines from stdin, write results to stdout.

### Input

```json
{"id": 123, "text": "content", "sender_id": 456, "date": "...", "chat_id": 789}
```

### Output

```json
{"id": 123, "chat_id": 456, "status": "success"}
```

### Status Values

| Status | Meaning | Action |
|--------|---------|--------|
| `success` | Processed | Remove from pending, mark ✅ |
| `error` | Retriable failure | Retry 3× (5s, 15s, 45s backoff), then dead-letter |
| `fatal` | Non-retriable | Remove from pending, log to fatal.jsonl |

### Rich Reply

```json
{
  "id": 123,
  "chat_id": 456,
  "status": "success",
  "reply": [
    {"text": "# Title\n_Description_", "media": {"type": "video", "url": "https://..."}}
  ]
}
```

Media types: `video` (≤50MB, size verified via HTTP HEAD), `image`. Each reply item sent as separate message.

## Persistence

### File Structure

```
~/.tele/state/
├── bot_{chat_id}.json           # Offset state
├── bot_{chat_id}_pending.jsonl  # Messages awaiting processing
├── bot_{chat_id}_dead.jsonl     # Retriable errors after 3 retries
└── bot_{chat_id}_fatal.jsonl    # Fatal errors (no retry)
```

### Incremental Processing

App mode tracks processed messages in `~/.tele/state/{chat_id}.json`. Use `--full` to ignore state.

## Testing

```bash
uv run pytest                           # All tests
uv run pytest tests/test_filter.py      # DSL tests
uv run pytest tests/test_integration.py # Pipeline tests

# Manual (requires credentials)
TELEGRAM_API_ID=x TELEGRAM_API_HASH=y uv run python tests/integration_manual.py
TELEGRAM_BOT_TOKEN=x uv run python tests/integration_manual.py --bot
```