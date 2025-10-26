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

### AWS Serverless 배포

1. `sam build`
2. `sam deploy --guided`
3. (배포 후) EventBridge 스케줄 또는 Lambda 콘솔 테스트로 실행 확인

### 로컬 실행 (개발/테스트)

Paper Watcher는 AWS Lambda 없이도 로컬에서 직접 실행할 수 있습니다.

#### 1. 환경 설정

```bash
# 가상 환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 설정 파일 복사 및 수정
cp .env.example .env
# .env 파일에서 AWS credentials, email 설정 등을 입력

# config.yaml 수정 (키워드, 이메일 주소 등)
vim config.yaml
```

#### 2. Daily Runner 스크립트 사용

**`bin/run-daily.py`** - Production-ready 일일 실행 스크립트

```bash
# 방법 1: Shell wrapper 사용 (권장)
./bin/run-daily.sh                           # 기본 실행
./bin/run-daily.sh --dry-run                 # Dry run
./bin/run-daily.sh --reset-state             # 상태 초기화
./bin/run-daily.sh --provider bing           # Bing API
./bin/run-daily.sh --keywords "parp,isg"     # 키워드 오버라이드
./bin/run-daily.sh --min-results 5           # 최소 결과 수
./bin/run-daily.sh --verbose                 # 상세 로깅

# 방법 2: Python 직접 실행
./venv/bin/python bin/run-daily.py --dry-run
```

**실행 흐름:**
1. 설정 로드 (`config.yaml` + 환경변수 병합)
2. 웹 크롤링 (Bing API 또는 HTTP)
3. 중복 제거 (`.data/seen.json` 기반)
4. 결과 >= `min_results`이면 이메일 전송
5. 상태 저장 및 종료

**종료 코드:**
- `0`: 성공
- `1`: 에러 발생

#### 3. CLI 개발 도구 (고급)

**`src/crawler/main.py`** - 개발자용 상세 제어 도구

```bash
# 크롤링만 (이메일 없음)
./run_crawler.sh --limit 10

# 크롤링 + 이메일
./run_crawler.sh --send-email

# 스토리지 통계
./run_crawler.sh --stats

# 오래된 레코드 정리
./run_crawler.sh --cleanup

# 중복 제거 비활성화 (디버깅)
./run_crawler.sh --no-dedup --send-email
```

#### 4. 일일 자동화 (Cron)

```bash
# crontab -e
# 매일 09:00 UTC에 실행
0 9 * * * cd /path/to/demoSES && ./venv/bin/python bin/run-daily.py >> logs/daily.log 2>&1
```

#### 5. GitHub Actions 자동화

Paper Watcher는 GitHub Actions를 통해 자동으로 실행할 수 있습니다.

**워크플로우:** `.github/workflows/daily-crawl.yml`

**스케줄:**
- 매일 UTC 00:00 (KST 09:00) 자동 실행
- Actions 탭에서 수동 트리거 가능

**설정 방법:**

1. **GitHub Secrets 설정** (Settings → Secrets and variables → Actions)

   **필수 Secrets:**
   | Secret 이름 | 설명 | 예시 |
   |------------|------|------|
   | `EMAIL_FROM` | 발신 이메일 주소 | `alerts@your-domain.com` |
   | `EMAIL_TO` | 수신 이메일 주소 | `recipient@example.com` |
   | `AWS_REGION` | AWS 리전 | `ap-northeast-2` |
   | `AWS_ACCESS_KEY_ID` | AWS Access Key | `AKIAIOSFODNN7EXAMPLE` |
   | `AWS_SECRET_ACCESS_KEY` | AWS Secret Key | `wJalrXUtnFEMI/K7MDENG/...` |

   **선택 Secrets:**
   | Secret 이름 | 설명 | 필요 조건 |
   |------------|------|----------|
   | `BING_API_KEY` | Bing Search API 키 | provider=bing 사용 시 |
   | `SMTP_HOST` | SMTP 서버 주소 | SMTP fallback 사용 시 |
   | `SMTP_PORT` | SMTP 포트 | SMTP fallback 사용 시 |
   | `SMTP_USER` | SMTP 사용자명 | SMTP fallback 사용 시 |
   | `SMTP_PASSWORD` | SMTP 비밀번호 | SMTP fallback 사용 시 |

2. **워크플로우 활성화**

   Repository에 `.github/workflows/daily-crawl.yml` 파일이 있으면 자동으로 활성화됩니다.

3. **수동 실행 (테스트)**

   GitHub Repository → Actions → "Daily Paper Watcher" → Run workflow

   수동 실행 옵션:
   - **Provider**: `http` (기본) 또는 `bing`
   - **Dry run**: 이메일 발송 없이 테스트
   - **Verbose**: 상세 로깅 활성화

4. **실행 로그 확인**

   Actions 탭에서 각 실행의 상세 로그를 확인할 수 있습니다.

**AWS SES 권한 설정:**

GitHub Actions에서 SES를 사용하려면 IAM 사용자에게 다음 권한이 필요합니다:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ses:SendEmail",
        "ses:SendRawEmail"
      ],
      "Resource": "*"
    }
  ]
}
```

**주의사항:**
- GitHub Actions는 매월 2,000분 무료 (Public 리포지토리는 무제한)
- AWS credentials는 절대 코드에 커밋하지 마세요
- Secrets는 로그에 자동으로 마스킹됩니다

## CLI 옵션 레퍼런스

### `bin/run-daily.py` 옵션

| 옵션 | 설명 | 예시 |
|------|------|------|
| `--config PATH` | 설정 파일 경로 | `--config my-config.yaml` |
| `--dry-run` | 이메일 발송 없이 테스트 | `--dry-run` |
| `--reset-state` | 중복 제거 상태 초기화 | `--reset-state` |
| `--provider PROVIDER` | 검색 공급자 (bing\|http) | `--provider bing` |
| `--keywords KEYWORDS` | 키워드 오버라이드 (콤마 구분) | `--keywords "parp,isg"` |
| `--min-results N` | 최소 결과 수 임계값 | `--min-results 5` |
| `--verbose, -v` | 상세 로깅 (DEBUG) | `--verbose` |
| `--storage-path PATH` | 스토리지 파일 경로 | `--storage-path /tmp/seen.json` |

## Testing

Paper Watcher includes comprehensive test coverage with unit, integration, and smoke tests.

### Running Tests Locally

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run specific test categories
pytest -m unit          # Unit tests only (fast)
pytest -m integration   # Integration tests (slower)
pytest -m smoke         # Smoke tests (basic sanity)

# Run tests with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_storage.py -v

# Run specific test function
pytest tests/test_storage.py::test_is_seen_new_item -v
```

### Test Organization

Tests are organized using pytest markers:

| Marker | Description | Examples |
|--------|-------------|----------|
| `unit` | Fast, isolated unit tests | Storage hashing, config validation |
| `integration` | Tests with external dependencies | Full workflow, crawler + dedup + email |
| `smoke` | Basic functionality checks | Module imports, component initialization |
| `slow` | Long-running tests | Large dataset processing (skipped by default) |
| `requires_api` | Tests requiring external APIs | Bing Search, PubMed (mocked in CI) |
| `requires_aws` | Tests requiring AWS credentials | SES email sending (mocked in CI) |

### Test Coverage

Current test files:
- `tests/test_crawler.py` - Web crawler tests (Bing API, HTTP)
- `tests/test_storage.py` - Deduplication and storage tests
- `tests/test_emailer.py` - Email delivery tests (SES, SMTP)
- `tests/test_integration.py` - End-to-end workflow tests
- `tests/test_filtering.py` - Keyword filtering pipeline tests
- `tests/test_runtime.py` - Runtime configuration tests
- `tests/test_keyword_registry.py` - Keyword registry tests

### Continuous Integration

GitHub Actions automatically runs tests on:
- **Pull Requests**: All tests run on every PR to `main`
- **Push to main**: Full test suite on merge
- **Manual trigger**: Via Actions tab

The test workflow (`.github/workflows/test.yml`) includes:
1. Unit tests
2. Integration tests (with mocked HTTP/SES)
3. Smoke tests
4. Code coverage reporting
5. Linting (black, ruff, mypy)

View test results: [Actions tab](../../actions/workflows/test.yml)

### Mocking External Services

Tests use the following mocking libraries:
- **HTTP requests**: `responses`, `pytest-httpx`
- **AWS SES**: `moto[ses]`
- **Boto3**: `moto` for DynamoDB (if needed)

Example:
```python
@pytest.mark.integration
@patch('src.emailer.boto3')
def test_email_workflow(mock_boto3):
    mock_ses = MagicMock()
    mock_ses.send_email.return_value = {"MessageId": "test-123"}
    mock_boto3.client.return_value = mock_ses
    # Test email delivery
```

## Development Checklist

다음 단계 작업 목록:

- [x] ✅ 설정/비밀(키워드/수신자/크롤러 공급자/API키) 정의
- [x] ✅ 크롤러/중복제거/발송 모듈 추가
- [x] ✅ 로컬 실행 스크립트 (`bin/run-daily.py`)
- [x] ✅ 하루 1회 스케줄(GitHub Actions)
- [x] ✅ 테스트/모의(HTTP, SES)

## 기능 완성도

- ✅ **Configuration Management**: YAML config + 환경변수 지원
- ✅ **Web Crawling**: Bing API + HTTP 직접 크롤링
- ✅ **Deduplication**: SHA-256 해싱 + TTL 기반 스토리지
- ✅ **Email Delivery**: AWS SES + SMTP fallback
- ✅ **CLI Tools**: Production runner + Developer tools
- ✅ **GitHub Actions**: 일일 자동화 + 수동 트리거 + PR 테스트
- ✅ **Testing**: Unit, Integration, Smoke tests with mocked HTTP/SES

