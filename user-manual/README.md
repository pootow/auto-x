# tele User Manual

Command-line tool for automated Telegram message processing.

## Contents

1. [Getting Started](getting-started.md) - Installation and setup
2. [Basic Usage](basic-usage.md) - Common commands and options
3. [Filter Guide](filter-guide.md) - How to write filter expressions
4. [Examples](examples.md) - Real-world use cases
5. [Configuration](configuration.md) - Settings and troubleshooting

## Quick start

```bash
# Setup
uv sync
export TELEGRAM_API_ID=your_id
export TELEGRAM_API_HASH=your_hash

# Login (first time only)
uv run tele --chat "me"

# Get messages
uv run tele --chat "work"

# Filter messages
uv run tele --chat "work" --filter 'contains("urgent")'

# Process and mark
uv run tele --chat "work" | your-script | uv run tele --mark
```

## What you need

- Python 3.10+
- Telegram account
- API credentials from https://my.telegram.org/apps