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

Choose your mode:

### App Mode (Full Access)

Use this if you need access to all your chats and full message history.

#### 1. Get Telegram API credentials

1. Go to https://my.telegram.org/apps
2. Log in with your phone number
3. Create a new application
4. Copy the `api_id` and `api_hash`

#### 2. Configure credentials

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

#### 3. First run (login)

```bash
uv run tele --chat "me"
```

You'll be prompted to:
1. Enter your phone number
2. Enter the verification code Telegram sends you

This creates a session file at `~/.tele/tele_tool.session`.

---

### Bot Mode (Easier Setup)

Use this if you only need to monitor specific channels/groups where you can add a bot.

#### 1. Create a bot

1. Open Telegram and search for @BotFather
2. Send `/newbot` and follow the instructions
3. Copy the bot token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

#### 2. Configure

```bash
export TELEGRAM_BOT_TOKEN=your_bot_token
```

#### 3. Run

```bash
# Process all messages the bot can see
uv run tele --bot --exec "your-processor"

# Or filter to specific chat
uv run tele --bot --chat "-1001234567890" --exec "your-processor"
```

**What messages can the bot see?**

| Source | What the bot receives |
|--------|----------------------|
| Private chat (DMs) | All messages sent to the bot |
| Group chat (privacy mode ON) | Only @mentions and commands (e.g., `/start`) |
| Group chat (privacy mode OFF) | All messages |
| Channel | Requires admin - all posts |

Configure privacy mode via @BotFather → `/setprivacy`.

## Next Steps

- [Basic Usage](basic-usage.md) - Common commands
- [Filter Guide](filter-guide.md) - How to filter messages
- [Examples](examples.md) - Real-world use cases
- [Configuration](configuration.md) - All settings