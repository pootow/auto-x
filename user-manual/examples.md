# Examples

## App Mode Examples

### Example 1: Daily digest

Get all unread messages from important chats:

```bash
#!/bin/bash
# daily-digest.sh

echo "=== Work Chat ==="
uv run tele --chat "work" --filter '!has_reaction("✅")' --limit 20

echo "=== Support Channel ==="
uv run tele --chat "support" --filter '!has_reaction("✅")' --limit 20
```

### Example 2: Extract links

Find messages with URLs and extract them:

```bash
uv run tele --chat "bookmarks" --filter 'contains("http")' | \
  jq -r '.text' | \
  grep -oE 'https?://[^ ]+'
```

### Example 3: Backup messages

Save all messages to a file:

```bash
# Full backup
uv run tele --chat "important" --full > backup_$(date +%Y%m%d).jsonl

# Incremental backup (only new)
uv run tele --chat "important" >> backup.jsonl
```

### Example 4: Process and mark

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

### Example 5: Monitor for keywords

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

### Example 6: Search old messages

Search across all history:

```bash
uv run tele --chat "archive" --search "project name" --full
```

### Example 7: Export to CSV

Convert JSON Lines to CSV:

```bash
uv run tele --chat "data" --full | \
  jq -r '[.id, .sender_id, .date, .text] | @csv' > messages.csv
```

### Example 8: Filter by date range

Get messages from a specific period:

```bash
# After a date
uv run tele --chat "log" --filter 'date > "2024-01-01"' --full

# Note: For complex date ranges, post-process with jq
uv run tele --chat "log" --full | \
  jq 'select(.date >= "2024-01-01" and .date < "2024-02-01")'
```

### Example 9: Scheduled job

Run via cron (crontab -e):

```cron
# Check for new urgent messages every 30 minutes
*/30 * * * * cd /path/to/auto-x && uv run tele --chat "work" --filter 'contains("urgent") && !has_reaction("✅")' | your-handler
```

### Example 10: Multiple chats

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

---

## Bot Mode Examples

### Example 11: Simple notification bot

Monitor a channel and send desktop notifications:

```bash
#!/bin/bash
# bot-notify.sh

uv run tele --bot --chat "-1001234567890" --exec "notify-handler"
```

`notify-handler`:

```python
#!/usr/bin/env python3
import sys
import json
import subprocess

for line in sys.stdin:
    msg = json.loads(line)
    text = msg.get("text", "")

    # Send notification
    subprocess.run(["notify-send", "New Message", text])

    # Output success
    msg["status"] = "success"
    print(json.dumps(msg))
```

### Example 12: URL logger bot

Extract and save URLs from messages:

```bash
#!/bin/bash
# bot-url-logger.sh

uv run tele --bot --chat "-1001234567890" --exec "url-extractor" --mark "🔗"
```

`url-extractor`:

```python
#!/usr/bin/env python3
import sys
import json
import re

URL_PATTERN = re.compile(r'https?://\S+')

for line in sys.stdin:
    msg = json.loads(line)
    text = msg.get("text", "")

    urls = URL_PATTERN.findall(text)
    if urls:
        with open("urls.txt", "a") as f:
            for url in urls:
                f.write(f"{url}\n")

    msg["status"] = "success"
    print(json.dumps(msg))
```

### Example 13: Filter and forward bot

Process only messages matching a filter:

```bash
uv run tele --bot --chat "-1001234567890" \
  --filter 'contains("urgent") || contains("important")' \
  --exec "urgent-handler" \
  --mark "🔴" \
  --failed-mark "⚠️"
```

### Example 14: Batch processor with retry handling

Handle transient failures gracefully:

```python
#!/usr/bin/env python3
# batch-processor.py
import sys
import json
import requests

def process_message(msg):
    try:
        # Your processing logic
        response = requests.post("https://api.example.com/process", json=msg)
        response.raise_for_status()
        return "success"
    except Exception as e:
        print(f"Failed: {e}", file=sys.stderr)
        return "failed"

for line in sys.stdin:
    msg = json.loads(line)
    msg["status"] = process_message(msg)
    print(json.dumps(msg))
```

Run with:

```bash
uv run tele --bot --chat "-1001234567890" \
  --exec "python batch-processor.py" \
  --page-size 20 \
  --interval 5
```

### Example 15: Using -- for complex commands

Avoid shell quoting issues:

```bash
# Complex Python script with arguments
uv run tele --bot --chat "-1001234567890" -- \
  python3 /path/to/processor.py --config /path/to/config.yaml --verbose

# Multiple piped commands (wrap in shell)
uv run tele --bot --chat "-1001234567890" -- \
  sh -c "jq .text | grep -i error | logger -t telegram"
```

### Example 16: Systemd service

Run bot mode as a systemd service:

```ini
# /etc/systemd/system/tele-bot.service
[Unit]
Description=Telegram Bot Processor
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/auto-x
Environment="TELEGRAM_BOT_TOKEN=your_token"
ExecStart=/usr/bin/uv run tele --bot --chat "-1001234567890" --exec "/path/to/processor"
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable tele-bot
sudo systemctl start tele-bot
sudo journalctl -u tele-bot -f  # View logs
```