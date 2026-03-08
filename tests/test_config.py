"""Tests for configuration management."""

import os
import tempfile
from pathlib import Path

import pytest

from tele.config import Config, ConfigManager, TelegramConfig, DefaultsConfig, load_config


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