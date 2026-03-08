#!/usr/bin/env python
"""
Manual integration tests requiring real Telegram credentials.

Run with: uv run python tests/integration_manual.py

Prerequisites:
1. Set TELEGRAM_API_ID and TELEGRAM_API_HASH env vars
2. Have a test chat available (set TEST_CHAT_NAME env var)
3. First run will prompt for Telegram login code
"""

import asyncio
import os
import sys
from datetime import datetime

# Check for credentials
if not os.environ.get("TELEGRAM_API_ID") or not os.environ.get("TELEGRAM_API_HASH"):
    print("ERROR: Set TELEGRAM_API_ID and TELEGRAM_API_HASH environment variables")
    sys.exit(1)

TEST_CHAT = os.environ.get("TEST_CHAT_NAME", "me")  # "me" = saved messages


async def test_connection():
    """Test basic Telegram connection."""
    from tele.client import TeleClient
    from tele.config import load_config

    print("\n[TEST] Connection...")

    config = load_config()
    client = TeleClient(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
    )

    await client.connect()

    if not await client.client.is_user_authorized():
        print("ERROR: Not authorized. Run interactively first to login.")
        await client.disconnect()
        return False

    print("[PASS] Connected and authorized")
    await client.disconnect()
    return True


async def test_resolve_chat():
    """Test chat resolution."""
    from tele.client import TeleClient
    from tele.config import load_config

    print(f"\n[TEST] Resolving chat '{TEST_CHAT}'...")

    config = load_config()
    client = TeleClient(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
    )

    await client.connect()

    try:
        peer = await client.resolve_chat(TEST_CHAT)
        chat_id = await client.get_chat_id(TEST_CHAT)
        print(f"[PASS] Resolved to peer type: {type(peer).__name__}, id: {chat_id}")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False
    finally:
        await client.disconnect()


async def test_get_messages():
    """Test fetching messages."""
    from tele.client import TeleClient
    from tele.config import load_config
    from tele.output import format_message

    print(f"\n[TEST] Fetching messages from '{TEST_CHAT}'...")

    config = load_config()
    client = TeleClient(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
    )

    await client.connect()

    try:
        messages = await client.get_messages(TEST_CHAT, limit=3)
        print(f"[PASS] Fetched {len(messages)} messages")
        for msg in messages[:2]:
            output = format_message(msg)
            print(f"  - {output[:80]}...")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False
    finally:
        await client.disconnect()


async def test_search_messages():
    """Test searching messages."""
    from tele.client import TeleClient
    from tele.config import load_config

    print(f"\n[TEST] Searching messages in '{TEST_CHAT}'...")

    config = load_config()
    client = TeleClient(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
    )

    await client.connect()

    try:
        # Search for common words
        messages = await client.search_messages(TEST_CHAT, "the", limit=3)
        print(f"[PASS] Search returned {len(messages)} messages")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False
    finally:
        await client.disconnect()


async def test_filter_integration():
    """Test filter with real messages."""
    from tele.client import TeleClient
    from tele.config import load_config
    from tele.filter import create_filter
    from tele.output import format_message

    print(f"\n[TEST] Filter integration on '{TEST_CHAT}'...")

    config = load_config()
    client = TeleClient(
        api_id=config.telegram.api_id,
        api_hash=config.telegram.api_hash,
    )

    await client.connect()

    try:
        messages = await client.get_messages(TEST_CHAT, limit=20)

        # Test various filters
        filters = [
            'sender_id > 0',
            'has_media || is_forwarded',
        ]

        for filt_expr in filters:
            filt = create_filter(filt_expr)
            matched = sum(1 for m in messages if filt.matches(m))
            print(f"  Filter '{filt_expr}': {matched}/{len(messages)} matched")

        print("[PASS] Filter integration works")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False
    finally:
        await client.disconnect()


async def test_state_incremental():
    """Test incremental processing."""
    from tele.client import TeleClient
    from tele.config import load_config
    from tele.state import StateManager
    import tempfile

    print(f"\n[TEST] Incremental processing on '{TEST_CHAT}'...")

    with tempfile.TemporaryDirectory() as tmpdir:
        config = load_config()
        client = TeleClient(
            api_id=config.telegram.api_id,
            api_hash=config.telegram.api_hash,
        )
        state_mgr = StateManager(tmpdir)

        await client.connect()

        try:
            chat_id = await client.get_chat_id(TEST_CHAT)

            # First fetch
            state = state_mgr.load(chat_id)
            print(f"  Initial state: last_id={state.last_message_id}")

            messages = []
            async for msg in client.iter_messages(TEST_CHAT, min_id=state.last_message_id, limit=5, reverse=True):
                messages.append(msg)

            if messages:
                last_id = max(m.id for m in messages)
                state_mgr.update(chat_id, last_id)
                print(f"  Processed {len(messages)} messages, last_id={last_id}")

                # Second fetch should get 0 (no new messages)
                state = state_mgr.load(chat_id)
                new_messages = []
                async for msg in client.iter_messages(TEST_CHAT, min_id=state.last_message_id, limit=5, reverse=True):
                    new_messages.append(msg)
                print(f"  Second fetch: {len(new_messages)} new messages")

            print("[PASS] Incremental processing works")
            return True
        except Exception as e:
            print(f"[FAIL] {e}")
            return False
        finally:
            await client.disconnect()


async def run_all_tests():
    """Run all integration tests."""
    print("=" * 50)
    print("TELEGRAM INTEGRATION TESTS")
    print("=" * 50)

    tests = [
        test_connection,
        test_resolve_chat,
        test_get_messages,
        test_search_messages,
        test_filter_integration,
        test_state_incremental,
    ]

    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"[ERROR] {e}")
            results.append(False)

    print("\n" + "=" * 50)
    passed = sum(results)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    print("=" * 50)

    return all(results)


if __name__ == "__main__":
    asyncio.run(run_all_tests())