# Paper Watcher (Serverless Edition)

This project deploys a fully managed pipeline that monitors **Nature**, **Cell**, and **Science** for new publications matching configured keywords. The solution runs on AWS Lambda, stores deduplication state in DynamoDB, retrieves configuration from AWS Secrets Manager, and delivers consolidated alerts via Amazon SES (API by default, SMTP optional).

## Architecture Overview

- **AWS Lambda (Python 3.11)** fetches papers from Crossref, PubMed, and official RSS feeds, deduplicates via DynamoDB, and sends a single aggregated email when new results are detected.
- **Amazon EventBridge Scheduler** triggers the Lambda once per day at 09:00 UTC (configurable).
- **Amazon DynamoDB** table `paper_seen` stores previously notified paper identifiers.
- **AWS Secrets Manager** holds SES delivery metadata and optional API credentials/User-Agent email.
- **Amazon SES** sends notifications using the SendEmail API, with optional SMTP fallback if credentials are supplied.

## Repository Layout

```
template.yaml        # AWS SAM template defining Lambda, DynamoDB, scheduler, and IAM permissions
requirements.txt     # Python dependencies bundled with the Lambda
src/
  handler.py         # Lambda entry point
  config.py          # Environment and secrets loading
  dal.py             # DynamoDB repository helpers
  mailer.py          # SES / SMTP email sender
  util.py            # Shared helpers (keywords, highlighting, formatting)
  sources/
    crossref.py      # Crossref REST API client
    pubmed.py        # PubMed E-utilities client
    rss.py           # RSS feed fallback client
```

## Prerequisites

1. AWS account with permissions to deploy SAM stacks, manage Lambda, DynamoDB, EventBridge, SES, and Secrets Manager.
2. SES production access with verified sender domain/email and approved recipients (unless in sandbox).
3. Two Secrets Manager secrets:
   - `paperwatcher/ses`: `{"sender": "from@domain", "recipients": ["to@domain"], "region": "ap-northeast-2"}` plus optional SMTP keys (`smtp_user`, `smtp_pass`, `host`, `port`).
   - `paperwatcher/api`: `{"pubmed_api_key": "<optional>", "user_agent_email": "you@example.com"}`.

## Deployment

1. Ensure the AWS CLI and AWS SAM CLI are configured (see [SAM documentation](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)).
2. (Optional) Update `template.yaml` parameter defaults or override during deployment.
3. Build and deploy:

```bash
sam build
sam deploy --guided
```

During guided deployment you will be prompted for stack name, AWS Region, parameter overrides (table name, secret names, schedule, SMTP toggle), and permission confirmations.

## Operation

- After deployment, EventBridge triggers the Lambda once per day according to the configured cron schedule. The function fetches the latest papers within the `WINDOW_HOURS` window and emails a consolidated digest when new matches exist.
- To test manually, open the Lambda function in the AWS console and invoke it with `{}`. Check CloudWatch Logs for execution details.
- DynamoDB table `paper_seen` maintains idempotency. Removing an item allows it to be emailed again if still within the window.
- Toggle SMTP delivery by setting the `UseSmtp` parameter (and providing SMTP credentials in the SES secret).

## Configuration Reference

Environment variables are configured within `template.yaml` and can be overridden via parameter overrides:

| Variable | Description |
| --- | --- |
| `KEYWORDS` | Comma-separated keyword list (case-insensitive). |
| `MATCH_MODE` | `OR` or `AND` keyword evaluation. |
| `WINDOW_HOURS` | Sliding time window for new papers. |
| `SOURCES` | Comma-separated list of enabled sources (`crossref`, `pubmed`, `rss`). |
| `APP_NAME` | User-Agent prefix for outbound HTTP requests. |
| `DDB_TABLE` | DynamoDB table storing seen paper IDs. |
| `SES_SECRET_NAME` | Secrets Manager secret containing SES configuration. |
| `API_SECRET_NAME` | Secrets Manager secret containing API-related configuration. |
| `USE_SMTP` | `true` to force SMTP delivery (requires credentials in SES secret). |

## Monitoring & Logging

- CloudWatch Logs capture INFO-level execution traces, including request counts, new item counts, and email delivery status. Exceptions are logged at WARNING/ERROR with stack traces.
- Lambda metrics (Invocations, Errors, Duration) and EventBridge metrics provide operational visibility. Configure CloudWatch Alarms as needed.

## Security Considerations

- Secrets remain in AWS Secrets Manager and are fetched at runtime; no secrets are stored in environment variables or code.
- IAM policies follow the principle of least privilege (read-only secrets, minimal DynamoDB and SES permissions).
- Emails sanitize headers to mitigate injection risks.

## 빠른 시작

1. `sam build`
2. `sam deploy --guided`
3. (배포 후) EventBridge 스케줄 또는 Lambda 콘솔 테스트로 실행 확인

