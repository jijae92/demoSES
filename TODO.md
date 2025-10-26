# demoSES Implementation TODO

## 우선순위 분류

- **P0 (Critical)**: 즉시 수정 필요 - 기능 장애 또는 데이터 정합성 문제
- **P1 (High)**: 1-2주 내 수정 - 안정성/보안/코드 품질 개선
- **P2 (Medium)**: 1-2개월 내 수정 - 운영 효율성 및 유지보수성 개선

---

## 🔴 P0: Critical Priority (즉시 수정)

### P0-1: 하드코딩된 키워드 제거 🚨

**파일**: `src/runtime.py:58`

**현재 코드**:
```python
keywords = _normalize_keywords(payload.get("keywords"), config.keywords)
# Always enforce the fixed keyword set for production searches, regardless of overrides.
keywords = FIXED_KEYWORDS  # ⚠️ 이 줄 삭제
```

**수정 방안**:
```python
# Option 1: 하드코딩 완전 제거
keywords = _normalize_keywords(payload.get("keywords"), config.keywords)

# Option 2: 환경변수로 제어
if os.environ.get("FORCE_FIXED_KEYWORDS", "false").lower() == "true":
    keywords = FIXED_KEYWORDS
else:
    keywords = _normalize_keywords(payload.get("keywords"), config.keywords)
```

**영향 범위**: 전체 키워드 검색 기능
**예상 시간**: 5분
**테스트**:
```bash
# 환경변수 변경 후 재배포
sam build && sam deploy

# 테스트 이벤트로 검증
aws lambda invoke \
  --function-name PaperWatcherFunction \
  --payload '{"keywords": ["covid", "vaccine"]}' \
  response.json
```

---

### P0-2: DynamoDB ConsistentRead 활성화

**파일**: `src/dal.py:31`

**현재 코드**:
```python
response = self._client.get_item(
    TableName=self.table_name,
    Key={"paper_id": {"S": paper_id}},
    ProjectionExpression="paper_id",
    ConsistentRead=False,  # ⚠️ False → True
)
```

**수정**:
```python
ConsistentRead=True,  # Eventual → Strong consistency
```

**영향 범위**: 중복 이메일 발송 방지
**예상 시간**: 2분
**트레이드오프**:
- 비용: PAY_PER_REQUEST 모드에서는 동일
- 레이턴시: ~5-10ms 증가 (무시 가능)

**테스트**:
```python
# tests/test_dal.py
def test_is_seen_consistency():
    repo = SeenRepository("paper_seen")
    item = PaperItem(...)
    repo.mark_seen([item])
    assert repo.is_seen(item.paper_id)  # 즉시 확인 가능
```

---

### P0-3: 의존성 버전 고정

**파일**: `requirements.txt`, `src/requirements.txt`

**현재**:
```
requests
feedparser
tenacity
PyYAML>=6.0,<7
```

**수정**:
```bash
# 1. 현재 환경의 버전 고정
pip freeze | grep -E 'requests|feedparser|tenacity|PyYAML|boto3' > requirements.lock

# 2. requirements.txt 업데이트
cat requirements.lock
```

**예상 결과**:
```
requests==2.31.0
feedparser==6.0.10
tenacity==8.2.3
PyYAML==6.0.1
boto3==1.34.69
```

**영향 범위**: 빌드 재현성
**예상 시간**: 10분

---

## 🟠 P1: High Priority (1-2주 내)

### P1-1: Lambda 타임아웃 및 HTTP 타임아웃 조정

**파일**:
- `template.yaml:16`
- `src/sources/crossref.py:17`
- `src/sources/pubmed.py:17`
- `src/sources/rss.py:23`

**수정 1**: Lambda timeout 증가
```yaml
# template.yaml:16
Timeout: 180  # 60 → 180초
```

**수정 2**: HTTP timeout 증가
```python
# src/sources/*.py
DEFAULT_TIMEOUT = 20  # 10 → 20초
```

**수정 3**: Tenacity 재시도 횟수 감소
```python
@retry(
    stop=stop_after_attempt(3),  # 5 → 3
    wait=wait_exponential(multiplier=1, min=1, max=10),  # max 60 → 10
)
```

**예상 시간**: 15분

---

### P1-2: Secrets Manager 캐싱 추가

**파일**: `src/config.py`

**방법 1: 수동 캐싱**
```python
import time

class ConfigLoader:
    def __init__(self):
        self._secrets_client = boto3.client("secretsmanager")
        self._cache: Dict[str, Tuple[Dict, float]] = {}
        self._cache_ttl = 300  # 5분

    def _load_secret(self, secret_name: str) -> Dict[str, Any]:
        now = time.time()
        if secret_name in self._cache:
            data, timestamp = self._cache[secret_name]
            if now - timestamp < self._cache_ttl:
                LOGGER.debug("Using cached secret: %s", secret_name)
                return data

        # Secrets Manager API 호출
        try:
            response = self._secrets_client.get_secret_value(SecretId=secret_name)
        except (ClientError, BotoCoreError) as exc:
            LOGGER.error("Failed to load secret %s: %s", secret_name, exc)
            raise

        secret_string = response.get("SecretString")
        if not secret_string:
            raise ValueError(f"Secret {secret_name} did not contain SecretString")

        data = json.loads(secret_string)
        self._cache[secret_name] = (data, now)
        LOGGER.info("Loaded and cached secret: %s", secret_name)
        return data
```

**방법 2: AWS Lambda Extension 사용 (권장)**
```yaml
# template.yaml에 추가
Resources:
  PaperWatcherFunction:
    Properties:
      Layers:
        - arn:aws:lambda:ap-northeast-2:738900069198:layer:AWS-Parameters-and-Secrets-Lambda-Extension:11
      Environment:
        Variables:
          PARAMETERS_SECRETS_EXTENSION_CACHE_ENABLED: "true"
          PARAMETERS_SECRETS_EXTENSION_CACHE_SIZE: "10"
          PARAMETERS_SECRETS_EXTENSION_TTL_SECONDS: "300"
```

```python
# src/config.py 수정 (Extension 사용 시)
import os
import urllib.request

def _load_secret_via_extension(self, secret_name: str) -> Dict[str, Any]:
    url = f"http://localhost:2773/secretsmanager/get?secretId={secret_name}"
    headers = {"X-Aws-Parameters-Secrets-Token": os.environ.get("AWS_SESSION_TOKEN")}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())
        return json.loads(data["SecretString"])
```

**예상 시간**: 30분 (방법 1) / 20분 (방법 2)
**비용 절감**: ~$0.70/월

---

### P1-3: BatchWriteItem 재시도 로직 추가

**파일**: `src/dal.py:62`

**수정**:
```python
def mark_seen(self, items: Sequence[PaperItem]) -> None:
    if not items:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    requests = [
        {
            "PutRequest": {
                "Item": {
                    "paper_id": {"S": item.paper_id},
                    "source": {"S": item.source},
                    "title": {"S": item.title[:400]},
                    "created_at": {"S": now_iso},
                }
            }
        }
        for item in items
    ]
    chunks = [requests[i : i + 25] for i in range(0, len(requests), 25)]

    for chunk_idx, chunk in enumerate(chunks):
        backoff = 0.1
        remaining = chunk
        for attempt in range(5):
            try:
                response = self._client.batch_write_item(
                    RequestItems={self.table_name: remaining}
                )
            except (ClientError, BotoCoreError):
                LOGGER.exception("DynamoDB batch_write_item failed")
                raise

            unprocessed = response.get("UnprocessedItems", {}).get(self.table_name, [])
            if not unprocessed:
                LOGGER.info("Chunk %d written successfully (%d items)", chunk_idx + 1, len(chunk))
                break

            LOGGER.warning(
                "Chunk %d: Retry %d with %d unprocessed items",
                chunk_idx + 1,
                attempt + 1,
                len(unprocessed),
            )
            remaining = unprocessed
            time.sleep(backoff)
            backoff = min(backoff * 2, 5.0)  # 최대 5초
        else:
            raise RuntimeError(
                f"Failed to write {len(remaining)} items in chunk {chunk_idx + 1} after 5 attempts"
            )
```

**예상 시간**: 30분

---

### P1-4: 예외 처리 구체화

**파일**: `src/handler.py:29`, `src/handler.py:182`

**수정**:
```python
# handler.py:29
try:
    base_config = get_config()
except (ValueError, ClientError, BotoCoreError) as exc:
    LOGGER.error("Configuration error: %s", exc, exc_info=True)
    raise

# handler.py:182 (소스 fetch)
except (requests.RequestException, ValueError, KeyError) as exc:
    LOGGER.exception("Failed to fetch items from %s", source)
    continue
```

**예상 시간**: 15분

---

### P1-5: API 키 로깅 마스킹

**파일**: `src/sources/pubmed.py`

**추가**:
```python
def _mask_params(params: Dict[str, str]) -> Dict[str, str]:
    """Mask sensitive parameters for logging."""
    masked = params.copy()
    for key in ("api_key", "apikey", "token", "password"):
        if key in masked:
            masked[key] = "***"
    return masked

# 로깅 수정
LOGGER.info(
    "PUBMED request: params=%s",
    _mask_params(params),
)
```

**예상 시간**: 15분

---

### P1-6: HTML 파싱 개선

**파일**: `src/sources/crossref.py:80`

**수정**:
```python
from html.parser import HTMLParser

class _HTMLStripper(HTMLParser):
    """Robust HTML tag stripper using standard library."""

    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)

    def get_text(self):
        return " ".join(self.text)

def _strip_tags(raw: str) -> str:
    """Remove HTML tags from text content."""
    if not raw:
        return ""
    stripper = _HTMLStripper()
    try:
        stripper.feed(raw)
        return stripper.get_text()
    except Exception:
        # Fallback: regex-based stripping
        LOGGER.warning("HTML parsing failed, using regex fallback")
        return _TAG_RE.sub(" ", raw)
```

**예상 시간**: 20분

---

### P1-7: 단위 테스트 추가

**디렉토리**: `tests/`

**작업**:
1. **pytest 설정**:
```bash
pip install pytest pytest-cov pytest-mock moto
```

2. **테스트 파일 생성**:

```python
# tests/test_util.py
import pytest
from src.util import parse_keywords, highlight_text, sanitize_header

def test_parse_keywords_empty():
    assert parse_keywords("") == []

def test_parse_keywords_single():
    assert parse_keywords("covid") == ["covid"]

def test_parse_keywords_multiple():
    assert parse_keywords("covid, vaccine, omicron") == ["covid", "vaccine", "omicron"]

def test_parse_keywords_whitespace():
    assert parse_keywords("  covid  ,  vaccine  ") == ["covid", "vaccine"]

def test_highlight_text():
    result = highlight_text("COVID-19 vaccine", ["covid", "vaccine"])
    assert "[COVID" in result or "[vaccine]" in result

def test_sanitize_header_valid():
    assert sanitize_header("Valid Header") == "Valid Header"

def test_sanitize_header_invalid():
    with pytest.raises(ValueError):
        sanitize_header("Invalid\r\nHeader")
```

```python
# tests/test_filtering.py
from src.pipeline.filtering import keyword_match, filter_items
from src.util import PaperItem

def test_keyword_match_or_mode():
    matched, terms = keyword_match(
        "COVID-19 vaccine study",
        "This is about vaccines",
        ["covid", "influenza"],
        "OR"
    )
    assert matched is True
    assert "covid" in terms

def test_keyword_match_and_mode():
    matched, terms = keyword_match(
        "COVID-19 vaccine study",
        "influenza research",
        ["covid", "influenza"],
        "AND"
    )
    assert matched is False  # title에 influenza 없음

def test_filter_items_deduplication():
    items = {
        "source1": [
            PaperItem("source1", "doi:123", "Title", [], None, "http://", matched_keywords=["covid"]),
            PaperItem("source1", "doi:123", "Title", [], None, "http://", matched_keywords=["covid"]),  # 중복
        ]
    }
    filtered, stats = filter_items(items, ["covid"], "OR")
    assert stats.post_dedup == 1  # 중복 제거됨
```

```python
# tests/test_config.py
import pytest
from unittest.mock import patch, MagicMock
from src.config import ConfigLoader

@patch("boto3.client")
def test_config_loader_missing_env(mock_boto_client):
    with patch.dict("os.environ", {}, clear=True):
        loader = ConfigLoader()
        with pytest.raises(ValueError, match="DDB_TABLE"):
            loader.load()

@patch("boto3.client")
def test_config_loader_valid(mock_boto_client):
    mock_sm = MagicMock()
    mock_boto_client.return_value = mock_sm
    mock_sm.get_secret_value.side_effect = [
        {"SecretString": '{"sender": "a@b.com", "recipients": ["c@d.com"], "region": "us-east-1"}'},
        {"SecretString": '{"pubmed_api_key": null, "user_agent_email": "e@f.com"}'},
    ]
    with patch.dict("os.environ", {
        "DDB_TABLE": "test_table",
        "SES_SECRET_NAME": "ses",
        "API_SECRET_NAME": "api",
    }):
        loader = ConfigLoader()
        config = loader.load()
        assert config.ddb_table == "test_table"
```

3. **GitHub Actions CI 추가**:
```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt pytest pytest-cov moto
      - run: pytest tests/ --cov=src --cov-report=term-missing
```

**예상 시간**: 2-3시간

---

## 🟡 P2: Medium Priority (1-2개월 내)

### P2-1: Dead Letter Queue 추가

**파일**: `template.yaml`

**추가**:
```yaml
Resources:
  PaperWatcherDLQ:
    Type: AWS::SQS::Queue
    Properties:
      QueueName: paper-watcher-dlq
      MessageRetentionPeriod: 1209600  # 14일
      VisibilityTimeout: 300

  PaperWatcherFunction:
    Type: AWS::Serverless::Function
    Properties:
      DeadLetterQueue:
        Type: SQS
        TargetArn: !GetAtt PaperWatcherDLQ.Arn
      EventInvokeConfig:
        MaximumRetryAttempts: 1
      # ... 기존 설정 ...

  DLQAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: PaperWatcherDLQAlarm
      MetricName: ApproximateNumberOfMessagesVisible
      Namespace: AWS/SQS
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 1
      ComparisonOperator: GreaterThanOrEqualToThreshold
      Dimensions:
        - Name: QueueName
          Value: !GetAtt PaperWatcherDLQ.QueueName
      AlarmActions:
        - !Ref AlertSNSTopic  # SNS 토픽 별도 생성 필요

  AlertSNSTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: PaperWatcherAlerts
      Subscription:
        - Endpoint: your-email@example.com
          Protocol: email
```

**예상 시간**: 30분

---

### P2-2: EventBridge 재시도 정책

**파일**: `template.yaml:70`

**수정**:
```yaml
Events:
  DailySchedule:
    Type: Schedule
    Properties:
      Schedule: !Ref ScheduleExpression
      Name: paper-watcher-schedule
      Description: Daily trigger for paper watcher Lambda
      RetryPolicy:
        MaximumRetryAttempts: 2  # 0 → 2
        MaximumEventAgeInSeconds: 3600  # 1시간
```

**예상 시간**: 2분

---

### P2-3: CloudWatch 메트릭 추가

**파일**: `src/handler.py`

**추가**:
```python
import boto3
cloudwatch = boto3.client("cloudwatch")

def _publish_metrics(namespace: str, metrics: Dict[str, float], dimensions: Dict[str, str]):
    """Publish custom metrics to CloudWatch."""
    metric_data = [
        {
            "MetricName": name,
            "Value": value,
            "Unit": "Count",
            "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()],
        }
        for name, value in metrics.items()
    ]
    try:
        cloudwatch.put_metric_data(Namespace=namespace, MetricData=metric_data)
    except Exception:
        LOGGER.exception("Failed to publish metrics")

# handler.py에서 호출
def lambda_handler(event, context):
    # ... 기존 로직 ...

    # 메트릭 발행
    _publish_metrics(
        "PaperWatcher",
        {
            "TotalFetched": total_fetched,
            "TotalMatched": filter_stats.post_keyword,
            "TotalNew": new_total,
            "EmailsSent": 1 if new_total > 0 else 0,
        },
        {"Environment": "Production"},
    )

    # 소스별 메트릭
    for source, count in fetch_counts.items():
        _publish_metrics(
            "PaperWatcher/Sources",
            {"Fetched": count},
            {"Source": source},
        )
```

**대시보드 생성**:
```yaml
# template.yaml에 추가
Resources:
  PaperWatcherDashboard:
    Type: AWS::CloudWatch::Dashboard
    Properties:
      DashboardName: PaperWatcherMetrics
      DashboardBody: !Sub |
        {
          "widgets": [
            {
              "type": "metric",
              "properties": {
                "metrics": [
                  ["PaperWatcher", "TotalFetched"],
                  [".", "TotalMatched"],
                  [".", "TotalNew"]
                ],
                "period": 86400,
                "stat": "Sum",
                "region": "${AWS::Region}",
                "title": "Daily Paper Stats"
              }
            }
          ]
        }
```

**예상 시간**: 1시간

---

### P2-4: X-Ray 추적 활성화

**파일**: `template.yaml`

**수정**:
```yaml
Resources:
  PaperWatcherFunction:
    Properties:
      Tracing: Active  # X-Ray 활성화
      # ... 기존 설정 ...

      Policies:
        - AWSXRayDaemonWriteAccess  # X-Ray 권한 추가
        # ... 기존 정책 ...
```

```python
# src/handler.py에 추가
from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all

patch_all()  # boto3, requests 등 자동 패치

@xray_recorder.capture("fetch_sources")
def _fetch_sources(...):
    # ... 기존 로직 ...
```

**예상 시간**: 30분

---

### P2-5: 이메일 발송 순서 변경

**파일**: `src/handler.py:141-147`

**현재**:
```python
repository.mark_seen(flat_items)  # DDB 먼저
send_email(...)  # 이메일 나중 (실패 시 논문 손실)
```

**수정**:
```python
# 순서 변경: 이메일 먼저, DDB 나중
try:
    send_email(new_items, config, runtime, window_start_dt, window_end_dt, summary)
except EmailDeliveryError as exc:
    LOGGER.error("Email delivery failed: %s", exc)
    raise  # 이메일 실패 시 DDB 업데이트 안 함 (다음 실행에서 재시도)

# 이메일 성공 후에만 DDB 업데이트
try:
    repository.mark_seen(flat_items)
except (ClientError, BotoCoreError):
    LOGGER.exception("Failed to update DynamoDB (email already sent)")
    # DDB 실패는 로깅만 하고 성공 처리 (이메일은 이미 발송됨)
```

**트레이드오프**:
- 장점: 이메일 발송 실패 시 다음 실행에서 재시도 가능
- 단점: 이메일 성공 + DDB 실패 시 중복 발송 (드문 경우)

**예상 시간**: 10분

---

### P2-6: 리트라이 로직 공통화

**파일**: `src/util.py` (신규), `src/sources/*.py` (수정)

**추가**: `src/util.py`
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests

def api_retry(max_attempts: int = 3, max_wait: int = 10):
    """Common retry decorator for API calls."""
    return retry(
        retry=retry_if_exception_type((requests.RequestException, requests.HTTPError)),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=max_wait),
        reraise=True,
    )
```

**수정**: 각 소스 파일
```python
from util import api_retry

@api_retry(max_attempts=3, max_wait=10)
def _perform_request(...):
    # ... 기존 로직 ...
```

**예상 시간**: 20분

---

### P2-7: 레거시 코드 정리

**삭제 대상**:
- `config/keywords.yml` (사용되지 않음)
- `backend/search/` (사용되지 않음)
- `vendor/` (용도 불명 시 삭제)

**정리**:
```bash
git rm -r config/keywords.yml backend/ vendor/
git commit -m "chore: remove unused legacy code"
```

**예상 시간**: 10분

---

### P2-8: IAM 권한 최소화

**파일**: `template.yaml`

**현재**:
```yaml
- Effect: Allow
  Action:
    - ses:SendEmail
    - ses:SendRawEmail
  Resource: "*"  # ⚠️ 과도한 권한
```

**수정**:
```yaml
- Effect: Allow
  Action:
    - ses:SendEmail
    - ses:SendRawEmail
  Resource:
    - !Sub "arn:aws:ses:${AWS::Region}:${AWS::AccountId}:identity/${SenderEmail}"
```

또는 조건 추가:
```yaml
- Effect: Allow
  Action:
    - ses:SendEmail
    - ses:SendRawEmail
  Resource: "*"
  Condition:
    StringEquals:
      ses:FromAddress: !Ref SenderEmail
```

**예상 시간**: 15분

---

## 📋 작업 체크리스트

### Week 1 (P0)
- [ ] P0-1: 키워드 하드코딩 제거
- [ ] P0-2: ConsistentRead 활성화
- [ ] P0-3: 의존성 버전 고정
- [ ] 테스트 및 재배포

### Week 2 (P1 Part 1)
- [ ] P1-1: Lambda/HTTP 타임아웃 조정
- [ ] P1-2: Secrets Manager 캐싱
- [ ] P1-3: BatchWriteItem 재시도
- [ ] 통합 테스트

### Week 3 (P1 Part 2)
- [ ] P1-4: 예외 처리 구체화
- [ ] P1-5: API 키 마스킹
- [ ] P1-6: HTML 파싱 개선
- [ ] 코드 리뷰

### Week 4 (P1 Part 3)
- [ ] P1-7: 단위 테스트 작성
- [ ] GitHub Actions CI 설정
- [ ] 테스트 커버리지 80% 달성

### Month 2 (P2)
- [ ] P2-1: DLQ 추가
- [ ] P2-2: EventBridge 재시도
- [ ] P2-3: CloudWatch 메트릭
- [ ] P2-4: X-Ray 추적
- [ ] P2-5: 이메일/DDB 순서 변경
- [ ] P2-6: 리트라이 공통화
- [ ] P2-7: 레거시 정리
- [ ] P2-8: IAM 권한 최소화

---

## 🧪 테스트 전략

### 로컬 테스트
```bash
# 1. 단위 테스트
pytest tests/ -v --cov=src

# 2. SAM Local 테스트
sam build
sam local invoke PaperWatcherFunction --event event.json

# 3. 통합 테스트 (DynamoDB Local)
docker run -p 8000:8000 amazon/dynamodb-local
AWS_ENDPOINT_URL=http://localhost:8000 pytest tests/integration/
```

### 배포 전 검증
```bash
# 1. Linting
ruff check src/
black --check src/

# 2. Type checking
mypy src/ --strict

# 3. SAM validate
sam validate --lint

# 4. 보안 스캔
bandit -r src/
safety check
```

### 프로덕션 배포
```bash
# 1. Staging 배포
sam deploy --config-env staging

# 2. 수동 테스트
aws lambda invoke \
  --function-name PaperWatcherFunction-Staging \
  --payload '{"dry_run": true}' \
  output.json

# 3. 로그 확인
sam logs --name PaperWatcherFunction --stack-name PaperWatcherStack-Staging --tail

# 4. 프로덕션 배포
sam deploy --config-env production
```

---

## 📊 성공 지표

### 코드 품질
- [ ] 테스트 커버리지 > 80%
- [ ] Ruff/Black 린팅 통과
- [ ] Mypy strict 모드 통과

### 안정성
- [ ] Lambda 에러율 < 1%
- [ ] DynamoDB throttling 0건
- [ ] 이메일 발송 성공률 > 99%

### 비용
- [ ] Secrets Manager 호출 60% 감소 (캐싱)
- [ ] Lambda 실행 시간 10% 감소
- [ ] 월 비용 < $1

### 운영
- [ ] DLQ 메시지 0건
- [ ] CloudWatch 알람 0건
- [ ] 중복 이메일 신고 0건

---

**작성일**: 2025-01-27
**대상 리포지토리**: https://github.com/jijae92/demoSES
**예상 총 작업 시간**: ~40시간 (5 working days)
