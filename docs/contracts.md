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
| `\|\|` | bool, bool | Logical OR |
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

```json
{
  "last_message_id": int,    // Max processed ID
  "last_processed_at": str,  // ISO timestamp
  "chat_id": int | null      // Optional reference
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
  is_forwarded?: boolean;
  forward_from_id?: number;
  has_media?: boolean;
  media_type?: string;
  reactions?: Array<{emoji: string, count: number}>;
}
```

## Config Schema

```yaml
telegram:
  api_id: int | null      # Or TELEGRAM_API_ID
  api_hash: str | null    # Or TELEGRAM_API_HASH
  session_name: str       # Default: "tele_tool"

defaults:
  chat: str | null        # Default chat
  reaction: str           # Default: "✅"
  batch_size: int         # Default: 100
```

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
3. Use in `run_get_messages()` or `run_mark_mode()`