"""Email delivery helpers supporting SES API and SMTP fallback."""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from typing import Dict, Mapping, Sequence, TYPE_CHECKING

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import AppConfig
from util import PaperItem, sanitize_header, summarize_authors

if TYPE_CHECKING:  # pragma: no cover
    from runtime import RuntimeOptions

LOGGER = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    """Raised when email delivery fails."""


def _render_body(
    items_by_source: Mapping[str, Sequence[PaperItem]],
    summary: Mapping[str, object],
    window_start: datetime,
    window_end: datetime,
) -> str:
    total = sum(len(items) for items in items_by_source.values())
    lines = [
        f"검색 기간: {window_start.isoformat()} ~ {window_end.isoformat()}",
        f"검색 소스: {', '.join(summary.get('sources', []))}",
        f"매치 모드: {summary.get('match_mode')} | 키워드 {len(summary.get('keywords', []))}개",
        "키워드 매칭 기준: title/abstract contains",
        "",
    ]
    if total:
        lines.append(f"총 {total}건의 신규 논문을 발견했습니다.")
    else:
        lines.append("조건에 일치하는 신규 논문이 없었습니다. 아래는 요약 정보입니다.")
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
    lines.append("")
    filter_stats = summary.get("filter_stats", {})
    lines.append("[처리 요약]")
    fetch_counts_line = ", ".join(
        f"{src}={cnt}" for src, cnt in summary.get("fetch_counts", {}).items()
    )
    lines.append(f"- Fetch counts: {fetch_counts_line}" if fetch_counts_line else "- Fetch counts: 없음")
    filtered_counts_line = ", ".join(
        f"{src}={cnt}" for src, cnt in summary.get("filtered_counts", {}).items()
    )
    lines.append(
        f"- Filtered counts: {filtered_counts_line}"
        if filtered_counts_line
        else "- Filtered counts: 없음"
    )
    new_counts_line = ", ".join(
        f"{src}={cnt}" for src, cnt in summary.get("new_counts", {}).items()
    )
    lines.append(
        f"- New counts: {new_counts_line}" if new_counts_line else "- New counts: 없음"
    )
    lines.append(
        "- Filter stats: post_fetch={post_fetch} post_keyword={post_keyword} post_dedup={post_dedup} post_seen={post_seen}".format(
            post_fetch=filter_stats.get("post_fetch", filter_stats.get("total", 0)),
            post_keyword=filter_stats.get("post_keyword", filter_stats.get("matched", 0)),
            post_dedup=filter_stats.get("post_dedup", filter_stats.get("unique", 0)),
            post_seen=filter_stats.get("post_seen", 0),
        )
    )
    return "\n".join(lines)


def _build_message(
    config: AppConfig,
    subject: str,
    body: str,
    recipients: Sequence[str],
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = sanitize_header(subject)
    message["From"] = sanitize_header(config.ses_secrets.sender)
    message["To"] = ", ".join(sanitize_header(recipient) for recipient in recipients)
    if config.ses_secrets.reply_to:
        message["Reply-To"] = ", ".join(
            sanitize_header(address) for address in config.ses_secrets.reply_to
        )
    message.set_content(body)
    return message


def _resolve_recipients(config: AppConfig, runtime: "RuntimeOptions") -> Sequence[str]:
    if runtime.recipients_override:
        return runtime.recipients_override
    return config.ses_secrets.recipients


def send_email(
    items_by_source: Mapping[str, Sequence[PaperItem]],
    config: AppConfig,
    runtime: "RuntimeOptions",
    window_start: datetime,
    window_end: datetime,
    summary: Mapping[str, object],
) -> None:
    """Send an aggregated email via SES API or SMTP fallback."""
    recipients = _resolve_recipients(config, runtime)
    if not recipients:
        LOGGER.warning("No recipients configured; skipping email dispatch")
        return

    total_items = sum(len(items) for items in items_by_source.values())
    if total_items == 0 and not runtime.force_send_summary:
        LOGGER.info("No items to send and force summary disabled; skipping email")
        return

    prefix = config.ses_secrets.subject_prefix or "[PaperWatcher]"
    subject = (
        f"{prefix} {total_items} matches (sources={','.join(summary.get('sources', []))}, "
        f"window={summary.get('window_hours')}h)"
    )
    body = _render_body(items_by_source, summary, window_start, window_end)

    if config.use_smtp:
        _send_via_smtp(config, subject, body, recipients)
    else:
        _send_via_ses_api(config, subject, body, recipients)


def _send_via_ses_api(config: AppConfig, subject: str, body: str, recipients: Sequence[str]) -> None:
    client = boto3.client("ses", region_name=config.ses_secrets.region)
    request_kwargs: Dict[str, object] = {}
    if config.ses_secrets.reply_to:
        request_kwargs["ReplyToAddresses"] = list(config.ses_secrets.reply_to)
    try:
        client.send_email(
            Source=config.ses_secrets.sender,
            Destination={"ToAddresses": list(recipients)},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
            **request_kwargs,
        )
        LOGGER.info("SES API email sent to %s", ", ".join(recipients))
    except (ClientError, BotoCoreError) as exc:
        LOGGER.exception("SES API send_email failed")
        raise EmailDeliveryError(str(exc))


def _send_via_smtp(
    config: AppConfig,
    subject: str,
    body: str,
    recipients: Sequence[str],
) -> None:
    secrets = config.ses_secrets
    if not secrets.smtp_user or not secrets.smtp_pass or not secrets.host:
        raise EmailDeliveryError("SMTP credentials are incomplete")
    port = secrets.port or 587
    message = _build_message(config, subject, body, recipients)
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(secrets.host, port, timeout=20) as server:
            server.starttls(context=context)
            server.login(secrets.smtp_user, secrets.smtp_pass)
            server.send_message(message)
            LOGGER.info("SMTP email sent to %s", ", ".join(recipients))
    except smtplib.SMTPException as exc:
        LOGGER.exception("SMTP send failed")
        raise EmailDeliveryError(str(exc))
