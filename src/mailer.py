"""Email delivery helpers supporting SES API and SMTP fallback."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Mapping, Sequence

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import AppConfig
from util import PaperItem, sanitize_header, summarize_authors

LOGGER = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Raised when email delivery fails."""


def _render_body(items_by_source: Mapping[str, Sequence[PaperItem]]) -> str:
    total = sum(len(items) for items in items_by_source.values())
    lines = [f"총 {total}건의 신규 논문을 발견했습니다."]
    for source, items in items_by_source.items():
        if not items:
            continue
        lines.append("")
        lines.append(f"[{source.upper()}] {len(items)}건")
        for item in items:
            lines.append(f"- {item.title}")
            lines.append(f"  저자: {summarize_authors(item.authors)}")
            if item.journal:
                lines.append(f"  저널: {item.journal}")
            if item.published:
                lines.append(f"  발행일: {item.published_iso()}")
            if item.matched_keywords:
                lines.append(f"  일치 키워드: {', '.join(item.matched_keywords)}")
            lines.append(f"  링크: {item.url}")
            if item.summary:
                lines.append(f"  요약: {item.summary}")
    return "\n".join(lines)


def _build_message(config: AppConfig, subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = sanitize_header(subject)
    message["From"] = sanitize_header(config.ses_secrets.sender)
    message["To"] = ", ".join(sanitize_header(recipient) for recipient in config.ses_secrets.recipients)
    message.set_content(body)
    return message


def send_email(items_by_source: Mapping[str, Sequence[PaperItem]], config: AppConfig) -> None:
    """Send an aggregated email via SES API or SMTP fallback."""
    if not items_by_source:
        LOGGER.info("No items to send, skipping email")
        return

    total_items = sum(len(items) for items in items_by_source.values())
    subject = f"[Paper Watcher] 신규 논문 {total_items}건 (Nature/Cell/Science)"
    body = _render_body(items_by_source)

    if config.use_smtp:
        _send_via_smtp(config, subject, body)
    else:
        _send_via_ses_api(config, subject, body)


def _send_via_ses_api(config: AppConfig, subject: str, body: str) -> None:
    client = boto3.client("ses", region_name=config.ses_secrets.region)
    try:
        client.send_email(
            Source=config.ses_secrets.sender,
            Destination={"ToAddresses": list(config.ses_secrets.recipients)},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
        LOGGER.info("SES API email sent to %s", ", ".join(config.ses_secrets.recipients))
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("SES API send_email failed")
        raise EmailDeliveryError(str(exc))


def _send_via_smtp(config: AppConfig, subject: str, body: str) -> None:
    secrets = config.ses_secrets
    if not secrets.smtp_user or not secrets.smtp_pass or not secrets.host:
        raise EmailDeliveryError("SMTP credentials are incomplete")
    port = secrets.port or 587
    message = _build_message(config, subject, body)
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(secrets.host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(secrets.smtp_user, secrets.smtp_pass)
            server.send_message(message)
            LOGGER.info("SMTP email sent to %s", ", ".join(secrets.recipients))
    except smtplib.SMTPException as exc:
        LOGGER.exception("SMTP send failed")
        raise EmailDeliveryError(str(exc))