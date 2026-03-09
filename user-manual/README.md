# tele User Manual

Command-line tool for automated Telegram message processing.

## Contents

1. [Getting Started](getting-started.md) - Installation and setup
2. [Basic Usage](basic-usage.md) - Common commands and options
3. [Filter Guide](filter-guide.md) - How to write filter expressions
4. [Examples](examples.md) - Real-world use cases
5. [Configuration](configuration.md) - Settings and troubleshooting

## Quick start

### App Mode (full access)

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

### Bot Mode (easier setup)

```bash
# Setup - just get a bot token from @BotFather
uv sync
export TELEGRAM_BOT_TOKEN=your_bot_token

# Run as daemon
uv run tele --bot --chat "-100123456789" --exec "your-processor"
```

## What you need

**App Mode:**
- Python 3.10+
- Telegram account
- API credentials from https://my.telegram.org/apps

**Bot Mode:**
- Python 3.10+
- Bot token from @BotFather (talk to @BotFather on Telegram)
- Bot must be admin in target chat/channel

## Mode Comparison

| Feature | App Mode | Bot Mode |
|---------|----------|----------|
| Setup | Requires API_ID | Just bot token |
| Access | All your chats | Only where bot is admin |
| History | Full history | Only after bot added |
| Search | Yes | No |
| Run style | One-shot commands | Daemon process |
| Auth | Phone login | Token-based |