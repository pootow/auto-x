"""Configuration management."""

import os
from pathlib import Path
from typing import Optional, Any, Dict, List
from dataclasses import dataclass, field

import yaml


def _normalize_api_endpoint(endpoint: str) -> str:
    """Normalize bot API endpoint.

    Strips protocol prefix and trailing slashes.

    Args:
        endpoint: Raw endpoint string (e.g., "https://api.telegram.org/")

    Returns:
        Normalized endpoint (e.g., "api.telegram.org")
    """
    # Strip protocol prefix if present
    if "://" in endpoint:
        endpoint = endpoint.split("://", 1)[1]
    # Strip trailing slashes
    endpoint = endpoint.rstrip("/")
    return endpoint


@dataclass
class TelegramConfig:
    """Telegram API configuration."""
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    bot_token: Optional[str] = None
    bot_api_endpoint: str = "api.telegram.org"
    session_name: str = "tele_tool"
    endpoint_routing: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class DefaultsConfig:
    """Default values for CLI options."""
    chat: Optional[str] = None
    reaction: str = "✅"
    batch_size: int = 100


@dataclass
class Config:
    """Application configuration."""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Create Config from dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            Config instance
        """
        telegram_data = data.get('telegram', {})
        defaults_data = data.get('defaults', {})

        # Parse endpoint_routing with normalization
        endpoint_routing_raw = telegram_data.get('endpoint_routing', {})
        endpoint_routing = {}
        for endpoint, routing_data in endpoint_routing_raw.items():
            normalized_endpoint = _normalize_api_endpoint(endpoint)
            methods = routing_data.get('methods', [])
            endpoint_routing[normalized_endpoint] = methods

        telegram = TelegramConfig(
            api_id=telegram_data.get('api_id'),
            api_hash=telegram_data.get('api_hash'),
            bot_token=telegram_data.get('bot_token'),
            bot_api_endpoint=_normalize_api_endpoint(
                telegram_data.get('bot_api_endpoint', 'api.telegram.org')
            ),
            session_name=telegram_data.get('session_name', 'tele_tool'),
            endpoint_routing=endpoint_routing,
        )

        defaults = DefaultsConfig(
            chat=defaults_data.get('chat'),
            reaction=defaults_data.get('reaction', '✅'),
            batch_size=defaults_data.get('batch_size', 100),
        )

        return cls(telegram=telegram, defaults=defaults)

    def to_dict(self) -> dict:
        """Convert Config to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            'telegram': {
                'api_id': self.telegram.api_id,
                'api_hash': self.telegram.api_hash,
                'bot_token': self.telegram.bot_token,
                'bot_api_endpoint': self.telegram.bot_api_endpoint,
                'session_name': self.telegram.session_name,
                'endpoint_routing': {
                    endpoint: {'methods': methods}
                    for endpoint, methods in self.telegram.endpoint_routing.items()
                },
            },
            'defaults': {
                'chat': self.defaults.chat,
                'reaction': self.defaults.reaction,
                'batch_size': self.defaults.batch_size,
            },
        }


class ConfigManager:
    """Manages configuration loading and saving."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize config manager.

        Args:
            config_path: Path to config file (defaults to ~/.tele/config.yaml)
        """
        if config_path is None:
            config_path = os.path.expanduser("~/.tele/config.yaml")
        self.config_path = Path(config_path)

    def load(self) -> Config:
        """Load configuration from file and environment.

        Configuration priority (highest to lowest):
        1. Environment variables
        2. Config file
        3. Defaults

        Returns:
            Config instance
        """
        # Start with defaults
        config = Config()

        # Load from file if exists
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                config = Config.from_dict(data)
            except yaml.YAMLError:
                pass  # Use defaults

        # Override with environment variables
        api_id = os.environ.get('TELEGRAM_API_ID')
        if api_id:
            try:
                config.telegram.api_id = int(api_id)
            except ValueError:
                pass

        api_hash = os.environ.get('TELEGRAM_API_HASH')
        if api_hash:
            config.telegram.api_hash = api_hash

        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if bot_token:
            config.telegram.bot_token = bot_token

        return config

    def save(self, config: Config) -> None:
        """Save configuration to file.

        Args:
            config: Config instance to save
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(config.to_dict(), f, default_flow_style=False)

    def create_template(self) -> None:
        """Create a template config file."""
        template = Config()
        template.telegram.api_id = 12345
        template.telegram.api_hash = "your_api_hash_here"
        self.save(template)


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file and environment.

    Args:
        config_path: Optional path to config file

    Returns:
        Config instance
    """
    manager = ConfigManager(config_path)
    return manager.load()