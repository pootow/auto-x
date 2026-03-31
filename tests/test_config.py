"""Tests for configuration management."""

import os
import tempfile
from pathlib import Path

import pytest

from tele.config import Config, ConfigManager, TelegramConfig, DefaultsConfig, load_config, _normalize_api_endpoint, SourceConfig, IngestConfig


class TestConfig:
    """Test cases for Config dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = Config()
        assert config.telegram.api_id is None
        assert config.telegram.api_hash is None
        assert config.telegram.session_name == "tele_tool"
        assert config.defaults.chat is None
        assert config.defaults.reaction == "✅"
        assert config.defaults.batch_size == 100

    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "telegram": {
                "api_id": 12345,
                "api_hash": "test_hash",
                "session_name": "custom_session",
            },
            "defaults": {
                "chat": "test_chat",
                "reaction": "👍",
                "batch_size": 200,
            },
        }
        config = Config.from_dict(data)
        assert config.telegram.api_id == 12345
        assert config.telegram.api_hash == "test_hash"
        assert config.telegram.session_name == "custom_session"
        assert config.defaults.chat == "test_chat"
        assert config.defaults.reaction == "👍"
        assert config.defaults.batch_size == 200

    def test_to_dict(self):
        """Test converting config to dictionary."""
        config = Config(
            telegram=TelegramConfig(api_id=12345, api_hash="test_hash"),
            defaults=DefaultsConfig(chat="test_chat", reaction="👍", batch_size=200),
        )
        data = config.to_dict()
        assert data["telegram"]["api_id"] == 12345
        assert data["telegram"]["api_hash"] == "test_hash"
        assert data["defaults"]["chat"] == "test_chat"
        assert data["defaults"]["reaction"] == "👍"
        assert data["defaults"]["batch_size"] == 200

    def test_from_dict_with_endpoint_routing(self):
        """Test creating config with endpoint_routing."""
        data = {
            "telegram": {
                "api_id": 12345,
                "api_hash": "test_hash",
                "endpoint_routing": {
                    "local.server:8081": {
                        "methods": ["sendVideo", "sendPhoto"]
                    },
                    "api.telegram.org": {
                        "methods": ["getUpdates"]
                    }
                }
            },
        }
        config = Config.from_dict(data)
        assert config.telegram.endpoint_routing == {
            "local.server:8081": ["sendVideo", "sendPhoto"],
            "api.telegram.org": ["getUpdates"]
        }

    def test_to_dict_with_endpoint_routing(self):
        """Test serializing config with endpoint_routing."""
        config = Config(
            telegram=TelegramConfig(
                api_id=12345,
                api_hash="test_hash",
                endpoint_routing={
                    "local.server:8081": ["sendVideo", "sendPhoto"]
                }
            ),
        )
        data = config.to_dict()
        assert data["telegram"]["endpoint_routing"] == {
            "local.server:8081": {"methods": ["sendVideo", "sendPhoto"]}
        }

    def test_endpoint_routing_normalization(self):
        """Test endpoint URLs are normalized in routing."""
        data = {
            "telegram": {
                "endpoint_routing": {
                    "https://local.server:8081/": {
                        "methods": ["sendVideo"]
                    }
                }
            }
        }
        config = Config.from_dict(data)
        assert "local.server:8081" in config.telegram.endpoint_routing
        assert "https://local.server:8081/" not in config.telegram.endpoint_routing


class TestConfigManager:
    """Test cases for ConfigManager."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create a temporary directory for config files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    def test_load_missing_config(self, temp_config_dir):
        """Test loading when config file doesn't exist."""
        config_path = os.path.join(temp_config_dir, "config.yaml")
        manager = ConfigManager(config_path)
        config = manager.load()
        # Should return defaults
        assert config.telegram.api_id is None
        assert config.telegram.api_hash is None

    def test_save_and_load_config(self, temp_config_dir):
        """Test saving and loading config."""
        config_path = os.path.join(temp_config_dir, "config.yaml")
        manager = ConfigManager(config_path)

        config = Config(
            telegram=TelegramConfig(api_id=12345, api_hash="test_hash"),
            defaults=DefaultsConfig(chat="test_chat"),
        )
        manager.save(config)

        loaded = manager.load()
        assert loaded.telegram.api_id == 12345
        assert loaded.telegram.api_hash == "test_hash"
        assert loaded.defaults.chat == "test_chat"

    def test_env_override(self, temp_config_dir, monkeypatch):
        """Test environment variable override."""
        monkeypatch.setenv("TELEGRAM_API_ID", "99999")
        monkeypatch.setenv("TELEGRAM_API_HASH", "env_hash")

        config_path = os.path.join(temp_config_dir, "config.yaml")
        manager = ConfigManager(config_path)
        config = manager.load()

        assert config.telegram.api_id == 99999
        assert config.telegram.api_hash == "env_hash"

    def test_create_template(self, temp_config_dir):
        """Test creating a template config file."""
        config_path = os.path.join(temp_config_dir, "config.yaml")
        manager = ConfigManager(config_path)
        manager.create_template()

        assert os.path.exists(config_path)

        loaded = manager.load()
        assert loaded.telegram.api_id == 12345
        assert loaded.telegram.api_hash == "your_api_hash_here"

    def test_env_bot_token(self, temp_config_dir, monkeypatch):
        """Test loading bot token from environment."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_bot_token_123")

        config_path = os.path.join(temp_config_dir, "config.yaml")
        manager = ConfigManager(config_path)
        config = manager.load()

        assert config.telegram.bot_token == "test_bot_token_123"

    def test_bot_api_endpoint_normalization(self, temp_config_dir):
        """Test bot_api_endpoint normalization in config file."""
        config_path = os.path.join(temp_config_dir, "config.yaml")
        manager = ConfigManager(config_path)

        # Save config with endpoint that has protocol and trailing slash
        config = Config(
            telegram=TelegramConfig(
                api_id=12345,
                api_hash="test_hash",
                bot_api_endpoint="https://custom.api.server/",
            ),
        )
        manager.save(config)

        loaded = manager.load()
        # Note: load() uses from_dict which normalizes, but save saves the normalized value
        assert loaded.telegram.bot_api_endpoint == "custom.api.server"

    def test_roundtrip_with_sources_and_ingest(self, temp_config_dir):
        """Test save and load roundtrip with sources and ingest."""
        config_path = os.path.join(temp_config_dir, "config.yaml")
        manager = ConfigManager(config_path)

        original = Config(
            telegram=TelegramConfig(api_id=12345, api_hash="test_hash"),
            defaults=DefaultsConfig(chat="test_chat"),
            sources={
                "web_monitor": SourceConfig(
                    processor="python monitor.py",
                    chat_id=12345,
                    filter='contains("urgent")'
                )
            },
            ingest=IngestConfig(poll_interval=60.0, watch_enabled=False)
        )
        manager.save(original)

        loaded = manager.load()
        assert loaded.sources["web_monitor"].processor == "python monitor.py"
        assert loaded.sources["web_monitor"].chat_id == 12345
        assert loaded.sources["web_monitor"].filter == 'contains("urgent")'
        assert loaded.ingest.poll_interval == 60.0
        assert loaded.ingest.watch_enabled is False


class TestNormalizeApiEndpoint:
    """Test cases for _normalize_api_endpoint function."""

    @pytest.mark.parametrize("input_value,expected", [
        ("api.telegram.org", "api.telegram.org"),
        ("https://api.telegram.org", "api.telegram.org"),
        ("http://api.telegram.org", "api.telegram.org"),
        ("api.telegram.org/", "api.telegram.org"),
        ("api.telegram.org//", "api.telegram.org"),
        ("https://api.telegram.org/", "api.telegram.org"),
        ("http://custom.server/", "custom.server"),
        ("https://custom.server", "custom.server"),
        ("custom.server/", "custom.server"),
    ])
    def test_normalize(self, input_value, expected):
        """Test various endpoint formats are normalized correctly."""
        assert _normalize_api_endpoint(input_value) == expected


class TestEndpointRoutingLookup:
    """Test cases for get_endpoint_for_method."""

    def test_default_endpoint_when_no_routing(self):
        """Test returns default when no routing configured."""
        config = TelegramConfig(
            bot_api_endpoint="api.telegram.org",
            endpoint_routing={}
        )
        result = config.get_endpoint_for_method("sendVideo")
        assert result == "api.telegram.org"

    def test_routed_method_returns_assigned_endpoint(self):
        """Test returns assigned endpoint for routed method."""
        config = TelegramConfig(
            bot_api_endpoint="api.telegram.org",
            endpoint_routing={
                "local.server:8081": ["sendVideo", "sendPhoto"]
            }
        )
        result = config.get_endpoint_for_method("sendVideo")
        assert result == "local.server:8081"

    def test_unlisted_method_returns_default(self):
        """Test returns default for method not in routing."""
        config = TelegramConfig(
            bot_api_endpoint="api.telegram.org",
            endpoint_routing={
                "local.server:8081": ["sendVideo"]
            }
        )
        result = config.get_endpoint_for_method("getUpdates")
        assert result == "api.telegram.org"

    def test_last_endpoint_wins_for_duplicate_method(self):
        """Test later routing entries override earlier ones."""
        config = TelegramConfig(
            bot_api_endpoint="api.telegram.org",
            endpoint_routing={
                "server1": ["sendVideo"],
                "server2": ["sendVideo"]
            }
        )
        result = config.get_endpoint_for_method("sendVideo")
        assert result == "server2"

    def test_method_in_multiple_lists_last_wins(self):
        """Test method appearing in multiple endpoint lists."""
        config = TelegramConfig(
            bot_api_endpoint="default.server",
            endpoint_routing={
                "endpoint_a": ["sendVideo", "getUpdates"],
                "endpoint_b": ["getUpdates", "sendMessage"]
            }
        )
        # getUpdates appears in both, last wins
        result = config.get_endpoint_for_method("getUpdates")
        assert result == "endpoint_b"
        # sendVideo only in first
        result = config.get_endpoint_for_method("sendVideo")
        assert result == "endpoint_a"


class TestSourceConfig:
    """Test cases for SourceConfig dataclass."""

    def test_source_config_required_fields(self):
        """Test SourceConfig with required fields only."""
        source = SourceConfig(processor="python monitor.py", chat_id=12345)
        assert source.processor == "python monitor.py"
        assert source.chat_id == 12345
        assert source.filter is None
        assert source.path is None

    def test_source_config_all_fields(self):
        """Test SourceConfig with all fields."""
        source = SourceConfig(
            processor="rss-processor",
            chat_id=67890,
            filter='contains("important")',
            path="/custom/data/source"
        )
        assert source.processor == "rss-processor"
        assert source.chat_id == 67890
        assert source.filter == 'contains("important")'
        assert source.path == "/custom/data/source"


class TestIngestConfig:
    """Test cases for IngestConfig dataclass."""

    def test_ingest_config_defaults(self):
        """Test IngestConfig default values."""
        ingest = IngestConfig()
        assert ingest.poll_interval == 30.0
        assert ingest.watch_enabled is True

    def test_ingest_config_custom_values(self):
        """Test IngestConfig with custom values."""
        ingest = IngestConfig(poll_interval=60.0, watch_enabled=False)
        assert ingest.poll_interval == 60.0
        assert ingest.watch_enabled is False


class TestConfigSourcesAndIngest:
    """Test cases for Config sources and ingest sections."""

    def test_default_config_has_empty_sources(self):
        """Test default Config has empty sources."""
        config = Config()
        assert config.sources == {}
        assert config.ingest.poll_interval == 30.0
        assert config.ingest.watch_enabled is True

    def test_from_dict_with_sources(self):
        """Test creating config with sources."""
        data = {
            "sources": {
                "web_monitor": {
                    "processor": "python monitor.py",
                    "chat_id": 12345
                },
                "rss_feed": {
                    "processor": "rss-processor",
                    "chat_id": 67890,
                    "filter": 'contains("important")',
                    "path": "/data/rss"
                }
            }
        }
        config = Config.from_dict(data)
        assert len(config.sources) == 2
        assert "web_monitor" in config.sources
        assert "rss_feed" in config.sources

        web_monitor = config.sources["web_monitor"]
        assert web_monitor.processor == "python monitor.py"
        assert web_monitor.chat_id == 12345
        assert web_monitor.filter is None
        assert web_monitor.path is None

        rss_feed = config.sources["rss_feed"]
        assert rss_feed.processor == "rss-processor"
        assert rss_feed.chat_id == 67890
        assert rss_feed.filter == 'contains("important")'
        assert rss_feed.path == "/data/rss"

    def test_from_dict_with_ingest(self):
        """Test creating config with ingest settings."""
        data = {
            "ingest": {
                "poll_interval": 60,
                "watch_enabled": False
            }
        }
        config = Config.from_dict(data)
        assert config.ingest.poll_interval == 60
        assert config.ingest.watch_enabled is False

    def test_to_dict_with_sources(self):
        """Test serializing config with sources."""
        config = Config(
            sources={
                "web_monitor": SourceConfig(
                    processor="python monitor.py",
                    chat_id=12345
                ),
                "rss_feed": SourceConfig(
                    processor="rss-processor",
                    chat_id=67890,
                    filter='contains("important")',
                    path="/data/rss"
                )
            }
        )
        data = config.to_dict()
        assert "sources" in data
        assert len(data["sources"]) == 2
        assert data["sources"]["web_monitor"]["processor"] == "python monitor.py"
        assert data["sources"]["web_monitor"]["chat_id"] == 12345
        assert "filter" not in data["sources"]["web_monitor"]
        assert "path" not in data["sources"]["web_monitor"]
        assert data["sources"]["rss_feed"]["filter"] == 'contains("important")'
        assert data["sources"]["rss_feed"]["path"] == "/data/rss"

    def test_to_dict_with_ingest(self):
        """Test serializing config with ingest settings."""
        config = Config(
            ingest=IngestConfig(poll_interval=45.0, watch_enabled=False)
        )
        data = config.to_dict()
        assert "ingest" in data
        assert data["ingest"]["poll_interval"] == 45.0
        assert data["ingest"]["watch_enabled"] is False