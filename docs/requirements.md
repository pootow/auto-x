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
- Bot must be admin in target chat/channel
- Only sees messages after bot was added
- No search support (Bot API limitation)
- At-least-once delivery (processor must be idempotent)

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