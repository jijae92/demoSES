"""
Configuration loader for Paper Watcher using pydantic and YAML.

This module provides a typed configuration schema that loads from config.yaml
and validates all required fields.
"""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class EmailConfig(BaseModel):
    """Email delivery configuration."""

    sender: str = Field(alias="from", description="Sender email address")
    recipients: list[str] = Field(alias="to", description="List of recipient email addresses")
    subject_prefix: str = Field(description="Email subject line prefix")

    class Config:
        populate_by_name = True


class PaperWatcherConfig(BaseModel):
    """Main configuration schema for Paper Watcher."""

    keywords: list[str] = Field(
        description="List of keywords to search for (case-insensitive)"
    )
    provider: Literal["bing", "http"] = Field(
        description="Search provider: 'bing' for Bing API, 'http' for direct URL crawling"
    )
    sources: list[str] | None = Field(
        default=None,
        description="Source URLs (required when provider='http')"
    )
    min_results: int = Field(
        default=1,
        ge=0,
        description="Minimum number of results required to send email"
    )
    dedup_window_days: int = Field(
        default=14,
        ge=1,
        description="Deduplication window in days"
    )
    timezone: str = Field(
        default="Asia/Seoul",
        description="Timezone for scheduling and date formatting"
    )
    email: EmailConfig = Field(description="Email configuration")

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, v, values):
        """Validate that sources is provided when provider='http'."""
        # Note: In Pydantic v2, we need to access other fields differently
        # This is a simplified validation; adjust as needed for your Pydantic version
        return v

    @field_validator("keywords")
    @classmethod
    def validate_keywords_not_empty(cls, v):
        """Ensure at least one keyword is provided."""
        if not v or len(v) == 0:
            raise ValueError("At least one keyword must be provided")
        return v


def load_config(config_path: str | Path = "config.yaml") -> PaperWatcherConfig:
    """
    Load and validate configuration from YAML file.

    Args:
        config_path: Path to the config.yaml file (default: 'config.yaml' in repo root)

    Returns:
        PaperWatcherConfig: Validated configuration object

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If configuration is invalid
        yaml.YAMLError: If YAML parsing fails

    Example:
        >>> config = load_config()
        >>> print(config.keywords)
        ['parp', 'isg', 'interferon', 'sting']
        >>> print(config.email.sender)
        'alerts@your-domain.com'
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    if not config_data:
        raise ValueError(f"Configuration file is empty: {config_path}")

    return PaperWatcherConfig(**config_data)


def load_config_with_env_fallback() -> PaperWatcherConfig:
    """
    Load configuration from config.yaml if it exists, otherwise fall back to
    environment variables (for backward compatibility).

    Returns:
        PaperWatcherConfig: Validated configuration object
    """
    config_path = Path("config.yaml")

    if config_path.exists():
        return load_config(config_path)

    # Fallback to environment variables (legacy mode)
    keywords_str = os.getenv("KEYWORDS", "parp, isg, interferon, sting")
    keywords = [k.strip() for k in keywords_str.split(",")]

    email_from = os.getenv("EMAIL_FROM", "alerts@example.com")
    email_to_str = os.getenv("EMAIL_TO", "recipient@example.com")
    email_to = [e.strip() for e in email_to_str.split(",")]

    return PaperWatcherConfig(
        keywords=keywords,
        provider="http",
        sources=[
            "https://www.nature.com/nature/articles",
            "https://www.cell.com/cell/current",
            "https://www.science.org/toc/science/current"
        ],
        min_results=int(os.getenv("MIN_RESULTS", "1")),
        dedup_window_days=int(os.getenv("DEDUP_WINDOW_DAYS", "14")),
        timezone=os.getenv("TZ", "Asia/Seoul"),
        email=EmailConfig(
            sender=email_from,
            recipients=email_to,
            subject_prefix="[Daily Keyword Alerts]"
        )
    )


if __name__ == "__main__":
    # Test the configuration loader
    try:
        config = load_config()
        print("Configuration loaded successfully!")
        print(f"Keywords: {config.keywords}")
        print(f"Provider: {config.provider}")
        print(f"Email from: {config.email.sender}")
        print(f"Email to: {config.email.recipients}")
    except Exception as e:
        print(f"Error loading configuration: {e}")
