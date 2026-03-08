# Architecture

## Data Flow

```
┌─────────┐    ┌────────┐    ┌────────┐    ┌─────────┐
│ Config  │───>│ Client │───>│ Filter │───>│ Output  │
└─────────┘    └────────┘    └────────┘    └─────────┘
                    │
               ┌────┴────┐
               │  State  │
               └─────────┘
```

## Components

### cli.py (Entry Point)

**Responsibility**: Parse args, orchestrate flow

```python
# Key flow
load_config() -> TeleClient() -> fetch_messages() -> filter() -> output()
                                                    ↓
                                              StateManager.update()
```

**CLI Modes**:
- `get`: Fetch messages (default)
- `mark`: Read JSON from stdin, add reactions

### client.py (API Layer)

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

**File**: `~/.tele/state/{chat_id}.json`

```json
{"last_message_id": 123, "last_processed_at": "2024-01-15T10:00:00Z"}
```

**Logic**:
- Normal mode: `min_id = last_message_id`, `reverse=True`
- Search mode: No incremental (API limitation)
- `--full` flag: Ignore state

### output.py (Serialization)

**Format**: JSON Lines (one message per line)

```json
{"id": 1, "text": "...", "sender_id": 123, "date": "...", "chat_id": 456}
```

**Optional fields** (when present):
- `is_forwarded`, `forward_from_id`
- `has_media`, `media_type`
- `reactions`: `[{emoji, count}]`

### config.py (Configuration)

**Priority**: ENV > YAML > Defaults

**Env vars**:
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`

**YAML**: `~/.tele/config.yaml`

## Error Handling

| Layer | Strategy |
|-------|----------|
| CLI | Click exceptions, exit codes |
| Client | Raise to CLI, print to stderr |
| Filter | SyntaxError for parse, ValueError for eval |

## Testing Strategy

| Module | Test Focus |
|--------|------------|
| filter.py | Lexer, parser, evaluator (pure functions) |
| state.py | File I/O, edge cases |
| config.py | Env override, file parsing |
| output.py | Serialization |
| integration | E2E pipeline flows |

Integration tests with real Telegram API require credentials (see `tests/integration_manual.py`).