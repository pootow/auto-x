# Requirements

## Purpose

Automate Telegram message processing with:
1. Incremental fetching (reduce API calls)
2. Flexible filtering (DSL expressions)
3. Pipeline integration (JSON Lines stdout)
4. Processing tracking (reactions)

## Use Cases

### Primary: Message Pipeline

```
tele --filter 'DSL' --> stdout --> processor --> tele --mark
```

User runs scheduled jobs to process new messages from chats.

### Secondary: One-off Queries

```bash
tele --chat "work" --search "urgent" --filter '!has_reaction("✅")'
```

Find unprocessed urgent messages.

## Constraints

| Constraint | Rationale |
|------------|-----------|
| JSON Lines output | Stream processing, tool interoperability |
| DSL not SQL | Simpler parsing, Telegram-specific ops |
| State in files | No database dependency |
| Reaction-based marking | Native Telegram feature, visible to users |

## Non-Goals

- Message sending (read-only)
- Real-time monitoring (polling only)
- GUI (CLI only)
- Message storage (output to downstream)

## API Considerations

Telegram limits:
- Search API: No incremental optimization
- Rate limits: Built into Telethon
- Auth: Requires user session (not bot)