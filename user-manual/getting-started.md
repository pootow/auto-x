# tele - Getting Started

A command-line tool to process Telegram messages automatically.

## What it does

- Fetches messages from Telegram chats
- Filters messages using simple expressions
- Outputs messages for other tools to process
- Tracks which messages you've already handled

## Installation

```bash
cd /path/to/auto-x
uv sync
```

## Setup

### 1. Get Telegram API credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application
4. Copy the `api_id` and `api_hash`

### 2. Configure credentials

Create `~/.tele/config.yaml`:

```yaml
telegram:
  api_id: YOUR_API_ID
  api_hash: "YOUR_API_HASH"
```

Or set environment variables:

```bash
export TELEGRAM_API_ID=your_id
export TELEGRAM_API_HASH=your_hash
```

### 3. First run (login)

```bash
uv run tele --chat "me"
```

You'll be prompted to:
1. Enter your phone number
2. Enter the verification code Telegram sends you

This creates a session file at `~/.tele/tele_tool.session`.

## Next Steps

- [Basic Usage](basic-usage.md) - Common commands
- [Filter Guide](filter-guide.md) - How to filter messages
- [Examples](examples.md) - Real-world use cases