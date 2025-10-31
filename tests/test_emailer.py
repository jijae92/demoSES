"""
Unit tests for emailer module.

Tests HTML generation, SES delivery (mocked), and SMTP delivery (mocked).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.crawler.interface import ResultItem
from src.emailer import (
    EmailStats,
    Emailer,
    generate_html_email,
    generate_subject,
)


# ========== HTML Generation Tests ==========

def test_generate_subject_basic():
    """Test basic subject generation."""
    subject = generate_subject("[Test]", ["parp", "isg"], 5)

    assert "[Test]" in subject
    assert "parp" in subject
    assert "isg" in subject
    assert "5 new results" in subject
    assert datetime.now().strftime('%Y-%m-%d') in subject


def test_generate_subject_many_keywords():
    """Test subject with many keywords."""
    keywords = ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]
    subject = generate_subject("[Test]", keywords, 10)

    # Should show first 3 + "more"
    assert "keyword1" in subject
    assert "keyword2" in subject
    assert "keyword3" in subject
    assert "+2 more" in subject


def test_generate_html_email_basic():
    """Test basic HTML email generation."""
    results = [
        ResultItem(
            title="Test Article",
            url="https://example.com/test",
            snippet="This is a test snippet about PARP inhibitors",
            published_at=datetime.now(timezone.utc)
        )
    ]

    html = generate_html_email(results, ["parp"])

    # Check HTML structure
    assert "<!DOCTYPE html>" in html
    assert "<html>" in html
    assert "</html>" in html

    # Check content
    assert "Test Article" in html
    assert "https://example.com/test" in html
    assert "PARP inhibitors" in html
    assert "Paper Watcher Alert" in html


def test_generate_html_email_multiple_results():
    """Test HTML with multiple results."""
    results = [
        ResultItem(f"Article {i}", f"https://example.com/{i}", f"Snippet {i}")
        for i in range(5)
    ]

    html = generate_html_email(results, ["test"])

    # Check all articles present
    for i in range(5):
        assert f"Article {i}" in html
        assert f"https://example.com/{i}" in html


def test_generate_html_email_with_stats():
    """Test HTML with execution statistics."""
    results = [
        ResultItem("Article", "https://example.com", "Snippet")
    ]

    stats = EmailStats()
    stats.total_found = 10
    stats.total_new = 1
    stats.total_duplicates = 9

    html = generate_html_email(results, ["test"], stats)

    # Check stats in HTML
    assert "Execution Summary" in html
    assert "10" in html  # total found
    assert "1" in html   # new
    assert "9" in html   # duplicates


def test_generate_html_email_long_snippet():
    """Test HTML with long snippet (should truncate)."""
    long_snippet = "A" * 500

    results = [
        ResultItem("Article", "https://example.com", long_snippet)
    ]

    html = generate_html_email(results, ["test"])

    # Should be truncated to 300 chars
    assert long_snippet[:300] in html
    assert "..." in html


# ========== EmailStats Tests ==========

def test_email_stats_initialization():
    """Test EmailStats initialization."""
    stats = EmailStats()

    assert stats.total_attempted == 0
    assert stats.total_found == 0
    assert stats.total_new == 0
    assert stats.total_duplicates == 0


def test_email_stats_to_dict():
    """Test converting EmailStats to dictionary."""
    stats = EmailStats()
    stats.total_found = 10
    stats.total_new = 5

    stats_dict = stats.to_dict()

    assert stats_dict["total_found"] == 10
    assert stats_dict["total_new"] == 5
    assert "total_duplicates" in stats_dict


# ========== Emailer Tests ==========

def test_emailer_initialization():
    """Test Emailer initialization."""
    emailer = Emailer(
        sender="from@example.com",
        recipients=["to@example.com"],
        subject_prefix="[Test]"
    )

    assert emailer.sender == "from@example.com"
    assert emailer.recipients == ["to@example.com"]
    assert emailer.subject_prefix == "[Test]"


def test_emailer_min_results_skip():
    """Test that email is skipped when results < min_results."""
    emailer = Emailer(
        sender="from@example.com",
        recipients=["to@example.com"]
    )

    results = [
        ResultItem("Article", "https://example.com", "Snippet")
    ]

    # min_results = 5, but only 1 result
    sent = emailer.send_email(results, ["test"], min_results=5)

    assert sent is False


def test_emailer_min_results_send():
    """Test that email is sent when results >= min_results."""
    with patch('src.emailer.boto3') as mock_boto3:
        mock_ses = MagicMock()
        mock_ses.send_email.return_value = {"MessageId": "test123"}
        mock_boto3.client.return_value = mock_ses

        emailer = Emailer(
            sender="from@example.com",
            recipients=["to@example.com"]
        )

        results = [
            ResultItem(f"Article {i}", f"https://example.com/{i}", f"Snippet {i}")
            for i in range(3)
        ]

        # min_results = 2, and we have 3 results
        sent = emailer.send_email(results, ["test"], min_results=2)

        assert sent is True
        mock_ses.send_email.assert_called_once()


@patch('src.emailer.BOTO3_AVAILABLE', True)
@patch('src.emailer.boto3')
def test_send_via_ses_success(mock_boto3):
    """Test successful SES delivery."""
    mock_ses = MagicMock()
    mock_ses.send_email.return_value = {"MessageId": "test-message-id"}
    mock_boto3.client.return_value = mock_ses

    emailer = Emailer(
        sender="from@example.com",
        recipients=["to@example.com"],
        aws_region="us-east-1"
    )

    results = [
        ResultItem("Test Article", "https://example.com", "Test snippet")
    ]

    sent = emailer.send_email(results, ["test"])

    assert sent is True
    mock_boto3.client.assert_called_once_with('ses', region_name='us-east-1')
    mock_ses.send_email.assert_called_once()

    # Check SES API call
    call_args = mock_ses.send_email.call_args
    assert call_args[1]['Source'] == "from@example.com"
    assert call_args[1]['Destination']['ToAddresses'] == ["to@example.com"]


@patch('src.emailer.BOTO3_AVAILABLE', True)
@patch('src.emailer.boto3')
def test_send_via_ses_failure_fallback_smtp(mock_boto3):
    """Test SES failure with SMTP fallback."""
    # SES fails
    mock_boto3.client.side_effect = Exception("SES not available")

    with patch('src.emailer.smtplib.SMTP') as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        emailer = Emailer(
            sender="from@example.com",
            recipients=["to@example.com"],
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass"
        )

        results = [
            ResultItem("Test", "https://example.com", "Snippet")
        ]

        sent = emailer.send_email(results, ["test"])

        assert sent is True
        mock_smtp.assert_called_once()
        mock_server.send_message.assert_called_once()


@patch('src.emailer.BOTO3_AVAILABLE', False)
@patch('src.emailer.smtplib.SMTP')
def test_send_via_smtp_success(mock_smtp):
    """Test successful SMTP delivery."""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    emailer = Emailer(
        sender="from@example.com",
        recipients=["to@example.com"],
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="user",
        smtp_password="pass"
    )

    results = [
        ResultItem("Test", "https://example.com", "Snippet")
    ]

    sent = emailer.send_email(results, ["test"])

    assert sent is True
    mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user", "pass")
    mock_server.send_message.assert_called_once()


@patch('src.emailer.BOTO3_AVAILABLE', False)
def test_send_no_delivery_method():
    """Test failure when no delivery method is available."""
    emailer = Emailer(
        sender="from@example.com",
        recipients=["to@example.com"]
        # No smtp_host configured
    )

    results = [
        ResultItem("Test", "https://example.com", "Snippet")
    ]

    sent = emailer.send_email(results, ["test"])

    assert sent is False


@patch('src.emailer.smtplib.SMTP')
def test_send_via_smtp_no_auth(mock_smtp):
    """Test SMTP without authentication."""
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    emailer = Emailer(
        sender="from@example.com",
        recipients=["to@example.com"],
        smtp_host="smtp.example.com",
        smtp_port=25,
        use_tls=False
    )

    results = [
        ResultItem("Test", "https://example.com", "Snippet")
    ]

    sent = emailer.send_email(results, ["test"])

    assert sent is True
    mock_server.starttls.assert_not_called()
    mock_server.login.assert_not_called()
    mock_server.send_message.assert_called_once()


def test_emailer_environment_variables():
    """Test that Emailer reads from environment variables."""
    with patch.dict('os.environ', {
        'AWS_REGION': 'eu-west-1',
        'SMTP_HOST': 'smtp.test.com',
        'SMTP_PORT': '465',
        'SMTP_USER': 'testuser',
        'SMTP_PASSWORD': 'testpass'
    }):
        emailer = Emailer(
            sender="from@example.com",
            recipients=["to@example.com"]
        )

        assert emailer.aws_region == 'eu-west-1'
        assert emailer.smtp_host == 'smtp.test.com'
        assert emailer.smtp_port == 465
        assert emailer.smtp_user == 'testuser'
        assert emailer.smtp_password == 'testpass'


def test_emailer_blank_env_port_defaults_to_587():
    """Blank SMTP_PORT environment variables should fall back to default."""
    with patch.dict('os.environ', {'SMTP_PORT': ''}):
        emailer = Emailer(
            sender="from@example.com",
            recipients=["to@example.com"]
        )

        assert emailer.smtp_port == 587


# ========== Integration Tests ==========

@patch('src.emailer.boto3')
def test_full_email_workflow(mock_boto3):
    """Test complete email workflow."""
    mock_ses = MagicMock()
    mock_ses.send_email.return_value = {"MessageId": "test-msg-id"}
    mock_boto3.client.return_value = mock_ses

    # Create sample results
    results = [
        ResultItem(
            title="PARP Inhibitors in Cancer Treatment",
            url="https://example.com/parp-inhibitors",
            snippet="Study shows PARP inhibitors effective in treating cancer",
            published_at=datetime.now(timezone.utc)
        ),
        ResultItem(
            title="ISG Expression Patterns",
            url="https://example.com/isg-expression",
            snippet="Research on ISG expression in immune response"
        )
    ]

    # Create emailer
    emailer = Emailer(
        sender="alerts@example.com",
        recipients=["user1@example.com", "user2@example.com"],
        subject_prefix="[Research Alert]",
        aws_region="us-west-2"
    )

    # Create stats
    stats = EmailStats()
    stats.total_found = 10
    stats.total_new = 2
    stats.total_duplicates = 8

    # Send email
    sent = emailer.send_email(
        results=results,
        keywords=["parp", "isg"],
        stats=stats,
        min_results=1
    )

    assert sent is True

    # Verify SES call
    call_args = mock_ses.send_email.call_args[1]
    assert call_args['Source'] == "alerts@example.com"
    assert "user1@example.com" in call_args['Destination']['ToAddresses']
    assert "user2@example.com" in call_args['Destination']['ToAddresses']

    # Verify subject
    subject = call_args['Message']['Subject']['Data']
    assert "[Research Alert]" in subject
    assert "parp" in subject or "isg" in subject
    assert "2 new results" in subject

    # Verify HTML body
    html_body = call_args['Message']['Body']['Html']['Data']
    assert "PARP Inhibitors" in html_body
    assert "ISG Expression" in html_body
    assert "https://example.com/parp-inhibitors" in html_body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
