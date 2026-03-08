# tele - Telegram Message Pipeline

CLI tool for processing Telegram messages. Filter, transform, mark processed.

## Quick Reference

```bash
tele --chat "name" [--search "q"] [--filter 'DSL'] [--full]  # Get messages
tele --mark [--reaction "✅"]                                # Mark from stdin
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
| `tele/client.py` | Telethon wrapper, API operations |
| `tele/filter.py` | DSL lexer/parser/evaluator |
| `tele/state.py` | Incremental processing state |
| `tele/output.py` | JSON Lines serialization |
| `tele/config.py` | YAML/env config loading |

## Testing

```bash
uv run pytest                           # All 60 tests (unit + integration)
uv run pytest tests/test_filter.py      # DSL tests
uv run pytest tests/test_integration.py # Pipeline tests

# Manual Telegram integration (requires credentials)
TELEGRAM_API_ID=x TELEGRAM_API_HASH=y uv run python tests/integration_manual.py
```

## Dependencies

- `telethon` - Telegram MTProto API
- `click` - CLI framework
- `pyyaml` - Config parsing