# Filter Guide

Filters let you select which messages to process.

## Basic syntax

```bash
uv run tele --chat "work" --filter 'EXPRESSION'
```

## Text matching

```bash
# Message contains text
contains("urgent")

# Multiple keywords (OR)
contains("urgent") || contains("important")

# Case matters - be specific
contains("URGENT")
```

## Sender filtering

```bash
# From specific user ID
sender_id == 12345678

# NOT from a user
sender_id != 12345678
```

## Message properties

```bash
# Has media attachment
has_media

# Is a forwarded message
is_forwarded

# Has specific reaction
has_reaction("✅")

# NOT processed yet
!has_reaction("✅")
```

## Message ID and date

```bash
# By message ID
message_id > 1000

# By date (ISO format)
date > "2024-01-01"
```

## Combining filters

```bash
# AND - both must be true
contains("urgent") && sender_id == 12345678

# OR - either can be true
contains("urgent") || contains("important")

# NOT - invert the condition
!has_reaction("✅")

# Grouping with parentheses
(contains("urgent") || contains("important")) && !has_reaction("✅")
```

## Comparison operators

| Operator | Meaning |
|----------|---------|
| `==` | Equal |
| `!=` | Not equal |
| `>` | Greater than |
| `>=` | Greater or equal |
| `<` | Less than |
| `<=` | Less or equal |

## Common patterns

### Find unprocessed urgent messages

```bash
uv run tele --chat "work" --filter 'contains("urgent") && !has_reaction("✅")'
```

### Messages from specific user with media

```bash
uv run tele --chat "group" --filter 'sender_id == 12345678 && has_media'
```

### Exclude forwarded messages

```bash
uv run tele --chat "channel" --filter '!is_forwarded'
```

## Quick reference

| Filter | Description |
|--------|-------------|
| `contains("text")` | Text contains substring |
| `sender_id == N` | From user ID N |
| `has_media` | Has attachment |
| `is_forwarded` | Is forwarded |
| `has_reaction("✅")` | Has reaction |
| `message_id > N` | ID greater than N |
| `!FILTER` | Invert filter |
| `A && B` | Both true |
| `A \|\| B` | Either true |