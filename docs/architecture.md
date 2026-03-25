# Architecture

## Data Flow

### App Mode

```
┌─────────┐    ┌────────────┐    ┌────────┐    ┌─────────┐
│ Config  │───>│ TeleClient │───>│ Filter │───>│ Output  │
└─────────┘    └────────────┘    └────────┘    └─────────┘
                      │
                 ┌────┴────┐
                 │  State  │
                 └─────────┘
```

### Bot Mode

```
┌─────────┐    ┌────────────┐    ┌────────┐    ┌─────────┐    ┌──────────┐
│ Config  │───>│ BotClient  │───>│ Filter │───>│ Batcher │───>│ Executor │
└─────────┘    └────────────┘    └────────┘    └─────────┘    └──────────┘
                      │                                            │
                 ┌────┴────┐                                      │
                 │  State  │<─────────────────────────────────────┘
                 └─────────┘     (update offset on success only)
```

## Components

### cli.py (Entry Point)

**Responsibility**: Parse args, orchestrate flow

**Modes**:
- `--bot`: Daemon mode with Bot API
- Default: App mode with MTProto

```python
# App mode flow
load_config() -> TeleClient() -> fetch_messages() -> filter() -> output()

# Bot mode flow
load_config() -> BotClient() -> poll_updates() -> filter() -> batch() -> exec() -> mark()
```

### client.py (MTProto API Layer)

**Responsibility**: Wrap Telethon, hide complexity

| Method | Purpose |
|--------|---------|
| `resolve_chat()` | Name/ID -> InputPeer |
| `iter_messages()` | Fetch with pagination |
| `iter_search_messages()` | Search API |
| `add_reaction()` | Mark processed |

**Chat ID Mapping**:
- User: positive int
- Group: negative int
- Channel: -1000000000000 - channel_id

### bot_client.py (Bot API Layer)

**Responsibility**: Bot API HTTP client, polling, message handling

| Method | Purpose |
|--------|---------|
| `poll_updates()` | Long polling with offset |
| `add_reaction()` | Mark via Bot API |
| `get_chat_id()` | Extract chat from update |

**State**: Offset-based, stored in `bot_{chat_id}.json`

**Offset Update Rule**: Only after successful exec + successful marking

**What Bot Can See**:
- Private DMs: all messages
- Groups (privacy ON): @mentions and commands only
- Groups (privacy OFF): all messages
- Channels (admin required): all posts

### filter.py (DSL Engine)

**Pipeline**: `Lexer -> Parser -> AST -> Evaluator`

```
"contains('x') && sender_id==1"
  ↓ Lexer
[IDENT, LPAREN, STRING, ...]
  ↓ Parser
BinaryOp(FunctionCall('contains', [Literal('x')]), '&&', BinaryOp(...))
  ↓ Evaluator
True/False
```

**AST Types**:
- `FunctionCall(name, args)` - contains(), has_reaction()
- `BinaryOp(left, op, right)` - &&, ||, ==, etc.
- `UnaryOp(op, operand)` - !
- `Identifier(name)` - Field reference
- `Literal(value)` - String/number

**Extending DSL**:
1. Add function to `_call_function()` in MessageFilter
2. Add tests in `tests/test_filter.py`

### state.py (Incremental Processing)

**App Mode File**: `~/.tele/state/{chat_id}.json`

```json
{"last_message_id": 123, "last_processed_at": "2024-01-15T10:00:00Z"}
```

**Bot Mode Files**:
- `bot_{chat_id}.json` - Offset state
- `bot_{chat_id}_pending.jsonl` - Messages waiting to be processed
- `bot_{chat_id}_dead.jsonl` - Retriable errors after 3 retries
- `bot_{chat_id}_fatal.jsonl` - Fatal errors (no retry value)

**Processor Status Values**:

| Status | Meaning | Action |
|--------|---------|--------|
| `success` | Processed successfully | Remove from pending, mark ✅ |
| `error` | Retriable failure | Retry up to 3 times, then dead-letter |
| `fatal` | Non-retriable, no value | Remove from pending, log to fatal.jsonl, mark 👎 |

**Examples of `fatal`**:
- Resource 404 (link expired, file deleted)
- Invalid message format
- Business logic rejection

**Examples of `error`**:
- Network timeout
- External service temporarily unavailable
- Rate limited

**Bot Mode Persistence**:

Messages are persisted to the pending queue before processing. On crash/restart, pending messages are replayed. Processor failures (status: error) are retried 3 times with exponential backoff (5s, 15s, 45s). After 3 failures, messages go to the dead-letter file for manual retry.

```
Startup:
  1. Load pending queue from disk
  2. Replay pending messages through batcher

Main loop:
  1. Poll getUpdates(offset)
  2. For each update: append to pending file → add to batcher
  3. On batch success: remove from pending file → save offset

Processor returns:
  - status: success → Remove from pending, mark ✅
  - status: error   → Retry with backoff, then dead-letter
  - status: fatal   → Remove from pending, fatal.jsonl, mark 👎

Processor crash:
  1. Increment retry_count
  2. Schedule retry with backoff
  3. After 3 retries: move to dead-letter file
```

**Retry Dead-Letter**:

```bash
# View dead letters (retriable errors that exhausted retries)
cat ~/.tele/state/bot_123_dead.jsonl

# View fatal errors (no retry value)
cat ~/.tele/state/bot_123_fatal.jsonl

# Retry dead letters with original processor
tele --retry-dead ~/.tele/state/bot_123_dead.jsonl

# Retry with different processor
tele --retry-dead ~/.tele/state/bot_123_dead.jsonl --exec "new-processor"
```

**Logic**:
- App mode: `min_id = last_message_id`, `reverse=True`
- Bot mode: `offset = last_update_id + 1`
- `--full` flag: Ignore state (app mode only)

**Known Limitation - App Mode**:

App mode does not have persistence for piped output. If the app crashes or is killed after outputting messages to stdout but before the downstream processor completes, those messages may be lost. Users can re-run the command to re-fetch messages from Telegram. This limitation is documented and app mode is currently paused in active development.

### output.py (Serialization)

**Format**: JSON Lines (one message per line)

```json
{"id": 1, "text": "...", "sender_id": 123, "date": "...", "chat_id": 456, "status": "success"}
```

**Required fields**:
- `id`, `text`, `sender_id`, `date`, `chat_id`, `status`

**Optional fields** (when present):
- `is_forwarded`, `forward_from_id`
- `has_media`, `media_type`
- `reactions`: `[{emoji, count}]`

**Status values**: `success` | `failed` | `pending`

### config.py (Configuration)

**Priority**: ENV > YAML > Defaults

**Env vars**:
- `TELEGRAM_API_ID` (app mode)
- `TELEGRAM_API_HASH` (app mode)
- `TELEGRAM_BOT_TOKEN` (bot mode)

**YAML**: `~/.tele/config.yaml`

## Error Handling

| Layer | Strategy |
|-------|----------|
| CLI | Click exceptions, exit codes |
| Client | Raise to CLI, print to stderr |
| Filter | SyntaxError for parse, ValueError for eval |
| BotClient | Retry on transient errors, exit on auth failure |

## Testing Strategy

| Module | Test Focus |
|--------|------------|
| filter.py | Lexer, parser, evaluator (pure functions) |
| state.py | File I/O, edge cases |
| config.py | Env override, file parsing |
| output.py | Serialization, status field |
| bot_client.py | Polling, offset handling |
| integration | E2E pipeline flows |

Integration tests with real Telegram API require credentials (see `tests/integration_manual.py`).