# Requirements

## Purpose

Automate Telegram message processing with:
1. Incremental fetching (reduce API calls)
2. Flexible filtering (DSL expressions)
3. Pipeline integration (JSON Lines stdout)
4. Processing tracking (reactions)

## Use Cases

### App Mode: Message Pipeline

```
tele --filter 'DSL' --> stdout --> processor --> tele --mark
```

User runs scheduled jobs to process new messages from chats.

### App Mode: One-off Queries

```bash
tele --chat "work" --search "urgent" --filter '!has_reaction("✅")'
```

Find unprocessed urgent messages.

### Bot Mode: Daemon Monitoring

```bash
tele --bot --chat "updates" --exec "my-processor" --filter 'important' --page-size 10 --interval 3
```

Bot runs as foreground daemon, polls for new messages, batches them, pipes to processor.

**Bot Mode Flow**:
1. Poll for updates via Bot API `getUpdates`
2. Apply `--filter` (optional, default = all messages)
3. Accumulate until `--page-size` reached OR `--interval` seconds of silence (debounce)
4. Pipe batch to `--exec` command via stdin (JSON Lines)
5. Mark based on stdout `status` field: `--mark` (✅) or `--failed-mark` (❌)
6. Update offset only on success

**Bot Mode Constraints**:
- Bot receives messages based on privacy mode:
  - Private DMs: all messages
  - Groups (privacy ON): @mentions and commands only
  - Groups (privacy OFF): all messages
  - Channels: requires admin, all posts
- No search support (Bot API limitation)
- At-least-once delivery (processor must be idempotent)

### Ingest Mode: External Data Sources

```bash
tele --ingest                    # Start daemon (watchdog + polling)
tele --scan                      # Scan all sources once
tele --process-source web_monitor  # Process specific source
```

External data sources (web monitors, RSS feeds, custom scripts) write to append-only JSONL files. Tele consumes and processes through existing pipeline.

**Ingest Mode Flow**:
1. Data source appends messages to `incoming.{date}.jsonl`
2. Watchdog detects file change (immediate) OR polling scans (fallback)
3. Read from last byte offset, process new messages
4. Pipe to configured processor via stdin (JSON Lines)
5. Update byte offset on success

**Ingest Mode Constraints**:
- File-based communication (no HTTP/TCP)
- Append-only files preserved as audit logs
- Date in filename must increase monotonically
- Cross-platform: watchdog + polling fallback

## Constraints

| Constraint | Rationale |
|------------|-----------|
| JSON Lines output | Stream processing, tool interoperability |
| DSL not SQL | Simpler parsing, Telegram-specific ops |
| State in files | No database dependency |
| Reaction-based marking | Native Telegram feature, visible to users |
| `status` field in output | Unified success/failure marking |

## Non-Goals

- Message sending (read-only)
- Real-time monitoring (polling only)
- GUI (CLI only)
- Message storage (output to downstream)
- Webhook mode (polling only)

## API Considerations

### MTProto (App Mode)
- Search API: No incremental optimization
- Rate limits: Built into Telethon
- Auth: Requires user session (not bot)

### Bot API (Bot Mode)
- getUpdates long polling for receiving
- Bot must be channel/group admin
- No history access before bot addition
- Rate limits: 30 msg/sec to same chat