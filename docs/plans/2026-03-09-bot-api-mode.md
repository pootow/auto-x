# Bot API Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Bot API mode for users without API_ID access, enabling daemon-style message processing via Bot API polling.

**Architecture:** Create `BotClient` class for Bot API HTTP operations, modify CLI to support `--bot` flag with daemon mode, update `output.py` to include `status` field, refactor state management for offset-based tracking in bot mode.

**Tech Stack:** aiohttp (Bot API HTTP), click (CLI), existing filter/output components

---

## Task 1: Add aiohttp Dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add aiohttp to dependencies**

```toml
dependencies = [
    "telethon>=1.28.0",
    "click>=8.0.0",
    "pyyaml>=6.0",
    "aiohttp>=3.8.0",
]
```

**Step 2: Install dependency**

Run: `uv sync`

Expected: aiohttp installed successfully

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add aiohttp for Bot API support"
```

---

## Task 2: Add status Field to Output Format

**Files:**
- Modify: `tele/output.py`
- Modify: `tests/test_output.py`

**Step 1: Write the failing test**

```python
# tests/test_output.py - add to existing file

def test_format_message_includes_status():
    """Output should include status field with default 'pending'."""
    from tele.output import format_message
    from unittest.mock import MagicMock

    msg = MagicMock()
    msg.id = 123
    msg.text = "test"
    msg.sender_id = 456
    msg.date = None
    msg.chat_id = 789
    msg.forward = None
    msg.media = None
    msg.reactions = None

    result = format_message(msg)
    assert result["status"] == "pending"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_output.py::test_format_message_includes_status -v`

Expected: FAIL with "KeyError: 'status'"

**Step 3: Modify format_message to include status**

```python
# tele/output.py - modify format_message function

def format_message(message, status: str = "pending") -> dict:
    """Format a message for JSON output.

    Args:
        message: Telethon Message or Bot API message dict
        status: Processing status (pending, success, failed)

    Returns:
        dict suitable for JSON serialization
    """
    # ... existing field extraction ...

    data["status"] = status

    return data
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_output.py::test_format_message_includes_status -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tele/output.py tests/test_output.py
git commit -m "feat(output): add status field to output format"
```

---

## Task 3: Add Bot Token to Config

**Files:**
- Modify: `tele/config.py`
- Modify: `tests/test_config.py`

**Step 1: Write the failing test**

```python
# tests/test_config.py - add to existing file

def test_config_loads_bot_token_from_env():
    """Config should load TELEGRAM_BOT_TOKEN from environment."""
    import os
    from tele.config import ConfigManager

    os.environ["TELEGRAM_BOT_TOKEN"] = "test_token_123"
    manager = ConfigManager()
    config = manager.load()

    assert config.telegram.bot_token == "test_token_123"

    del os.environ["TELEGRAM_BOT_TOKEN"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_config_loads_bot_token_from_env -v`

Expected: FAIL

**Step 3: Add bot_token to TelegramConfig**

```python
# tele/config.py - modify TelegramConfig

@dataclass
class TelegramConfig:
    """Telegram API configuration."""
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    bot_token: Optional[str] = None
    session_name: str = "tele_tool"
```

**Step 4: Add env var loading in ConfigManager.load()**

```python
# tele/config.py - in ConfigManager.load() method

bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
if bot_token:
    config.telegram.bot_token = bot_token
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::test_config_loads_bot_token_from_env -v`

Expected: PASS

**Step 6: Commit**

```bash
git add tele/config.py tests/test_config.py
git commit -m "feat(config): add bot_token support"
```

---

## Task 4: Add Bot State Management

**Files:**
- Modify: `tele/state.py`
- Create: `tests/test_bot_state.py`

**Step 1: Write the failing test**

```python
# tests/test_bot_state.py - new file

import pytest
import tempfile
import os
from tele.state import BotStateManager

def test_bot_state_loads_offset():
    """BotStateManager should load offset from state file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_file = os.path.join(tmpdir, "bot_123.json")
        with open(state_file, "w") as f:
            f.write('{"last_update_id": 456, "last_processed_at": "2024-01-15T10:00:00Z"}')

        manager = BotStateManager(tmpdir)
        state = manager.load(123)

        assert state["last_update_id"] == 456

def test_bot_state_saves_offset():
    """BotStateManager should save offset to state file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = BotStateManager(tmpdir)
        manager.save(123, 789)

        state = manager.load(123)
        assert state["last_update_id"] == 789
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bot_state.py -v`

Expected: FAIL with "ImportError" or "NameError"

**Step 3: Implement BotStateManager**

```python
# tele/state.py - add to existing file

import json
from datetime import datetime, timezone

class BotStateManager:
    """Manages bot mode state (offset-based)."""

    def __init__(self, state_dir: Optional[str] = None):
        if state_dir is None:
            state_dir = os.path.expanduser("~/.tele/state")
        self.state_dir = state_dir
        os.makedirs(state_dir, exist_ok=True)

    def _state_path(self, chat_id: int) -> str:
        return os.path.join(self.state_dir, f"bot_{chat_id}.json")

    def load(self, chat_id: int) -> dict:
        """Load bot state for a chat.

        Returns:
            dict with last_update_id (0 if no state) and last_processed_at
        """
        path = self._state_path(chat_id)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return {"last_update_id": 0, "last_processed_at": None}

    def save(self, chat_id: int, update_id: int) -> None:
        """Save bot state after successful processing."""
        path = self._state_path(chat_id)
        state = {
            "last_update_id": update_id,
            "last_processed_at": datetime.now(timezone.utc).isoformat()
        }
        with open(path, "w") as f:
            json.dump(state, f)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bot_state.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tele/state.py tests/test_bot_state.py
git commit -m "feat(state): add BotStateManager for offset-based tracking"
```

---

## Task 5: Create BotClient Class

**Files:**
- Create: `tele/bot_client.py`
- Create: `tests/test_bot_client.py`

**Step 1: Write the failing test for poll_updates**

```python
# tests/test_bot_client.py - new file

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from tele.bot_client import BotClient

@pytest.mark.asyncio
async def test_poll_updates_returns_messages():
    """BotClient.poll_updates should return list of updates."""
    client = BotClient("test_token")

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={
            "ok": True,
            "result": [
                {"update_id": 1, "message": {"message_id": 100, "text": "hello"}}
            ]
        })
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_get.return_value.__aexit__ = AsyncMock()

        updates = await client.poll_updates(offset=0)
        assert len(updates) == 1
        assert updates[0]["update_id"] == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bot_client.py -v`

Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement BotClient skeleton with poll_updates**

```python
# tele/bot_client.py - new file

"""Bot API client for Telegram operations."""

import aiohttp
from typing import Optional, List, Dict, Any


class BotClient:
    """Bot API client using HTTP long polling."""

    API_BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, timeout: int = 30):
        """Initialize Bot API client.

        Args:
            token: Bot token from @BotFather
            timeout: Long polling timeout in seconds
        """
        self.token = token
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _call_api(self, method: str, params: dict = None) -> dict:
        """Call Bot API method.

        Args:
            method: API method name
            params: Method parameters

        Returns:
            API response data
        """
        session = await self._get_session()
        url = self.API_BASE.format(token=self.token, method=method)

        async with session.post(url, json=params or {}) as response:
            response.raise_for_status()
            data = await response.json()
            if not data.get("ok"):
                raise RuntimeError(f"API error: {data.get('description')}")
            return data.get("result", {})

    async def poll_updates(self, offset: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
        """Poll for new updates using long polling.

        Args:
            offset: Start from this update_id
            limit: Max updates to fetch

        Returns:
            List of update objects
        """
        params = {
            "offset": offset,
            "limit": limit,
            "timeout": self.timeout,
            "allowed_updates": ["message", "channel_post"]
        }
        return await self._call_api("getUpdates", params)

    async def add_reaction(
        self,
        chat_id: int,
        message_id: int,
        emoji: str = "✅"
    ) -> bool:
        """Add reaction to a message.

        Args:
            chat_id: Target chat ID
            message_id: Message ID
            emoji: Reaction emoji

        Returns:
            True if successful
        """
        await self._call_api("setMessageReaction", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}]
        })
        return True
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bot_client.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tele/bot_client.py tests/test_bot_client.py
git commit -m "feat(bot_client): create BotClient with poll_updates and add_reaction"
```

---

## Task 6: Add Message Normalization for Bot API

**Files:**
- Modify: `tele/output.py`
- Modify: `tests/test_output.py`

**Step 1: Write the failing test**

```python
# tests/test_output.py - add test

def test_format_message_from_bot_api():
    """format_message should handle Bot API message dict."""
    from tele.output import format_message

    bot_message = {
        "message_id": 123,
        "text": "hello from bot",
        "from": {"id": 456},
        "date": 1705312800,  # Unix timestamp
        "chat": {"id": 789}
    }

    result = format_message(bot_message)
    assert result["id"] == 123
    assert result["text"] == "hello from bot"
    assert result["sender_id"] == 456
    assert result["chat_id"] == 789
    assert result["status"] == "pending"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_output.py::test_format_message_from_bot_api -v`

Expected: FAIL

**Step 3: Update format_message to handle both formats**

```python
# tele/output.py - modify format_message

from datetime import datetime

def format_message(message, status: str = "pending") -> dict:
    """Format a message for JSON output.

    Handles both Telethon Message objects and Bot API message dicts.

    Args:
        message: Telethon Message or Bot API message dict
        status: Processing status (pending, success, failed)

    Returns:
        dict suitable for JSON serialization
    """
    if isinstance(message, dict):
        # Bot API format
        data = {
            "id": message.get("message_id"),
            "text": message.get("text"),
            "sender_id": message.get("from", {}).get("id"),
            "chat_id": message.get("chat", {}).get("id"),
            "status": status,
        }
        # Convert Unix timestamp to ISO
        if message.get("date"):
            data["date"] = datetime.utcfromtimestamp(message["date"]).isoformat()
        else:
            data["date"] = None
    else:
        # Telethon Message format (existing logic)
        data = {
            "id": message.id,
            "text": message.text,
            "sender_id": message.sender_id,
            "date": message.date.isoformat() if message.date else None,
            "chat_id": message.chat_id,
            "status": status,
        }
        # ... rest of existing Telethon field extraction ...

    return data
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_output.py::test_format_message_from_bot_api -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tele/output.py tests/test_output.py
git commit -m "feat(output): support Bot API message format in format_message"
```

---

## Task 7: Add Batcher Utility for Bot Mode

**Files:**
- Create: `tele/batcher.py`
- Create: `tests/test_batcher.py`

**Step 1: Write the failing test**

```python
# tests/test_batcher.py - new file

import asyncio
import pytest
from tele.batcher import MessageBatcher

@pytest.mark.asyncio
async def test_batcher_accumulates_messages():
    """MessageBatcher should accumulate messages until page_size."""
    batcher = MessageBatcher(page_size=3, interval=10.0)
    results = []

    async def on_batch(messages):
        results.append(messages)

    batcher.on_batch = on_batch

    await batcher.add({"id": 1})
    await batcher.add({"id": 2})
    assert len(results) == 0  # Not yet

    await batcher.add({"id": 3})
    await asyncio.sleep(0.1)  # Let callback execute

    assert len(results) == 1
    assert len(results[0]) == 3

@pytest.mark.asyncio
async def test_batcher_flushes_on_interval():
    """MessageBatcher should flush after interval of silence."""
    batcher = MessageBatcher(page_size=100, interval=0.1)
    results = []

    async def on_batch(messages):
        results.append(messages)

    batcher.on_batch = on_batch

    await batcher.add({"id": 1})
    assert len(results) == 0

    await asyncio.sleep(0.2)  # Wait for debounce

    assert len(results) == 1
    assert len(results[0]) == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_batcher.py -v`

Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement MessageBatcher**

```python
# tele/batcher.py - new file

"""Message batching utility for bot mode."""

import asyncio
from typing import List, Callable, Any, Optional


class MessageBatcher:
    """Accumulates messages and flushes on page_size or debounce interval."""

    def __init__(self, page_size: int = 10, interval: float = 3.0):
        """Initialize batcher.

        Args:
            page_size: Max messages per batch
            interval: Debounce interval in seconds
        """
        self.page_size = page_size
        self.interval = interval
        self._messages: List[Any] = []
        self._flush_task: Optional[asyncio.Task] = None
        self.on_batch: Optional[Callable] = None

    async def add(self, message: Any) -> None:
        """Add a message to the batch.

        Triggers flush if page_size reached, otherwise schedules debounce flush.
        """
        self._messages.append(message)

        # Cancel pending flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Flush immediately if page_size reached
        if len(self._messages) >= self.page_size:
            await self._flush()
        else:
            # Schedule debounce flush
            self._flush_task = asyncio.create_task(self._debounced_flush())

    async def _debounced_flush(self) -> None:
        """Wait for interval, then flush if still pending."""
        await asyncio.sleep(self.interval)
        if self._messages:
            await self._flush()

    async def _flush(self) -> None:
        """Flush accumulated messages to callback."""
        if not self._messages:
            return

        batch = self._messages[:]
        self._messages = []

        if self.on_batch:
            await self.on_batch(batch)

    async def flush_remaining(self) -> None:
        """Flush any remaining messages (for shutdown)."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_batcher.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tele/batcher.py tests/test_batcher.py
git commit -m "feat(batcher): add MessageBatcher for bot mode debouncing"
```

---

## Task 8: Add Executor Utility for Bot Mode

**Files:**
- Create: `tele/executor.py`
- Create: `tests/test_executor.py`

**Step 1: Write the failing test**

```python
# tests/test_executor.py - new file

import pytest
from tele.executor import run_exec_command

@pytest.mark.asyncio
async def test_exec_command_processes_messages():
    """run_exec_command should pipe messages to command and parse output."""
    messages = [
        {"id": 1, "text": "hello", "status": "pending"},
        {"id": 2, "text": "world", "status": "pending"},
    ]

    # Use cat as echo to pass through (simulates identity processor)
    result = await run_exec_command("cat", messages)

    assert len(result) == 2
    assert result[0]["id"] == 1

@pytest.mark.asyncio
async def test_exec_command_parses_status():
    """run_exec_command should parse status field from output."""
    import json

    messages = [{"id": 1, "text": "test", "status": "pending"}]

    # Use echo to output a modified message
    result = await run_exec_command(
        "echo '{\"id\": 1, \"status\": \"success\"}'",
        messages,
        shell=True
    )

    assert result[0]["status"] == "success"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_executor.py -v`

Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement executor**

```python
# tele/executor.py - new file

"""Command execution utility for bot mode."""

import asyncio
import json
from typing import List, Dict, Any, Optional


async def run_exec_command(
    command: str,
    messages: List[Dict[str, Any]],
    shell: bool = False
) -> List[Dict[str, Any]]:
    """Run external command with messages as stdin, parse stdout for results.

    Args:
        command: Command to execute
        messages: List of message dicts to send as JSON Lines
        shell: Use shell execution

    Returns:
        List of message dicts from stdout (with status field)

    Raises:
        RuntimeError: If command fails
    """
    # Prepare stdin as JSON Lines
    stdin_data = "\n".join(json.dumps(msg) for msg in messages)

    # Execute command
    if shell:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *command.split(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    stdout, stderr = await proc.communicate(stdin_data.encode())

    if proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {stderr.decode()}")

    # Parse stdout as JSON Lines
    results = []
    for line in stdout.decode().strip().split("\n"):
        if line:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # Skip invalid lines

    return results
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_executor.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tele/executor.py tests/test_executor.py
git commit -m "feat(executor): add command execution for bot mode processing"
```

---

## Task 9: Add Bot Mode to CLI

**Files:**
- Modify: `tele/cli.py`
- Modify: `tests/test_integration.py`

**Step 1: Write the failing test**

```python
# tests/test_integration.py - add test

import pytest
from click.testing import CliRunner
from tele.cli import cli

def test_cli_bot_mode_requires_exec():
    """Bot mode should require --exec or -- separator."""
    runner = CliRunner()

    result = runner.invoke(cli, ["--bot", "--chat", "test"])

    assert result.exit_code != 0
    assert "exec" in result.output.lower() or "required" in result.output.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_integration.py::test_cli_bot_mode_requires_exec -v`

Expected: FAIL

**Step 3: Modify CLI to add bot mode**

```python
# tele/cli.py - add imports and bot mode

import click
import asyncio
import json
from typing import Optional, List

from tele.config import load_config
from tele.client import TeleClient
from tele.bot_client import BotClient
from tele.filter import MessageFilter
from tele.output import format_message
from tele.state import StateManager, BotStateManager
from tele.batcher import MessageBatcher
from tele.executor import run_exec_command


@click.group()
@click.option("--bot", is_flag=True, help="Use Bot API mode (daemon)")
@click.option("--chat", help="Target chat name or ID")
@click.option("--filter", "filter_expr", help="DSL filter expression")
@click.option("--page-size", default=10, help="Messages per batch")
@click.option("--interval", default=3, help="Debounce interval (bot mode)")
@click.option("--exec", "exec_cmd", help="Command to process messages (bot mode)")
@click.option("--mark", default="✅", help="Success reaction emoji")
@click.option("--failed-mark", default="❌", help="Failure reaction emoji")
@click.option("--search", help="Search query (app mode only)")
@click.option("--full", is_flag=True, help="Ignore state (app mode only)")
@click.pass_context
def cli(ctx, bot, chat, filter_expr, page_size, interval, exec_cmd, mark, failed_mark, search, full):
    """Telegram message processing pipeline."""
    ctx.ensure_object(dict)
    ctx.obj.update({
        "bot_mode": bot,
        "chat": chat,
        "filter_expr": filter_expr,
        "page_size": page_size,
        "interval": interval,
        "exec_cmd": exec_cmd,
        "mark": mark,
        "failed_mark": failed_mark,
        "search": search,
        "full": full,
    })


@cli.command()
@click.pass_context
def get(ctx):
    """Get messages (app mode, default command)."""
    if ctx.obj.get("bot_mode"):
        raise click.UsageError("Use --exec with --bot mode, not 'get'")

    # Existing app mode logic...
    asyncio.run(run_app_mode(ctx.obj))


@cli.command()
@click.pass_context
def mark(ctx):
    """Mark messages from stdin (app mode)."""
    # Existing mark logic...
    asyncio.run(run_mark_mode(ctx.obj))


# Add default command for bot mode
@cli.result_callback()
@click.pass_context
def process_result(ctx, result, **kwargs):
    """Handle bot mode when no subcommand specified."""
    if ctx.obj.get("bot_mode"):
        if not ctx.obj.get("exec_cmd"):
            raise click.UsageError("--bot mode requires --exec <command>")
        asyncio.run(run_bot_mode(ctx.obj))


async def run_bot_mode(opts: dict):
    """Run bot mode daemon loop."""
    config = load_config()

    if not config.telegram.bot_token:
        raise click.ClickException("TELEGRAM_BOT_TOKEN required for bot mode")

    client = BotClient(config.telegram.bot_token)
    chat = opts["chat"]
    if not chat:
        raise click.ClickException("--chat required for bot mode")

    # Resolve chat ID (bot must be admin)
    # For simplicity, assume chat is numeric ID or @username
    try:
        chat_id = int(chat.lstrip("@"))
    except ValueError:
        raise click.ClickException("Chat must be numeric ID in bot mode")

    state_mgr = BotStateManager()
    msg_filter = MessageFilter(opts["filter_expr"]) if opts["filter_expr"] else None

    batcher = MessageBatcher(page_size=opts["page_size"], interval=opts["interval"])
    batcher.on_batch = lambda msgs: process_batch(
        client, msgs, opts, chat_id, state_mgr, msg_filter
    )

    offset = state_mgr.load(chat_id).get("last_update_id", 0)

    try:
        while True:
            updates = await client.poll_updates(offset=offset + 1)

            for update in updates:
                offset = update["update_id"]

                # Extract message from update
                message = update.get("message") or update.get("channel_post")
                if not message:
                    continue

                # Filter chat
                if message.get("chat", {}).get("id") != chat_id:
                    continue

                # Apply filter
                if msg_filter and not msg_filter.evaluate(message):
                    continue

                # Add to batcher
                formatted = format_message(message)
                await batcher.add(formatted)

    except KeyboardInterrupt:
        await batcher.flush_remaining()
    finally:
        await client.close()


async def process_batch(client, messages, opts, chat_id, state_mgr, msg_filter):
    """Process a batch of messages through exec command."""
    exec_cmd = opts["exec_cmd"]

    try:
        results = await run_exec_command(exec_cmd, messages)

        # Mark messages based on status
        for result in results:
            msg_id = result.get("id")
            status = result.get("status", "success")

            emoji = opts["mark"] if status == "success" else opts["failed_mark"]
            try:
                await client.add_reaction(chat_id, msg_id, emoji)
            except Exception as e:
                print(f"Failed to mark message {msg_id}: {e}")

        # Update offset on success
        if results:
            last_id = max(m.get("id", 0) for m in messages)
            state_mgr.save(chat_id, last_id)

    except Exception as e:
        print(f"Batch processing failed: {e}")
        # Don't update state - will retry
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_integration.py::test_cli_bot_mode_requires_exec -v`

Expected: PASS

**Step 5: Commit**

```bash
git add tele/cli.py tests/test_integration.py
git commit -m "feat(cli): add bot mode with --exec and daemon loop"
```

---

## Task 10: Update Existing Tests for status Field

**Files:**
- Modify: `tests/test_output.py`
- Modify: `tests/test_integration.py`

**Step 1: Update existing tests that expect old output format**

```python
# tests/test_output.py - update existing tests

def test_format_message_basic():
    """Test basic message formatting."""
    # ... existing test code ...
    result = format_message(msg)
    # Add status assertion
    assert "status" in result
```

**Step 2: Run all tests to verify nothing broke**

Run: `uv run pytest -v`

Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/
git commit -m "test: update tests for status field in output"
```

---

## Task 11: Integration Test for Bot Mode

**Files:**
- Create: `tests/test_bot_integration.py`

**Step 1: Write integration test**

```python
# tests/test_bot_integration.py - new file

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from tele.bot_client import BotClient
from tele.batcher import MessageBatcher
from tele.executor import run_exec_command
from tele.output import format_message


@pytest.mark.asyncio
async def test_bot_mode_end_to_end():
    """Test complete bot mode flow: poll -> filter -> batch -> exec -> mark."""
    # Setup
    client = BotClient("test_token")
    batch_results = []

    async def capture_batch(messages):
        batch_results.append(messages)

    batcher = MessageBatcher(page_size=2, interval=0.1)
    batcher.on_batch = capture_batch

    # Simulate messages
    msg1 = {"message_id": 1, "text": "hello", "from": {"id": 123}, "chat": {"id": 456}, "date": 1705312800}
    msg2 = {"message_id": 2, "text": "world", "from": {"id": 123}, "chat": {"id": 456}, "date": 1705312800}

    formatted1 = format_message(msg1)
    formatted2 = format_message(msg2)

    await batcher.add(formatted1)
    await batcher.add(formatted2)

    await asyncio.sleep(0.2)  # Let batch process

    assert len(batch_results) == 1
    assert len(batch_results[0]) == 2
    assert batch_results[0][0]["status"] == "pending"
```

**Step 2: Run test**

Run: `uv run pytest tests/test_bot_integration.py -v`

Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_bot_integration.py
git commit -m "test: add bot mode integration test"
```

---

## Task 12: Run Full Test Suite

**Step 1: Run all tests**

Run: `uv run pytest -v`

Expected: All tests PASS

**Step 2: Fix any failures**

If tests fail, debug and fix.

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete bot API mode implementation"
```

---

## Summary

**New Files:**
- `tele/bot_client.py` - Bot API HTTP client
- `tele/batcher.py` - Message debouncing utility
- `tele/executor.py` - External command execution
- `tests/test_bot_client.py`
- `tests/test_bot_state.py`
- `tests/test_batcher.py`
- `tests/test_executor.py`
- `tests/test_bot_integration.py`

**Modified Files:**
- `tele/cli.py` - Bot mode orchestration
- `tele/config.py` - bot_token support
- `tele/state.py` - BotStateManager
- `tele/output.py` - status field, Bot API message support
- `tests/test_output.py`
- `tests/test_config.py`
- `tests/test_integration.py`
- `pyproject.toml` - aiohttp dependency