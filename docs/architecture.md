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

### Ingest Mode

```
┌───────────────┐    ┌─────────────┐    ┌──────────────┐    ┌──────────┐
│ Data Source   │───>│ JSONL File  │───>│ SourceWatcher│───>│ Executor │
│ (external)    │    │ (append-only)│    │ (watch+poll) │    │          │
└───────────────┘    └─────────────┘    └──────────────┘    └──────────┘
                                            │                    │
                                       ┌────┴────┐               │
                                       │SourceState│<────────────┘
                                       └──────────┘  (byte offset)
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

**State**: Offset-based, stored in `bot.json` (global, not per-chat)

**Offset Update Rule**: Only after successful exec + successful marking

**What Bot Can See**:
- Private DMs: all messages
- Groups (privacy ON): @mentions and commands only
- Groups (privacy OFF): all messages
- Channels (admin required): all posts

### source_state.py (Source Consumption State)

**Responsibility**: Track byte offset consumption progress for each source

| Class | Purpose |
|-------|---------|
| `SourceState` | Dataclass: current_file, byte_offset, last_processed_at |
| `SourceStateManager` | Load/save state, manage state.json files |

**State File**: `~/.tele/state/sources/{name}/state.json`

```json
{
  "current_file": "incoming.2026-03-30.jsonl",
  "byte_offset": 5000,
  "last_processed_at": "2026-03-31T10:00:00Z"
}
```

**Core Convention**: Date in filename always increases. Files with older dates are automatically complete.

### source_consumer.py (File Consumption)

**Responsibility**: Read JSONL files from byte offset, handle partial lines

| Function | Purpose |
|----------|---------|
| `consume_from_offset()` | Read from offset, yield complete lines |
| `get_next_file()` | Find next file by date monotonicity |

**Edge Cases**:
- Partial line at EOF (mid-write) → Skip, wait for next read
- File rotation → Move to next dated file automatically
- Unicode → Binary mode with UTF-8 decoding per line

### source_watcher.py (File Monitoring)

**Responsibility**: Detect file changes via watchdog + polling fallback

| Class | Purpose |
|-------|---------|
| `SourceWatcher` | Manage watchdog observer + polling timer |
| `WatcherEvent` | Event dataclass for queue |

**Three-Layer Detection**:
1. Watchdog events (primary) - immediate file modification detection
2. Polling fallback (30s default) - safety net for missed events
3. Manual trigger (`--scan`, `--process-source`)

**Cross-Platform**: watchdog uses inotify (Linux), kqueue/FSEvents (macOS), ReadDirectoryChangesW (Windows). All have limitations; polling ensures reliability.

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

**Bot Mode Files** (global - Telegram offset is not per-chat):
- `bot.json` - Offset state
- `bot_pending.jsonl` - Messages waiting to be processed
- `bot_dead.jsonl` - Retriable errors after 3 retries
- `bot_fatal.jsonl` - Fatal errors (no retry value)

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

**Ingest Mode Persistence**:

Data sources write to `incoming.{date}.jsonl` (append-only). Tele tracks consumption in `state.json` (byte offset). Files are preserved as audit logs.

```
Startup:
  1. Load state.json → current_file, byte_offset
  2. Scan directory → all incoming.*.jsonl files

Main loop (watchdog + polling):
  1. Detect file modification
  2. Read from byte_offset → yield complete lines
  3. Process each message through configured processor
  4. Update byte_offset after success
  5. When file exhausted → check for next dated file

Error handling:
  - status: success → Advance byte_offset
  - status: error   → Move to {source}_pending.jsonl, retry with backoff
  - status: fatal   → Move to {source}_fatal.jsonl, advance offset
```

**Key Differences**:

| Aspect | Bot Mode | Ingest Mode |
|--------|----------|-------------|
| Input source | Telegram API | Local JSONL files |
| Tracking | API offset | Byte offset |
| File retention | Pending queue cleared | Audit logs kept forever |
| File naming | Fixed names | Date-based (YYYY-MM-DD) |

**Retry Dead-Letter**:

```bash
# View dead letters (retriable errors that exhausted retries)
cat ~/.tele/state/bot_dead.jsonl

# View fatal errors (no retry value)
cat ~/.tele/state/bot_fatal.jsonl

# Retry dead letters with original processor
tele --retry-dead ~/.tele/state/bot_dead.jsonl

# Retry with different processor
tele --retry-dead ~/.tele/state/bot_dead.jsonl --exec "new-processor"
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

**New Sections** (ingest mode):
- `sources`: Dict of source configs (path, processor, filter, chat_id)
- `ingest`: Global ingest settings (poll_interval, watch_enabled)

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
| source_state.py | State persistence, source isolation |
| source_consumer.py | Byte offset reading, partial lines, file rotation |
| source_watcher.py | Watchdog events, polling fallback |
| integration | E2E pipeline flows |

Integration tests with real Telegram API require credentials (see `tests/integration_manual.py`).