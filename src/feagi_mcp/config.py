"""Configuration management for FEAGI MCP server."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class FeagiMcpConfig(BaseSettings):
    """Configuration for FEAGI MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="FEAGI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    #: Composer public REST root (HTTPS), no trailing slash. Example:
    #: ``https://staging-api.brainsforrobots.com``. When empty,
    #: ``composer_*`` MCP tools return ``composer_base_url_not_configured``.
    composer_base_url: str = ""

    host: str = "localhost"
    port: int = 8000
    timeout_seconds: float = 30.0
    max_retries: int = 3
    connection_check_interval_seconds: float = 5.0


def load_config() -> FeagiMcpConfig:
    """Load configuration from environment variables."""
    return FeagiMcpConfig()
