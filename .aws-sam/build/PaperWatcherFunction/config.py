"""Configuration loading for the paper watcher Lambda."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Sequence

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from util import parse_keywords

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ApiSecrets:
    """Secrets that influence external API access."""

    pubmed_api_key: str | None
    user_agent_email: str | None


@dataclass(slots=True)
class SesSecrets:
    """Secrets that control outbound email delivery."""

    sender: str
    recipients: Sequence[str]
    region: str
    reply_to: Sequence[str] = ()
    subject_prefix: str | None = None
    smtp_user: str | None = None
    smtp_pass: str | None = None
    host: str | None = None
    port: int | None = None


@dataclass(slots=True)
class AppConfig:
    """Concrete Lambda configuration derived from environment variables and secrets."""

    keywords: Sequence[str]
    match_mode: str
    window_hours: int
    sources: Sequence[str]
    app_name: str
    ddb_table: str
    ses_secret_name: str
    api_secret_name: str
    use_smtp: bool

    api_secrets: ApiSecrets
    ses_secrets: SesSecrets

    @property
    def user_agent(self) -> str:
        """Return the composed User-Agent string for outbound requests."""
        base = self.app_name
        if self.api_secrets.user_agent_email:
            return f"{base} (mailto:{self.api_secrets.user_agent_email})"
        return base


class ConfigLoader:
    """Loader that resolves environment variables and secrets once per invocation."""

    def __init__(self) -> None:
        self._secrets_client = boto3.client("secretsmanager")

    def load(self) -> AppConfig:
        keywords = parse_keywords(os.environ.get("KEYWORDS", ""))
        match_mode = os.environ.get("MATCH_MODE", "OR").upper()
        if match_mode not in {"AND", "OR"}:
            raise ValueError("MATCH_MODE must be 'AND' or 'OR'")
        try:
            window_hours = int(os.environ.get("WINDOW_HOURS", "24"))
        except ValueError as exc:
            raise ValueError("WINDOW_HOURS must be an integer") from exc
        if window_hours <= 0:
            raise ValueError("WINDOW_HOURS must be positive")
        sources_raw = os.environ.get("SOURCES", "crossref,pubmed,rss")
        sources = [part.strip().lower() for part in sources_raw.split(",") if part.strip()]
        if not sources:
            raise ValueError("At least one source must be configured")
        app_name = os.environ.get("APP_NAME", "paper-watcher")
        ddb_table = os.environ.get("DDB_TABLE")
        if not ddb_table:
            raise ValueError("DDB_TABLE environment variable is required")
        ses_secret_name = os.environ.get("SES_SECRET_NAME")
        api_secret_name = os.environ.get("API_SECRET_NAME")
        if not ses_secret_name or not api_secret_name:
            raise ValueError("SES_SECRET_NAME and API_SECRET_NAME environment variables are required")
        use_smtp = os.environ.get("USE_SMTP", "false").lower() == "true"

        ses_secrets = self._load_ses_secret(ses_secret_name)
        api_secrets = self._load_api_secret(api_secret_name)

        if use_smtp and (not ses_secrets.smtp_user or not ses_secrets.smtp_pass or not ses_secrets.host):
            raise ValueError("SMTP secrets must include smtp_user, smtp_pass, and host when USE_SMTP=true")

        return AppConfig(
            keywords=keywords,
            match_mode=match_mode,
            window_hours=window_hours,
            sources=sources,
            app_name=app_name,
            ddb_table=ddb_table,
            ses_secret_name=ses_secret_name,
            api_secret_name=api_secret_name,
            use_smtp=use_smtp,
            api_secrets=api_secrets,
            ses_secrets=ses_secrets,
        )

    def _load_secret(self, secret_name: str) -> Dict[str, Any]:
        try:
            response = self._secrets_client.get_secret_value(SecretId=secret_name)
        except (ClientError, BotoCoreError) as exc:
            LOGGER.error("Failed to load secret %s: %s", secret_name, exc)
            raise
        secret_string = response.get("SecretString")
        if not secret_string:
            raise ValueError(f"Secret {secret_name} did not contain SecretString")
        try:
            data = json.loads(secret_string)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Secret {secret_name} is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Secret {secret_name} must be a JSON object")
        return data

    def _load_ses_secret(self, secret_name: str) -> SesSecrets:
        payload = self._load_secret(secret_name)
        sender = payload.get("sender")
        recipients = payload.get("recipients")
        region = payload.get("region")
        if not sender or not isinstance(sender, str):
            raise ValueError("SES secret must include 'sender' string")
        if not isinstance(recipients, list) or not all(isinstance(item, str) for item in recipients):
            raise ValueError("SES secret must include 'recipients' list of strings")
        if not region or not isinstance(region, str):
            raise ValueError("SES secret must include 'region' string")
        reply_to_raw = payload.get("reply_to")
        if reply_to_raw is None:
            reply_to: Sequence[str] = ()
        elif isinstance(reply_to_raw, list) and all(isinstance(item, str) for item in reply_to_raw):
            reply_to = tuple(reply_to_raw)
        else:
            raise ValueError("SES secret 'reply_to' must be a list of strings if provided")
        subject_prefix = payload.get("subject_prefix")
        if subject_prefix is not None and not isinstance(subject_prefix, str):
            raise ValueError("SES secret 'subject_prefix' must be a string if provided")
        smtp_user = payload.get("smtp_user")
        smtp_pass = payload.get("smtp_pass")
        host = payload.get("host")
        port_value = payload.get("port")
        port = int(port_value) if isinstance(port_value, int) or (isinstance(port_value, str) and port_value.isdigit()) else None
        return SesSecrets(
            sender=sender,
            recipients=tuple(recipients),
            region=region,
            reply_to=reply_to,
            subject_prefix=subject_prefix,
            smtp_user=smtp_user,
            smtp_pass=smtp_pass,
            host=host,
            port=port,
        )

    def _load_api_secret(self, secret_name: str) -> ApiSecrets:
        payload = self._load_secret(secret_name)
        pubmed_api_key = payload.get("pubmed_api_key")
        user_agent_email = payload.get("user_agent_email")
        return ApiSecrets(
            pubmed_api_key=pubmed_api_key if isinstance(pubmed_api_key, str) and pubmed_api_key else None,
            user_agent_email=user_agent_email if isinstance(user_agent_email, str) and user_agent_email else None,
        )


_loader: ConfigLoader | None = None


def get_config() -> AppConfig:
    """Return the singleton application configuration."""
    global _loader
    if _loader is None:
        _loader = ConfigLoader()
    return _loader.load()
