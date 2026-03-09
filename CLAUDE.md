# tele - Telegram Message Pipeline

CLI tool for processing Telegram messages. Filter, transform, mark processed.

## Quick Reference

```bash
# App mode (MTProto API)
tele --chat "name" [--search "q"] [--filter 'DSL'] [--full]  # Get messages
tele --mark [--reaction "✅"]                                # Mark from stdin

# Bot mode (Bot API daemon)
tele --bot --chat "name" --exec "processor" [--filter 'DSL'] [--page-size 10] [--interval 3]
tele --bot --chat "name" -- <command args...>               # Alternative: -- to avoid quoting
```

## Docs

| File | Purpose | Read When |
|------|---------|-----------|
| [docs/requirements.md](docs/requirements.md) | What/Why | Understanding intent, extending features |
| [docs/architecture.md](docs/architecture.md) | How components work | Modifying internals, debugging |
| [docs/contracts.md](docs/contracts.md) | Interfaces/types | Extending DSL, adding outputs |

## Key Files

| File | Responsibility |
|------|---------------|
| `tele/cli.py` | Entry point, CLI parsing, orchestration |
| `tele/client.py` | Telethon wrapper (MTProto API) |
| `tele/bot_client.py` | Bot API client (HTTP polling) |
| `tele/filter.py` | DSL lexer/parser/evaluator |
| `tele/state.py` | Incremental processing state |
| `tele/output.py` | JSON Lines serialization |
| `tele/config.py` | YAML/env config loading |

## Modes

| Mode | API | State File | Use Case |
|------|-----|------------|----------|
| App | MTProto (Telethon) | `{chat_id}.json` | Manual queries, scheduled jobs |
| Bot | Bot API (HTTP) | `bot_{chat_id}.json` | Daemon monitoring, automation |

## Testing

```bash
uv run pytest                           # All tests (unit + integration)
uv run pytest tests/test_filter.py      # DSL tests
uv run pytest tests/test_integration.py # Pipeline tests

# Manual Telegram integration (requires credentials)
TELEGRAM_API_ID=x TELEGRAM_API_HASH=y uv run python tests/integration_manual.py
TELEGRAM_BOT_TOKEN=x uv run python tests/integration_manual.py --bot
```

## Dependencies

- `telethon` - Telegram MTProto API (app mode)
- `aiohttp` - HTTP client (bot mode)
- `click` - CLI framework
- `pyyaml` - Config parsing