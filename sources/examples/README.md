# Example Sources

This directory contains example data sources for the `tele` tool's ingest mode. Sources are external scripts that generate messages and write them to append-only JSONL files.

## How Sources Work

```
┌─────────────┐     JSON Lines      ┌─────────────────┐     Watch/Poll      ┌───────────┐
│   Your      │ ──────────────────▶ │  incoming.{date}│ ──────────────────▶ │   tele    │
│   Source    │     (append)        │     .jsonl      │     (detect)        │  --ingest │
│   (script)  │                     │                 │                     │           │
└─────────────┘                     └─────────────────┘                     └───────────┘
```

1. **Generate**: Your source script creates messages (from web monitoring, RSS, etc.)
2. **Write**: Append messages to `incoming.YYYY-MM-DD.jsonl` in your source directory
3. **Detect**: `tele --ingest` detects new content via watchdog events or polling
4. **Process**: Messages flow through the configured processor

## Core Conventions (MUST Follow)

These rules are critical. Breaking them will cause data loss or corruption.

### 1. File Naming Convention

```
incoming.YYYY-MM-DD.jsonl
```

- **Exact format**: `incoming.` + date (YYYY-MM-DD) + `.jsonl`
- **Date precision**: Day-level, not hours/minutes/seconds
- **Example**: `incoming.2026-03-31.jsonl`

### 2. Date Monotonicity

**The date in filename must always increase. Never write to older files.**

When your source runs:
- Calculate today's date at that moment
- Write to today's file
- If running past midnight, the date will naturally advance

```
# WRONG: Hardcoding a date
FILE="incoming.2026-03-30.jsonl"  # Never do this

# RIGHT: Calculate date each time
DATE=$(date +%Y-%m-%d)           # Recalculate every iteration
FILE="incoming.$DATE.jsonl"
```

### 3. Append-Only

**Only append to files. Never modify or delete existing content.**

Files serve as audit logs. Once written, content stays forever.

```python
# RIGHT: Append mode
with open(file_path, "a") as f:
    f.write(message + "\n")

# WRONG: Overwrite mode
with open(file_path, "w") as f:  # Never use "w"
    f.write(message + "\n")
```

### 4. Atomic Writes (Recommended)

For safety, write to a temp file first, then rename:

```bash
TEMP="incoming.$DATE.jsonl.tmp"
echo "$MSG" >> "$TEMP"
mv "$TEMP" "incoming.$DATE.jsonl"  # Atomic on same filesystem
```

This prevents partial writes if your script crashes mid-operation.

## Message Format

Write one JSON object per line (JSONL format):

```json
{"id": "unique_id", "chat_id": 123, "text": "Your message content", "date": "2026-03-31T10:00:00Z", "source": "my_monitor"}
```

**Required fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier for this message |
| `chat_id` | integer | Target chat ID for notifications |
| `text` | string | Message content (what processor sees) |
| `date` | string | ISO 8601 timestamp (when generated) |

**Optional fields:**

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Source name (for identification) |
| `sender_id` | integer | Mimic Telegram sender |
| `has_media` | boolean | Mimic Telegram media flag |

## Running Examples

### Python Heartbeat

Generates periodic heartbeat messages:

```bash
# Set environment variables
export TELE_SOURCE_PATH=~/.tele/state/sources/heartbeat
export TELE_CHAT_ID=-1001234567890
export TELE_INTERVAL=60

# Run (generates messages every 60 seconds)
python sources/examples/python/heartbeat.py
```

### Bash Heartbeat

Same functionality, pure shell:

```bash
# Set environment variables
export TELE_SOURCE_PATH=~/.tele/state/sources/heartbeat
export TELE_CHAT_ID=-1001234567890
export TELE_INTERVAL=60

# Run
bash sources/examples/bash/heartbeat.sh
```

### With tele ingest

```bash
# Configure in ~/.tele/config.yaml
sources:
  heartbeat:
    path: ~/.tele/state/sources/heartbeat
    processor: "python processors/examples/python/echo.py"
    chat_id: -1001234567890

# Start source (in one terminal)
python sources/examples/python/heartbeat.py

# Start tele ingest (in another terminal)
tele --ingest
```

## Common Patterns

### Web Monitoring

```python
import urllib.request
import json
from datetime import datetime

def check_website(url: str) -> dict:
    """Fetch website and return message if changed."""
    with urllib.request.urlopen(url, timeout=10) as resp:
        content = resp.read().decode()

    # Compare with previous content (stored elsewhere)
    if content != previous_content:
        return {
            "id": f"web-{datetime.now().timestamp()}",
            "chat_id": CHAT_ID,
            "text": f"Website changed: {url}",
            "date": datetime.now().isoformat(),
            "source": "web_monitor"
        }
    return None

# In your loop:
while True:
    msg = check_website("https://example.com")
    if msg:
        write_message(msg)
    time.sleep(300)  # Check every 5 minutes
```

### Handling Midnight Date Change

The date naturally advances when your loop runs past midnight:

```bash
# Bash: Date recalculated each iteration
while true; do
    DATE=$(date +%Y-%m-%d)        # Fresh date every loop
    FILE="$PATH/incoming.$DATE.jsonl"
    # ... write to $FILE
    sleep 60
done

# Python: Same approach
while True:
    date = datetime.now().strftime("%Y-%m-%d")  # Fresh date
    file_path = f"{base_path}/incoming.{date}.jsonl"
    # ... write to file_path
    time.sleep(60)
```

### Error Handling

Log errors to stderr (won't corrupt JSONL files):

```python
import logging
import sys

# Log to stderr only
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    write_message(msg)
except IOError as e:
    logger.error("Failed to write: %s", e)
    # Don't crash - retry next iteration
```

## Testing Your Source

```bash
# Create test directory
mkdir -p ~/.tele/state/sources/test

# Run your source briefly
export TELE_SOURCE_PATH=~/.tele/state/sources/test
export TELE_CHAT_ID=123
timeout 5 python your_source.py

# Check output
cat ~/.tele/state/sources/test/incoming.*.jsonl
# Should see valid JSON lines

# Validate JSON format
cat ~/.tele/state/sources/test/incoming.*.jsonl | python -m json.tool --no-ensure-ascii
# Should parse without errors

# Process with tele
tele --process-source test --exec "cat"
# Should output your messages
```

## Further Reading

- [docs/superpowers/specs/2026-03-31-source-ingest-design.md](../../docs/superpowers/specs/2026-03-31-source-ingest-design.md) - Full ingest mode design
- [CLAUDE.md](../../CLAUDE.md) - Quick reference for ingest commands
- [processors/examples/](../../processors/examples/) - Processor examples (the other side)