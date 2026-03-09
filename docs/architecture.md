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

**Bot Mode File**: `~/.tele/state/bot_{chat_id}.json`

```json
{"last_update_id": 456, "last_processed_at": "2024-01-15T10:00:00Z"}
```

**Logic**:
- App mode: `min_id = last_message_id`, `reverse=True`
- Bot mode: `offset = last_update_id + 1`
- `--full` flag: Ignore state (app mode only)

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