"""
Email delivery module for Paper Watcher.

Supports AWS SES (preferred) and SMTP fallback.
"""

import logging
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:  # pragma: no cover - exercised via tests
    boto3 = None  # type: ignore[assignment]
    ClientError = NoCredentialsError = Exception  # type: ignore[assignment]

# Optional toggle that tests (and callers) can override.
BOTO3_AVAILABLE: bool | None = None

from src.crawler.interface import ResultItem

logger = logging.getLogger(__name__)


class EmailStats:
    """Statistics for email generation."""

    def __init__(self):
        """Initialize stats."""
        self.total_attempted = 0
        self.total_found = 0
        self.total_new = 0
        self.total_duplicates = 0
        self.sources_success = 0
        self.sources_failed = 0
        self.sources_skipped = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "total_attempted": self.total_attempted,
            "total_found": self.total_found,
            "total_new": self.total_new,
            "total_duplicates": self.total_duplicates,
            "sources_success": self.sources_success,
            "sources_failed": self.sources_failed,
            "sources_skipped": self.sources_skipped,
        }


def generate_html_email(
    results: list[ResultItem],
    keywords: list[str],
    stats: EmailStats | None = None
) -> str:
    """
    Generate HTML email body from results.

    Args:
        results: List of ResultItem objects to include
        keywords: Keywords that were searched
        stats: Optional statistics object

    Returns:
        HTML string for email body
    """
    if stats is None:
        stats = EmailStats()
        stats.total_found = len(results)
        stats.total_new = len(results)

    # Build results table
    results_html = ""
    for i, item in enumerate(results, 1):
        published_str = ""
        if item.published_at:
            published_str = f"<br><small>Published: {item.published_at.strftime('%Y-%m-%d %H:%M UTC')}</small>"

        results_html += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #e0e0e0; text-align: center;">{i}</td>
            <td style="padding: 12px; border-bottom: 1px solid #e0e0e0;">
                <strong><a href="{item.url}" style="color: #1a73e8; text-decoration: none;">{item.title}</a></strong>
                <br>
                <span style="color: #5f6368; font-size: 14px;">{item.snippet[:300]}...</span>
                {published_str}
            </td>
        </tr>
        """

    # Build stats summary
    stats_html = f"""
    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <h3 style="color: #202124; margin-top: 0;">Execution Summary</h3>
        <table style="width: 100%; font-size: 14px;">
            <tr>
                <td style="padding: 5px;"><strong>Total Results Found:</strong></td>
                <td style="padding: 5px;">{stats.total_found}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>New Results:</strong></td>
                <td style="padding: 5px; color: #1e8e3e;"><strong>{stats.total_new}</strong></td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Duplicates Filtered:</strong></td>
                <td style="padding: 5px;">{stats.total_duplicates}</td>
            </tr>
        </table>
    </div>
    """

    # Complete HTML template
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #202124; margin: 0; padding: 0;">
    <div style="max-width: 800px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 10px 10px 0 0; text-align: center;">
            <h1 style="margin: 0; font-size: 28px;">📚 Paper Watcher Alert</h1>
            <p style="margin: 10px 0 0 0; font-size: 16px; opacity: 0.9;">New research papers matching your keywords</p>
        </div>

        <div style="background-color: white; padding: 30px; border: 1px solid #e0e0e0; border-top: none;">
            <div style="margin-bottom: 20px;">
                <p style="font-size: 14px; color: #5f6368; margin: 5px 0;">
                    <strong>Keywords:</strong> {', '.join(keywords)}
                </p>
                <p style="font-size: 14px; color: #5f6368; margin: 5px 0;">
                    <strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
                </p>
            </div>

            {stats_html}

            <h2 style="color: #202124; border-bottom: 2px solid #667eea; padding-bottom: 10px;">
                New Results ({len(results)})
            </h2>

            <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
                <thead>
                    <tr style="background-color: #f8f9fa;">
                        <th style="padding: 12px; text-align: center; border-bottom: 2px solid #e0e0e0; width: 50px;">#</th>
                        <th style="padding: 12px; text-align: left; border-bottom: 2px solid #e0e0e0;">Article</th>
                    </tr>
                </thead>
                <tbody>
                    {results_html}
                </tbody>
            </table>

            <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #e0e0e0; text-align: center; color: #5f6368; font-size: 12px;">
                <p>Generated by Paper Watcher • <a href="https://github.com/jijae92/demoSES" style="color: #1a73e8;">GitHub</a></p>
            </div>
        </div>
    </div>
</body>
</html>
    """

    return html.strip()


def generate_subject(
    subject_prefix: str,
    keywords: list[str],
    count: int
) -> str:
    """
    Generate email subject line.

    Args:
        subject_prefix: Prefix from config (e.g., "[Daily Keyword Alerts]")
        keywords: List of keywords searched
        count: Number of results

    Returns:
        Formatted subject string

    Example:
        "[Daily Keyword Alerts] 2025-10-27 (parp, isg) - 5 new results"
    """
    date_str = datetime.now().strftime('%Y-%m-%d')
    keywords_str = ', '.join(keywords[:3])  # Limit to first 3 keywords

    if len(keywords) > 3:
        keywords_str += f" +{len(keywords) - 3} more"

    subject = f"{subject_prefix} {date_str} ({keywords_str}) - {count} new results"

    return subject


class Emailer:
    """
    Email delivery manager with SES and SMTP support.
    """

    def __init__(
        self,
        sender: str,
        recipients: list[str],
        subject_prefix: str = "[Paper Watcher]",
        aws_region: str | None = None,
        smtp_host: str | None = None,
        smtp_port: int | str | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        use_tls: bool = True,
    ):
        """
        Initialize emailer.

        Args:
            sender: From email address
            recipients: List of recipient email addresses
            subject_prefix: Email subject prefix
            aws_region: AWS region for SES (auto-detected if None)
            smtp_host: SMTP server hostname (fallback)
            smtp_port: SMTP server port
            smtp_user: SMTP username
            smtp_password: SMTP password
            use_tls: Use TLS for SMTP
        """
        self.sender = sender
        self.recipients = recipients
        self.subject_prefix = subject_prefix

        # AWS SES configuration
        self.aws_region = aws_region or os.getenv("AWS_REGION", "us-east-1")

        # SMTP configuration
        self.smtp_host = smtp_host or os.getenv("SMTP_HOST")

        def _resolve_smtp_port(value: int | str | None) -> int:
            """Derive SMTP port with sensible defaults."""
            if value is None:
                return 587
            if isinstance(value, int):
                return value
            candidate = value.strip()
            if not candidate:
                return 587
            try:
                return int(candidate)
            except ValueError as exc:
                raise ValueError(f"Invalid SMTP port value: {value!r}") from exc

        env_smtp_port: str | None = os.getenv("SMTP_PORT")
        resolved_port_source: int | str | None = smtp_port if smtp_port is not None else env_smtp_port
        self.smtp_port = _resolve_smtp_port(resolved_port_source)
        self.smtp_user = smtp_user or os.getenv("SMTP_USER")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD")
        self.use_tls = use_tls

        logger.info(f"Emailer initialized: {sender} -> {len(recipients)} recipients")

    def send_email(
        self,
        results: list[ResultItem],
        keywords: list[str],
        stats: EmailStats | None = None,
        min_results: int = 1,
    ) -> bool:
        """
        Send email with results.

        Args:
            results: List of ResultItem objects
            keywords: Keywords that were searched
            stats: Optional execution statistics
            min_results: Minimum number of results required to send

        Returns:
            True if email was sent successfully, False otherwise
        """
        # Check minimum results threshold
        if len(results) < min_results:
            logger.info(
                f"Skipping email: {len(results)} results < min_results ({min_results})"
            )
            return False

        # Generate email content
        subject = generate_subject(self.subject_prefix, keywords, len(results))
        html_body = generate_html_email(results, keywords, stats)

        logger.info(f"Sending email: {subject}")

        # Try SES first, then SMTP
        if self._ses_enabled():
            try:
                return self._send_via_ses(subject, html_body)
            except Exception as e:
                logger.warning(f"SES delivery failed: {e}, trying SMTP fallback")

        # Fallback to SMTP
        if self.smtp_host:
            try:
                return self._send_via_smtp(subject, html_body)
            except Exception as e:
                logger.error(f"SMTP delivery failed: {e}")
                return False
        else:
            logger.error("No email delivery method available (SES failed, SMTP not configured)")
            return False

    def _send_via_ses(self, subject: str, html_body: str) -> bool:
        """
        Send email via AWS SES.

        Args:
            subject: Email subject
            html_body: HTML body content

        Returns:
            True if successful

        Raises:
            Exception: If SES delivery fails
        """
        if not self._ses_enabled():
            raise ImportError("boto3 is not installed")

        logger.debug(f"Sending via SES (region: {self.aws_region})")

        ses_client = boto3.client('ses', region_name=self.aws_region)

        try:
            response = ses_client.send_email(
                Source=self.sender,
                Destination={
                    'ToAddresses': self.recipients,
                },
                Message={
                    'Subject': {
                        'Data': subject,
                        'Charset': 'UTF-8'
                    },
                    'Body': {
                        'Html': {
                            'Data': html_body,
                            'Charset': 'UTF-8'
                        }
                    }
                }
            )

            message_id = response.get('MessageId', 'unknown')
            logger.info(f"✓ Email sent via SES (MessageId: {message_id})")
            return True

        except NoCredentialsError:
            logger.error("AWS credentials not found")
            raise
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"SES error ({error_code}): {error_message}")
            raise
        except Exception as e:
            logger.error(f"SES delivery failed: {e}")
            raise

    def _send_via_smtp(self, subject: str, html_body: str) -> bool:
        """
        Send email via SMTP.

        Args:
            subject: Email subject
            html_body: HTML body content

        Returns:
            True if successful

        Raises:
            Exception: If SMTP delivery fails
        """
        if not self.smtp_host:
            raise ValueError("SMTP host not configured")

        logger.debug(f"Sending via SMTP ({self.smtp_host}:{self.smtp_port})")

        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.sender
        msg['To'] = ', '.join(self.recipients)

        # Attach HTML body
        html_part = MIMEText(html_body, 'html', 'utf-8')
        msg.attach(html_part)

        # Connect and send
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
                if self.use_tls:
                    server.starttls()

                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)

                server.send_message(msg)

            logger.info(f"✓ Email sent via SMTP ({self.smtp_host})")
            return True

        except smtplib.SMTPException as e:
            logger.error(f"SMTP error: {e}")
            raise
        except Exception as e:
            logger.error(f"SMTP delivery failed: {e}")
            raise

    @staticmethod
    def _ses_enabled() -> bool:
        """
        Determine whether SES sending is enabled and boto3 is present.

        Returns:
            True when boto3 is available and the feature toggle allows usage.
        """
        if boto3 is None:
            return False
        if isinstance(BOTO3_AVAILABLE, bool):
            return BOTO3_AVAILABLE
        return True
