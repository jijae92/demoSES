#!/usr/bin/env python3
"""
Simple email delivery test script.

Tests the emailer module with sample data to verify email configuration.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.crawler.interface import ResultItem
from src.emailer import Emailer, EmailStats


def create_test_results() -> list[ResultItem]:
    """Create sample results for testing."""
    return [
        ResultItem(
            title="Novel PARP Inhibitors Show Enhanced Efficacy in Triple-Negative Breast Cancer",
            url="https://pubmed.ncbi.nlm.nih.gov/38123456/",
            snippet="Recent advances in PARP inhibitor development have led to the discovery of compounds with improved "
                   "selectivity and reduced toxicity. This study demonstrates significant tumor regression in xenograft "
                   "models of triple-negative breast cancer, suggesting potential for clinical translation.",
            published_at=datetime.now(timezone.utc) - timedelta(days=2)
        ),
        ResultItem(
            title="Interferon-Stimulated Genes (ISGs) and Their Role in Antiviral Defense",
            url="https://pubmed.ncbi.nlm.nih.gov/38234567/",
            snippet="Interferon-stimulated genes represent a critical arm of the innate immune response. We identified "
                   "120 ISGs with previously unknown antiviral functions through a genome-wide CRISPR screen, revealing "
                   "new therapeutic targets for viral infections.",
            published_at=datetime.now(timezone.utc) - timedelta(days=5)
        ),
        ResultItem(
            title="STING Pathway Activation Enhances Cancer Immunotherapy Response",
            url="https://pubmed.ncbi.nlm.nih.gov/38345678/",
            snippet="The cGAS-STING pathway plays a pivotal role in tumor immune surveillance. Our results show that "
                   "STING agonists synergize with checkpoint inhibitors to enhance T cell infiltration and improve "
                   "treatment outcomes in melanoma patients.",
            published_at=datetime.now(timezone.utc) - timedelta(days=7)
        ),
        ResultItem(
            title="Type I Interferon Response in COVID-19: Implications for Severe Disease",
            url="https://pubmed.ncbi.nlm.nih.gov/38456789/",
            snippet="Analysis of 500 hospitalized COVID-19 patients reveals that delayed type I interferon responses "
                   "correlate with disease severity. Early interferon administration may prevent progression to "
                   "critical illness in high-risk patients.",
            published_at=datetime.now(timezone.utc) - timedelta(days=10)
        ),
        ResultItem(
            title="Combination of PARP Inhibitors and ISG15 Modulators in Ovarian Cancer",
            url="https://pubmed.ncbi.nlm.nih.gov/38567890/",
            snippet="ISG15 modulation sensitizes ovarian cancer cells to PARP inhibition through disruption of DNA "
                   "repair mechanisms. Phase II clinical trial demonstrates 65% objective response rate with the "
                   "combination therapy, compared to 42% with PARP inhibitor alone.",
            published_at=datetime.now(timezone.utc) - timedelta(days=14)
        ),
    ]


def main():
    """Run email delivery test."""
    print("=" * 70)
    print("EMAIL DELIVERY TEST")
    print("=" * 70)
    print()

    # Configuration
    sender = os.getenv("EMAIL_FROM", "jijae92@gmail.com")
    recipients = os.getenv("EMAIL_TO", "jws0408@naver.com").split(",")

    # SMTP configuration (for Gmail)
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", sender)
    smtp_password = os.getenv("SMTP_PASSWORD", "")

    # AWS configuration (optional)
    aws_region = os.getenv("AWS_REGION", "us-east-1")

    print(f"Sender: {sender}")
    print(f"Recipients: {', '.join(recipients)}")
    print(f"SMTP Host: {smtp_host}:{smtp_port}")
    print(f"AWS Region: {aws_region}")
    print()

    # Create test data
    print("Creating test results...")
    results = create_test_results()
    keywords = ["parp", "interferon", "sting", "isg"]

    stats = EmailStats()
    stats.total_found = len(results)
    stats.total_new = len(results)
    stats.total_duplicates = 0

    print(f"✓ Created {len(results)} test results with realistic data")
    print()

    # Check configuration
    import boto3
    from pathlib import Path

    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_credentials_file = Path.home() / ".aws" / "credentials"

    has_aws_env = aws_access_key and aws_secret_key
    has_aws_file = aws_credentials_file.exists()
    has_aws_credentials = has_aws_env or has_aws_file
    has_smtp_credentials = smtp_password

    if not has_aws_credentials and not has_smtp_credentials:
        print("⚠️  ERROR: No email delivery method configured!")
        print()
        print("Option 1 - Use Gmail SMTP:")
        print("1. Enable 2-Step Verification in Google Account")
        print("2. Generate an App Password at: https://myaccount.google.com/apppasswords")
        print("3. Set environment variable:")
        print(f'   export SMTP_PASSWORD="your-app-password"')
        print()
        print("Option 2 - Use AWS SES:")
        print("   export AWS_ACCESS_KEY_ID=...")
        print("   export AWS_SECRET_ACCESS_KEY=...")
        print("   OR configure ~/.aws/credentials file")
        print()
        return 1

    if has_aws_credentials:
        if has_aws_env:
            print("✓ AWS credentials detected (environment variables) - will use AWS SES")
        else:
            print("✓ AWS credentials detected (~/.aws/credentials) - will use AWS SES")
    elif has_smtp_credentials:
        print("✓ SMTP credentials detected - will use Gmail SMTP")
    print()

    # Initialize emailer
    print("Initializing emailer...")
    emailer = Emailer(
        sender=sender,
        recipients=recipients,
        subject_prefix="[TEST - Paper Watcher]",
        aws_region=aws_region,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
    )
    print("✓ Emailer initialized")
    print()

    # Send test email
    print("Sending test email...")
    print("-" * 70)

    try:
        success = emailer.send_email(
            results=results,
            keywords=keywords,
            stats=stats,
            min_results=1
        )

        print("-" * 70)
        print()

        if success:
            print("✓ SUCCESS! Email sent successfully!")
            print(f"  Check your inbox: {', '.join(recipients)}")
            return 0
        else:
            print("✗ FAILED: Email was not sent")
            print("  Check the logs above for errors")
            return 1

    except Exception as e:
        print("-" * 70)
        print()
        print(f"✗ ERROR: {e}")
        print()
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
