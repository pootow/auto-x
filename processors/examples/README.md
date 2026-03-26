# Example Processors

This directory contains example processors for the `tele` tool's bot mode. Processors are external commands that receive Telegram messages via stdin and return results via stdout.

## How Processors Work

```
┌─────────────┐     JSON Lines      ┌────────────┐     JSON Lines     ┌─────────────┐
│  tele bot   │ ──────────────────▶ │  Processor │ ─────────────────▶ │  tele bot   │
│   (stdin)   │     (messages)       │  (your     │     (results)      │  (stdout)   │
│             │                      │   code)    │                    │             │
└─────────────┘                      └────────────┘                    └─────────────┘
```

1. **Input**: `tele` sends JSON Lines to your processor's stdin (one message per line)
2. **Processing**: Your code reads, parses, and processes each message
3. **Output**: Your code writes JSON Lines to stdout (one result per line)
4. **Exit**: Exit 0 on success, non-zero triggers retry

## Input/Output Format

### Input Message

```json
{
  "id": 12345,
  "chat_id": -1001234567890,
  "text": "Hello, world!",
  "sender_id": 987654,
  "date": "2024-01-15T10:30:00Z",
  "is_forwarded": false,
  "has_media": false
}
```

### Output Result

```json
{
  "id": 12345,
  "chat_id": -1001234567890,
  "status": "success"
}
```

**Required output fields:**
- `id` - The message ID (must match input)
- `chat_id` - The chat ID (must match input)
- `status` - Either `"success"` or `"failed"`

## Running Examples

### Python

```bash
# Test standalone
echo '{"id":1,"chat_id":123,"text":"hello"}' | python processors/examples/python/echo.py

# Use with tele
tele --bot --exec "python processors/examples/python/echo.py" --chat "-1001234567890"
```

### Bash (requires `jq`)

```bash
# Test standalone
echo '{"id":1,"chat_id":123,"text":"hello"}' | bash processors/examples/bash/echo.sh

# Use with tele
tele --bot --exec "bash processors/examples/bash/echo.sh" --chat "-1001234567890"
```

### TypeScript (requires Node.js)

```bash
# Compile first
npx tsc processors/examples/typescript/echo.ts --outDir processors/examples/typescript/dist --target ES2020 --module commonjs

# Test standalone
echo '{"id":1,"chat_id":123,"text":"hello"}' | node processors/examples/typescript/dist/echo.js

# Or use ts-node directly
npx ts-node processors/examples/typescript/echo.ts

# Use with tele
tele --bot --exec "node processors/examples/typescript/dist/echo.js" --chat "-1001234567890"
```

## Common Patterns

### Filtering Messages

Only mark certain messages as success:

```python
def process_message(msg: dict) -> dict:
    text = msg.get("text", "")

    # Only process messages containing "urgent"
    if "urgent" not in text.lower():
        return {"id": msg["id"], "chat_id": msg["chat_id"], "status": "success"}

    # Do something with urgent messages
    return {"id": msg["id"], "chat_id": msg["chat_id"], "status": "success"}
```

### Calling External APIs

```python
import urllib.request
import json

def process_message(msg: dict) -> dict:
    text = msg.get("text", "")

    # Send to external service
    data = json.dumps({"message": text}).encode()
    req = urllib.request.Request(
        "https://api.example.com/process",
        data=data,
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return {"id": msg["id"], "chat_id": msg["chat_id"], "status": "success"}
    except Exception as e:
        print(f"[ERROR] API call failed: {e}", file=sys.stderr)
        return {"id": msg["id"], "chat_id": msg["chat_id"], "status": "failed"}
```

### Transforming and Storing

```python
import sqlite3

conn = sqlite3.connect("messages.db")
conn.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY,
        chat_id INTEGER,
        text TEXT,
        sender_id INTEGER,
        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

def process_message(msg: dict) -> dict:
    try:
        conn.execute(
            "INSERT OR REPLACE INTO messages (id, chat_id, text, sender_id) VALUES (?, ?, ?, ?)",
            (msg["id"], msg["chat_id"], msg.get("text"), msg.get("sender_id"))
        )
        conn.commit()
        return {"id": msg["id"], "chat_id": msg["chat_id"], "status": "success"}
    except Exception as e:
        print(f"[ERROR] Database error: {e}", file=sys.stderr)
        return {"id": msg["id"], "chat_id": msg["chat_id"], "status": "failed"}
```

### Batch Processing

Messages come one at a time, but you can buffer them:

```python
import sys
import json

BATCH_SIZE = 10
batch = []

def flush_batch():
    global batch
    if not batch:
        return

    # Process batch
    for msg in batch:
        print(json.dumps({"id": msg["id"], "chat_id": msg["chat_id"], "status": "success"}))

    sys.stdout.flush()
    batch = []

for line in sys.stdin:
    msg = json.loads(line)
    batch.append(msg)

    if len(batch) >= BATCH_SIZE:
        flush_batch()

# Don't forget remaining messages
flush_batch()
```

## Error Handling

- **Logging**: Write to `stderr` (it won't interfere with stdout)
- **Invalid input**: Return a failed status and continue processing
- **Recoverable errors**: Return `status: "failed"` to trigger retry
- **Fatal errors**: Exit with non-zero code (stops the bot)

## Testing Your Processor

```bash
# Basic test
echo '{"id":1,"chat_id":123,"text":"test"}' | python your_processor.py
# Expected: {"id":1,"chat_id":123,"status":"success"}

# Multiple messages
printf '{"id":1,"chat_id":123}\n{"id":2,"chat_id":123}\n' | python your_processor.py
# Expected:
# {"id":1,"chat_id":123,"status":"success"}
# {"id":2,"chat_id":123,"status":"success"}

# Invalid input handling
echo 'not json' | python your_processor.py
# Should output: {"id":0,"chat_id":0,"status":"failed"}
# Should NOT crash

# With tele bot mode
tele --bot --exec "python your_processor.py" --chat "-1001234567890"
```

## Further Reading

- [docs/contracts.md](../../docs/contracts.md) - Full message format specification
- [docs/architecture.md](../../docs/architecture.md) - How bot mode works internally
- [../downloader/](../downloader/) - Practical downloader processor example