# Examples

## Example 1: Daily digest

Get all unread messages from important chats:

```bash
#!/bin/bash
# daily-digest.sh

echo "=== Work Chat ==="
uv run tele --chat "work" --filter '!has_reaction("✅")' --limit 20

echo "=== Support Channel ==="
uv run tele --chat "support" --filter '!has_reaction("✅")' --limit 20
```

## Example 2: Extract links

Find messages with URLs and extract them:

```bash
uv run tele --chat "bookmarks" --filter 'contains("http")' | \
  jq -r '.text' | \
  grep -oE 'https?://[^ ]+'
```

## Example 3: Backup messages

Save all messages to a file:

```bash
# Full backup
uv run tele --chat "important" --full > backup_$(date +%Y%m%d).jsonl

# Incremental backup (only new)
uv run tele --chat "important" >> backup.jsonl
```

## Example 4: Process and mark

Filter, process with a script, mark as done:

```bash
uv run tele --chat "tasks" --filter 'contains("TODO") && !has_reaction("✅")' | \
  while read line; do
    # Your processing logic here
    echo "$line" | your-task-processor

    # Pass through to mark
    echo "$line"
  done | \
  uv run tele --mark
```

## Example 5: Monitor for keywords

Alert on specific keywords (run periodically):

```bash
#!/bin/bash
# monitor.sh

KEYWORDS='contains("urgent") || contains("critical") || contains("down")'

uv run tele --chat "alerts" --filter "$KEYWORDS && !has_reaction(\"🔔\")" | \
  while read msg; do
    # Send notification (example: using notify-send on Linux)
    text=$(echo "$msg" | jq -r '.text')
    notify-send "Telegram Alert" "$text"

    # Mark as seen
    echo "$msg"
  done | \
  uv run tele --mark --reaction "🔔"
```

## Example 6: Search old messages

Search across all history:

```bash
uv run tele --chat "archive" --search "project name" --full
```

## Example 7: Export to CSV

Convert JSON Lines to CSV:

```bash
uv run tele --chat "data" --full | \
  jq -r '[.id, .sender_id, .date, .text] | @csv' > messages.csv
```

## Example 8: Filter by date range

Get messages from a specific period:

```bash
# After a date
uv run tele --chat "log" --filter 'date > "2024-01-01"' --full

# Note: For complex date ranges, post-process with jq
uv run tele --chat "log" --full | \
  jq 'select(.date >= "2024-01-01" and .date < "2024-02-01")'
```

## Example 9: Scheduled job

Run via cron (crontab -e):

```cron
# Check for new urgent messages every 30 minutes
*/30 * * * * cd /path/to/auto-x && uv run tele --chat "work" --filter 'contains("urgent") && !has_reaction("✅")' | your-handler
```

## Example 10: Multiple chats

Process several chats in one script:

```bash
#!/bin/bash
# process-chats.sh

CHATS=("work" "family" "news")

for chat in "${CHATS[@]}"; do
  echo "Processing $chat..."
  uv run tele --chat "$chat" | process-messages
done
```