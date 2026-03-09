# Contracts

## Message Object (Telethon)

```python
class Message:
    id: int
    text: str | None
    sender_id: int
    date: datetime
    chat_id: int
    forward: MessageFwd | None
    media: MessageMedia | None
    reactions: MessageReactions | None
```

## Bot API Update Object

```python
class Update:
    update_id: int
    message: Message | None      # New message
    channel_post: Message | None # Channel post
    # ... other update types
```

## Filter DSL

### Functions

| Signature | Returns | Description |
|-----------|---------|-------------|
| `contains(str)` | bool | Text contains substring |
| `has_reaction(str)` | bool | Has emoji reaction |

### Fields

| Name | Type | Description |
|------|------|-------------|
| `sender_id` | int | User ID |
| `message_id` | int | Message ID |
| `date` | datetime | Timestamp |
| `is_forwarded` | bool | Forward check |
| `has_media` | bool | Media check |

### Operators

| Operator | Operands | Result |
|----------|----------|--------|
| `&&` | bool, bool | Logical AND |
| `||` | bool, bool | Logical OR |
| `!` | bool | Logical NOT |
| `==`, `!=` | any, any | Equality |
| `<`, `<=`, `>`, `>=` | num, num | Comparison |

### Grammar (EBNF)

```
expr     = or_expr
or_expr  = and_expr ('||' and_expr)*
and_expr = unary_expr ('&&' unary_expr)*
unary    = '!' unary | comparison
comparison = primary (('=='|'!='|'<'|'<='|'>'|'>=') primary)?
primary  = IDENTIFIER | NUMBER | STRING | func_call | '(' expr ')'
func_call = IDENTIFIER '(' args? ')'
args     = expr (',' expr)*
```

## State File

### App Mode

```json
{
  "last_message_id": int,    // Max processed ID
  "last_processed_at": str,  // ISO timestamp
  "chat_id": int | null      // Optional reference
}
```

### Bot Mode

```json
{
  "last_update_id": int,     // Last processed update_id
  "last_processed_at": str   // ISO timestamp
}
```

## Output Format

```typescript
interface OutputMessage {
  id: number;
  text: string;
  sender_id: number;
  date: string | null;  // ISO
  chat_id: number | null;
  status: "success" | "failed" | "pending";  // Processing result
  is_forwarded?: boolean;
  forward_from_id?: number;
  has_media?: boolean;
  media_type?: string;
  reactions?: Array<{emoji: string, count: number}>;
}
```

**Status Field**:
- `pending`: Message not yet processed (input to processor)
- `success`: Processor marked as successful → apply `--mark` reaction
- `failed`: Processor marked as failed → apply `--failed-mark` reaction

## Config Schema

```yaml
telegram:
  api_id: int | null        # Or TELEGRAM_API_ID (app mode)
  api_hash: str | null      # Or TELEGRAM_API_HASH (app mode)
  bot_token: str | null     # Or TELEGRAM_BOT_TOKEN (bot mode)
  session_name: str         # Default: "tele_tool"

defaults:
  chat: str | null          # Default chat
  reaction: str             # Default: "✅"
  failed_reaction: str      # Default: "❌"
  batch_size: int           # Default: 100
  page_size: int            # Default: 10
  interval: int             # Default: 3 (seconds, bot mode)
```

## CLI Options

### App Mode

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--chat` | str | config | Target chat |
| `--search` | str | None | Search query |
| `--filter` | str | None | DSL filter |
| `--full` | flag | False | Ignore state |
| `--page-size` | int | 10 | Messages per output batch |
| `--mark` | str | ✅ | Reaction for marking |

### Bot Mode

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--bot` | flag | False | Enable bot mode |
| `--chat` | str | None | Filter to specific chat ID (optional) |
| `--exec` | str | None | Command to process messages |
| `--` | - | - | Pass remaining args to exec (avoids quoting) |
| `--filter` | str | None | DSL filter (default: all messages) |
| `--page-size` | int | 10 | Max messages per batch |
| `--interval` | int | 3 | Debounce seconds |
| `--mark` | str | ✅ | Success reaction |
| `--failed-mark` | str | ❌ | Failure reaction |

## Extension Points

### Adding Filter Functions

1. Add to `MessageFilter._call_function()`:

```python
if name == "my_func":
    # Parse args, evaluate, return result
    arg = self._evaluate(args[0], message)
    return some_logic(arg, message)
```

2. Update grammar/docs if complex

### Adding Output Fields

1. Modify `format_message()` in output.py:

```python
if message.my_field:
    data['my_field'] = message.my_field
```

2. Update OutputMessage type in contracts.md

### Adding CLI Options

1. Add option in `cli()` decorator
2. Pass through `ctx.obj`
3. Use in `run_get_messages()` or `run_bot_mode()`