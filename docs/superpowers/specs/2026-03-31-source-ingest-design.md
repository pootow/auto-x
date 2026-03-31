# Source Ingest Design

## Summary

Extend tele to support external data sources (web monitors, RSS feeds, etc.) that automatically trigger tasks. Data sources write to append-only JSONL files, tele consumes and processes them through the existing pipeline.

## Motivation

Current tele only processes messages from Telegram Bot (user-triggered). Need to support automatic triggers from external data sources:
- Web page content monitoring
- RSS feed updates
- Custom monitoring scripts

Core constraint: avoid complex network protocols (HTTP/TCP), use simple file-based communication that aligns with existing queue model.

## Architecture

### Directory Structure

```
~/.tele/state/
├── sources/
│   ├── {source_name}/
│   │   ├── incoming.2026-03-31.jsonl    ← Current day file (data source appends)
│   │   ├── incoming.2026-03-30.jsonl    ← Previous day (may be fully consumed)
│   │   ├── incoming.2026-03-29.jsonl    ← Audit log (keep forever)
│   │   ├── state.json                   ← tele consumption state
│   │   ├── {source_name}_pending.jsonl  ← Messages in retry (tele-managed)
│   │   ├── {source_name}_dead.jsonl     ← Exhausted retries (tele-managed)
│   │   └── {source_name}_fatal.jsonl    ← Fatal errors (tele-managed)
│   └── {another_source}/
│       └── ...
├── bot_{chat_id}_pending.jsonl          ← Bot queue (existing)
└── ...
```

### File Roles

| File | Manager | Purpose |
|------|---------|---------|
| `incoming.{date}.jsonl` | Data source | Append-only input, audit log |
| `state.json` | tele | Consumption progress |

### state.json Format

```json
{
  "current_file": "incoming.2026-03-30.jsonl",
  "byte_offset": 5000,
  "last_processed_at": "2026-03-31T10:00:00Z"
}
```

## Core Convention

**Date in filename always increases.** This eliminates need for `completed_files` list:
- Files with date < `current_file` date → automatically considered complete
- Files with date > `current_file` date → pending consumption

## Data Source Protocol

Data sources write JSONL messages matching existing tele format:

```json
{"id": "unique_id", "source": "web_monitor", "chat_id": 123, "text": "...", "date": "2026-03-31T10:00:00Z"}
```

Required fields: `id`, `chat_id`, `text`, `date`
Optional fields: `source`, `sender_id`, `has_media`, etc.

Data source behavior:
1. Determine current date (YYYY-MM-DD)
2. Append to `incoming.{date}.jsonl` in configured source directory
3. No need to notify tele — file monitoring handles detection

## Consumption Mechanism

Three-layer strategy for reliability:

### Layer 1: Event Monitoring (Primary)

Use Python `watchdog` to monitor `sources/` directory for file changes:
- Listen for `FileModifiedEvent` on `incoming.*.jsonl` files
- Push events to internal Channel buffer (deduplication)
- Trigger consumption on event

### Layer 2: Polling Fallback (Always Active)

Periodic scan (default: 30 seconds) as safety net:
- Check all source directories
- Compare file sizes with recorded `byte_offset`
- Process any new content

Purpose: catch events missed by watchdog (buffer overflow, OS limitations, edge cases).

### Layer 3: Manual Trigger

CLI command for explicit processing:
```bash
tele --scan                    # Scan all sources
tele --process-source {name}   # Process specific source
```

## Consumption Flow

```
1. Read state.json → get current_file and byte_offset
2. Scan directory → get all incoming.*.jsonl files, sort by date
3. Skip files with date < current_file (already complete)
4. Process current_file from byte_offset
5. Process files with date > current_file in order
6. After finishing a file:
   - Update state.json: current_file = next file, byte_offset = 0
7. Continue until all files processed up to latest
```

## Error Handling

Same as existing Bot mode:
- `success` → Offset advances, message processed
- `error` → Move message to `{source_name}_pending.jsonl` (tele-managed), retry with backoff (5s, 15s, 45s), then dead-letter queue `{source_name}_dead.jsonl`
- `fatal` → Move message to `{source_name}_fatal.jsonl`, offset advances

When error/fatal occurs, message moves from incoming to tele-managed queue. Offset in state.json advances so incoming consumption continues for other messages.

## Rotate Behavior

Data source handles file naming by date. No explicit rotate needed:
- Each day: new file `incoming.{new_date}.jsonl`
- Previous day's file becomes "complete" naturally when tele switches to newer file
- All files preserved as audit logs

## Configuration

New config section in `~/.tele/config.yaml`:

```yaml
sources:
  web_monitor:
    path: ~/.tele/state/sources/web_monitor
    processor: "my-web-processor"
    filter: 'contains("important")'  # Optional
    chat_id: 123                      # For notifications

ingest:
  poll_interval: 30                   # Seconds
  watch_enabled: true                 # Can disable if problematic
```

## CLI Commands

```bash
# Start ingest daemon (file monitoring + polling)
tele --ingest

# Process specific source
tele --process-source web_monitor

# Scan all sources once
tele --scan

# List sources and their state
tele --list-sources
```

## Integration with Existing Bot Mode

Both modes can run simultaneously:
- Bot mode: `tele --bot --chat X --exec processor`
- Ingest mode: `tele --ingest`

Each has independent state files. Bot mode tracks Telegram offset, ingest mode tracks source file offsets.

## Implementation Notes

### watchdog Integration

```python
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class SourceEventHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.src_path.endswith('.jsonl') and 'incoming.' in event.src_path:
            # Push to channel for dedup/consumption
            channel.put(event.src_path)
```

### Byte Offset Reading

```python
with open(file_path, 'rb') as f:
    f.seek(state.byte_offset)
    for line in f:
        message = json.loads(line)
        # process message
        state.byte_offset = f.tell()  # Update after each successful process
```

### Cross-Platform Considerations

watchdog uses:
- Linux: inotify
- macOS: kqueue / FSEvents
- Windows: ReadDirectoryChangesW

All have limitations (buffer size, event coalescing). Polling fallback ensures reliability across platforms.