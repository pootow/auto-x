# Source Examples Design

## Summary

Create reference implementations for data sources, similar to `processors/examples/`. Demonstrates the source protocol for writing messages to append-only JSONL files.

## Motivation

Processors have example implementations (`processors/examples/`) that teach users the protocol. Sources need the same - a clear reference showing how to:
- Generate messages in correct JSONL format
- Write to date-named files (`incoming.YYYY-MM-DD.jsonl`)
- Follow core conventions (append-only, date monotonicity)

## Directory Structure

```
sources/
└── examples/
    ├── README.md           # Protocol, conventions, usage examples
    ├── python/
    │   └── heartbeat.py    # Python heartbeat source
    └── bash/
        └── heartbeat.sh    # Bash heartbeat source
```

## Core Conventions (Must Document)

These rules are critical for users developing their own sources:

1. **File naming**: `incoming.YYYY-MM-DD.jsonl` (precise to day, not seconds)
2. **Date monotonicity**: New messages must go to today's file (or later). Never write to older files.
3. **Append-only**: Only append, never modify or delete existing content
4. **Atomic writes** (optional but recommended): Write to temp file, then rename

## Message Format

```json
{"id": "unique_id", "chat_id": 123, "text": "...", "date": "2026-03-31T10:00:00Z", "source": "heartbeat"}
```

Required fields: `id`, `chat_id`, `text`, `date`
Optional fields: `source`, `sender_id`, etc.

## Heartbeat Source

Generates periodic "heartbeat" messages. Demonstrates:
- Scheduling loop (Python: `time.sleep()`, Bash: `sleep`)
- Date-based file naming (recalculate each iteration)
- Append-only file writing
- JSON message generation

### Python Implementation

- Uses `datetime.now()` for date and timestamp
- Config via environment variables: `TELE_SOURCE_PATH`, `TELE_CHAT_ID`, `TELE_INTERVAL`
- Logging to stderr (simple format, tele's executor handles full formatting)

### Bash Implementation

- Uses `date +%Y-%m-%d` for filename, `date -Iseconds` for timestamp
- Same env vars for config
- Append with `>>` operator

## README.md Structure

1. How Sources Work (diagram: source → JSONL file → tele)
2. File Naming Convention
3. Core Conventions (highlighted, must follow)
4. Message Format
5. Running Examples (command lines)
6. Common Patterns (scheduling, error handling)
7. Testing Your Source
8. Further Reading

## Files to Create

| File | Content |
|------|---------|
| `sources/examples/README.md` | Protocol documentation |
| `sources/examples/python/heartbeat.py` | Python implementation (~50 lines) |
| `sources/examples/bash/heartbeat.sh` | Bash implementation (~30 lines) |