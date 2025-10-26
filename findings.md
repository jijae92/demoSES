# demoSES Security & Technical Debt Findings

## 리스크 매트릭스

| ID | 분류 | 발생 가능성 | 영향도 | 종합 리스크 | 위치 |
|----|------|------------|--------|------------|------|
| F-01 | Logic Bug | **High** | **Critical** | 🔴 **P0** | src/runtime.py:58 |
| F-02 | Performance | **High** | **High** | 🔴 **P0** | src/config.py:124 |
| F-03 | Data Integrity | **Medium** | **High** | 🟠 **P0** | src/dal.py:31 |
| F-04 | Reliability | **Medium** | **High** | 🟠 **P1** | src/dal.py:62 |
| F-05 | Reliability | **Medium** | **Medium** | 🟡 **P1** | template.yaml:16, src/sources/*.py |
| F-06 | Code Quality | **High** | **Low** | 🟡 **P1** | src/handler.py:29,182 |
| F-07 | Security | **Low** | **High** | 🟡 **P1** | src/sources/crossref.py:168 |
| F-08 | Security | **Medium** | **Medium** | 🟡 **P1** | src/sources/crossref.py:80 |
| F-09 | Reliability | **Low** | **High** | 🟢 **P2** | template.yaml |
| F-10 | Maintainability | **High** | **Low** | 🟢 **P2** | requirements.txt |
| F-11 | Code Quality | **Medium** | **Low** | 🟢 **P2** | src/sources/*.py |
| F-12 | Testing | **High** | **Medium** | 🟡 **P1** | tests/ |
| F-13 | Observability | **Medium** | **Medium** | 🟡 **P2** | src/handler.py |
| F-14 | Reliability | **Medium** | **Medium** | 🟡 **P2** | template.yaml:70 |
| F-15 | Architecture | **Low** | **Medium** | 🟢 **P2** | src/handler.py:141-147 |

---

## 🔴 Critical Priority (P0)

### F-01: 하드코딩된 키워드로 사용자 설정 무시

**위치**: `src/runtime.py:58`

**발견 내용**:
```python
def derive_runtime_options(config: "AppConfig", event: Mapping[str, Any] | None) -> RuntimeOptions:
    # ... 키워드 파싱 로직 ...
    keywords = _normalize_keywords(payload.get("keywords"), config.keywords)
    # Always enforce the fixed keyword set for production searches, regardless of overrides.
    keywords = FIXED_KEYWORDS  # ⚠️ 라인 58: 사용자 입력 완전 무시
```

**문제점**:
- 환경변수 `KEYWORDS` 및 이벤트 페이로드 `keywords` 파라미터가 완전히 무시됨
- `FIXED_KEYWORDS = ("parp", "isg", "interferon", "sting")` 하드코딩
- 사용자가 다른 키워드를 설정해도 효과 없음

**영향도**: **Critical**
- 애플리케이션의 핵심 기능(키워드 검색) 사용자 제어 불가
- 문서화된 설정과 실제 동작 불일치 → 혼란 및 신뢰도 저하

**재현 단계**:
1. 환경변수 `KEYWORDS="covid, vaccine"` 설정
2. Lambda 실행
3. 로그 확인: `"keywords": 4` (parp, isg, interferon, sting)
4. 실제로는 covid, vaccine 검색 안 됨

**권고 사항**:
```python
# src/runtime.py:58 수정
# keywords = FIXED_KEYWORDS  # 이 줄 삭제 또는 주석 처리

# 또는 환경변수로 제어
if os.environ.get("FORCE_FIXED_KEYWORDS", "false").lower() == "true":
    keywords = FIXED_KEYWORDS
```

**우선순위**: P0 (즉시 수정)

---

### F-02: Secrets Manager 캐싱 없음으로 인한 비용 및 레이턴시

**위치**: `src/config.py:124` (`_load_secret` 메서드)

**발견 내용**:
```python
def get_config() -> AppConfig:
    global _loader
    if _loader is None:
        _loader = ConfigLoader()
    return _loader.load()  # 매번 호출 시 Secrets Manager API 요청
```

**문제점**:
- Lambda 컨테이너가 재사용되어도 매 호출마다 2개 시크릿 재조회 (SES + API)
- Secrets Manager 요금: $0.40/10,000 API calls
- 레이턴시: ~50-100ms per secret

**영향도**: **High**
- 월 1,800회 호출 시 (일 30회 × 2 secrets × 30일) $0.072 추가 비용
- Lambda 실행 시간 100-200ms 증가 → 타임아웃 여유 감소

**재현 단계**:
1. Lambda 로그에서 `GetSecretValue` CloudTrail 이벤트 확인
2. 동일 컨테이너에서 연속 실행 시에도 API 호출 발생

**권고 사항**:
```python
# src/config.py에 캐싱 추가
import time
from functools import lru_cache

class ConfigLoader:
    def __init__(self):
        self._secrets_client = boto3.client("secretsmanager")
        self._cache = {}
        self._cache_ttl = 300  # 5분

    def _load_secret(self, secret_name: str) -> Dict[str, Any]:
        now = time.time()
        if secret_name in self._cache:
            data, timestamp = self._cache[secret_name]
            if now - timestamp < self._cache_ttl:
                return data

        # Secrets Manager 조회
        data = self._fetch_secret_from_api(secret_name)
        self._cache[secret_name] = (data, now)
        return data
```

또는 AWS Parameters and Secrets Lambda Extension 사용:
```yaml
# template.yaml에 추가
Layers:
  - arn:aws:lambda:ap-northeast-2:738900069198:layer:AWS-Parameters-and-Secrets-Lambda-Extension:11
```

**우선순위**: P0 (비용 절감 + 성능 개선)

---

### F-03: DynamoDB Eventual Consistency로 인한 중복 이메일 발송 가능

**위치**: `src/dal.py:31`

**발견 내용**:
```python
def is_seen(self, paper_id: str) -> bool:
    response = self._client.get_item(
        TableName=self.table_name,
        Key={"paper_id": {"S": paper_id}},
        ProjectionExpression="paper_id",
        ConsistentRead=False,  # ⚠️ Eventual consistency
    )
    return "Item" in response
```

**문제점**:
- Eventual consistency 모드에서는 최근 `PutItem` 결과가 즉시 반영 안 될 수 있음 (typically <1s, 최대 수 초)
- 짧은 시간 내 Lambda 재실행 시 동일 논문을 "새 논문"으로 오판 가능

**영향도**: **High**
- 중복 이메일 발송 → 사용자 경험 저하
- 발생 확률: EventBridge 재시도나 수동 재실행 시

**재현 단계**:
1. Lambda를 첫 실행하여 논문 A 발견 → DynamoDB 저장
2. 5초 이내에 동일 Lambda 재실행
3. `is_seen(A)` → eventual consistency로 인해 `False` 반환 가능
4. 논문 A가 다시 이메일로 발송

**권고 사항**:
```python
# src/dal.py:31 수정
ConsistentRead=True  # Eventual → Strong consistency
```

**트레이드오프**:
- 비용: Read Capacity Unit 2배 (하지만 PAY_PER_REQUEST 모드에서는 동일 요금)
- 레이턴시: ~5-10ms 증가 (무시 가능)

**우선순위**: P0 (데이터 정합성)

---

## 🟠 High Priority (P1)

### F-04: DynamoDB BatchWriteItem UnprocessedItems 재시도 없음

**위치**: `src/dal.py:62`

**발견 내용**:
```python
def mark_seen(self, items: Sequence[PaperItem]) -> None:
    for chunk in chunks:
        response = self._client.batch_write_item(RequestItems={self.table_name: chunk})
        unprocessed = response.get("UnprocessedItems", {})
        if unprocessed:
            LOGGER.warning("Some DynamoDB items were unprocessed: %s", unprocessed)
            # ⚠️ 재시도 없음, 그냥 경고만 로깅
```

**문제점**:
- DynamoDB throttling이나 일시적 오류 시 일부 항목이 저장 안 될 수 있음
- 저장 실패한 논문은 다음 실행 시 다시 이메일 발송됨 (중복)

**영향도**: **High**
- 데이터 손실 가능성
- Batch 크기가 클수록 발생 확률 증가

**재현 단계**:
1. 25개 이상의 신규 논문 발견
2. DynamoDB에 일시적 throttling 발생 (WCU 초과 등)
3. UnprocessedItems 발생하지만 재시도 없음

**권고 사항**:
```python
import time

def mark_seen(self, items: Sequence[PaperItem]) -> None:
    # ... chunk 생성 ...
    for chunk in chunks:
        backoff = 0.1
        remaining = chunk
        for attempt in range(5):
            response = self._client.batch_write_item(
                RequestItems={self.table_name: remaining}
            )
            unprocessed = response.get("UnprocessedItems", {}).get(self.table_name, [])
            if not unprocessed:
                break
            LOGGER.warning("Retry %d: %d unprocessed items", attempt + 1, len(unprocessed))
            remaining = unprocessed
            time.sleep(backoff)
            backoff *= 2
        else:
            raise RuntimeError(f"Failed to write {len(remaining)} items after 5 attempts")
```

**우선순위**: P1 (데이터 신뢰성)

---

### F-05: HTTP 타임아웃과 Lambda 타임아웃 불균형

**위치**:
- `template.yaml:16` (Lambda Timeout: 60s)
- `src/sources/crossref.py:17` (DEFAULT_TIMEOUT = 10)
- `src/sources/pubmed.py:17` (DEFAULT_TIMEOUT = 10)
- `src/sources/rss.py:23` (DEFAULT_TIMEOUT = 10)

**발견 내용**:
- 3개 소스를 순차 호출, 각 소스당 최대 5회 리트라이
- 최악의 경우: 3 sources × 5 retries × 10s = 150초 > 60초 Lambda timeout

**문제점**:
- Lambda timeout으로 인한 불완전한 실행
- 일부 소스만 처리하고 종료 가능

**영향도**: **Medium**
- 네트워크 불안정 시 서비스 중단 가능성

**재현 단계**:
1. Crossref API가 9초씩 응답하도록 시뮬레이션 (network delay)
2. Tenacity 리트라이 5회 → 45초 소모
3. PubMed도 유사하게 지연 → 총 90초
4. Lambda timeout 발생

**권고 사항**:
```yaml
# template.yaml:16 수정
Timeout: 180  # 60 → 180초
```

```python
# src/sources/*.py 수정
DEFAULT_TIMEOUT = 20  # 10 → 20초 (여유 확보)

# tenacity 설정 조정
@retry(
    stop=stop_after_attempt(3),  # 5 → 3회로 감소
    wait=wait_exponential(multiplier=1, min=1, max=10),  # max 60 → 10
)
```

**우선순위**: P1 (안정성)

---

### F-06: 예외 처리가 너무 광범위

**위치**:
- `src/handler.py:29` - `except Exception as exc: # noqa: BLE001`
- `src/handler.py:182` - `except Exception: # noqa: BLE001`

**발견 내용**:
```python
try:
    base_config = get_config()
except Exception as exc:  # noqa: BLE001 - Blind exception
    LOGGER.error("Configuration error: %s", exc)
    raise
```

**문제점**:
- `Exception` catch는 `KeyboardInterrupt`, `SystemExit` 등도 포함 (Python 3.x에서는 제외되지만 나쁜 관행)
- `BLE001` flake8 경고를 `noqa`로 억제 → 코드 품질 저하

**영향도**: **Low**
- 현재는 즉시 `raise`하므로 실질적 문제는 적음
- 하지만 향후 수정 시 버그 유입 가능성

**권고 사항**:
```python
# 구체적인 예외만 catch
try:
    base_config = get_config()
except (ValueError, ClientError, BotoCoreError) as exc:
    LOGGER.error("Configuration error: %s", exc)
    raise
```

**우선순위**: P1 (코드 품질)

---

### F-07: API 키 로그 노출 위험

**위치**: `src/sources/crossref.py:168`, `pubmed.py:93`

**발견 내용**:
```python
# crossref.py
safe_url = response.url
if safe_url and contact_email:
    safe_url = safe_url.replace(contact_email, "***")
LOGGER.info("... url=%s", safe_url)  # ⚠️ api_key는 마스킹 안 됨
```

```python
# pubmed.py
if api_key:
    params_base["api_key"] = api_key
# ... 이후 params를 로깅 시 api_key 평문 노출 가능
```

**문제점**:
- PubMed API 키가 CloudWatch Logs에 평문 저장 가능
- Crossref는 mailto 마스킹하지만 PubMed는 미흡

**영향도**: **Medium**
- CloudWatch Logs 접근 권한 있는 사람이 API 키 탈취 가능

**재현 단계**:
1. PubMed API 키 설정
2. Lambda 실행 후 CloudWatch Logs 검색: `api_key=`
3. API 키 평문 노출 확인

**권고 사항**:
```python
# src/sources/pubmed.py에 마스킹 함수 추가
def _mask_params(params: Dict[str, str]) -> Dict[str, str]:
    masked = params.copy()
    if "api_key" in masked:
        masked["api_key"] = "***"
    return masked

# 로깅 전 마스킹
LOGGER.info("Request params: %s", _mask_params(params))
```

**우선순위**: P1 (보안)

---

### F-08: HTML 태그 제거 로직 취약

**위치**: `src/sources/crossref.py:80-91`

**발견 내용**:
```python
def _strip_tags(raw: str) -> str:
    text = []
    in_tag = False
    for char in raw:
        if char == "<":
            in_tag = True
            continue
        if char == ">":
            in_tag = False
            continue
        if not in_tag:
            text.append(char)
    return "".join(text)
```

**문제점**:
- 중첩 태그 처리 안 됨: `<div><span>text</span></div>` → `<span>text` (잘못된 결과)
- `<` 또는 `>` 문자가 콘텐츠에 포함된 경우 오동작
- 이메일은 텍스트 전용이므로 XSS 위험은 없지만, 데이터 품질 저하

**영향도**: **Medium**
- 초록 텍스트 손상 가능성

**권고 사항**:
```python
# html.parser 사용 (표준 라이브러리)
from html.parser import HTMLParser

class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []

    def handle_data(self, data):
        self.text.append(data)

    def get_text(self):
        return "".join(self.text)

def _strip_tags(raw: str) -> str:
    stripper = HTMLStripper()
    stripper.feed(raw)
    return stripper.get_text()
```

**우선순위**: P1 (데이터 품질)

---

### F-12: 테스트 부재

**위치**: `tests/` 디렉토리 (빈 상태)

**발견 내용**:
- 단위 테스트, 통합 테스트 전무
- 리팩토링이나 수정 시 회귀 위험 높음

**영향도**: **Medium**
- 코드 변경 시 신뢰도 낮음
- CI/CD 파이프라인 구축 불가

**권고 사항**:
1. **단위 테스트 추가**:
   - `test_util.py` - 키워드 파싱, 하이라이팅 로직
   - `test_filtering.py` - keyword_match() 로직
   - `test_config.py` - 환경변수 검증 로직

2. **통합 테스트 추가**:
   - `test_handler.py` - Lambda handler 전체 흐름 (mock 사용)

3. **pytest + moto + pytest-mock 사용**:
```bash
pip install pytest moto pytest-mock
```

```python
# tests/test_util.py 예시
from src.util import parse_keywords

def test_parse_keywords_single():
    assert parse_keywords("covid") == ["covid"]

def test_parse_keywords_multiple():
    assert parse_keywords("covid, vaccine") == ["covid", "vaccine"]

def test_parse_keywords_empty():
    assert parse_keywords("") == []
```

**우선순위**: P1 (장기 유지보수)

---

## 🟢 Medium/Low Priority (P2)

### F-09: Dead Letter Queue 없음

**위치**: `template.yaml` (Lambda 설정)

**발견 내용**:
- Lambda 실패 시 재처리 메커니즘 없음
- EventBridge도 `MaximumRetryAttempts: 0`

**영향도**: **Medium**
- 일시적 오류로 실행 실패 시 해당 일자 논문 영구 손실

**권고 사항**:
```yaml
# template.yaml에 DLQ 추가
Resources:
  PaperWatcherDLQ:
    Type: AWS::SQS::Queue
    Properties:
      QueueName: paper-watcher-dlq
      MessageRetentionPeriod: 1209600  # 14일

  PaperWatcherFunction:
    Type: AWS::Serverless::Function
    Properties:
      DeadLetterQueue:
        Type: SQS
        TargetArn: !GetAtt PaperWatcherDLQ.Arn
      # ...

    Events:
      DailySchedule:
        Properties:
          RetryPolicy:
            MaximumRetryAttempts: 2  # 0 → 2
```

**우선순위**: P2 (운영 안정성)

---

### F-10: 의존성 버전 고정 안 됨

**위치**: `requirements.txt`

**발견 내용**:
```
requests          # 버전 미지정
feedparser        # 버전 미지정
tenacity          # 버전 미지정
PyYAML>=6.0,<7    # 범위 지정
```

**문제점**:
- 재현성 낮음 (다른 환경에서 다른 버전 설치 가능)
- 의존성 업데이트 시 예상치 못한 breaking change 발생 가능

**권고 사항**:
```bash
# 현재 환경의 버전 고정
pip freeze > requirements.txt

# 또는 poetry/pipenv 사용
poetry init
poetry add requests feedparser tenacity pyyaml
poetry export -f requirements.txt -o requirements.txt
```

**예시**:
```
requests==2.31.0
feedparser==6.0.10
tenacity==8.2.3
PyYAML==6.0.1
boto3==1.34.0  # Lambda 런타임 버전과 일치시키기
```

**우선순위**: P2 (재현성)

---

### F-11: 리트라이 로직 중복

**위치**: `src/sources/crossref.py`, `pubmed.py`, `rss.py`

**발견 내용**:
- 각 소스마다 동일한 `@retry` 데코레이터 반복

**권고 사항**:
```python
# src/util.py에 공통 리트라이 함수 추가
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests

def api_retry():
    return retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )

# 각 소스에서 사용
from util import api_retry

@api_retry()
def _perform_request(...):
    ...
```

**우선순위**: P2 (코드 중복 제거)

---

### F-13: 메트릭 및 추적 부재

**위치**: 전역 (관측성)

**발견 내용**:
- CloudWatch Metrics 커스텀 메트릭 없음
- AWS X-Ray 추적 없음
- 운영 가시성 낮음

**권고 사항**:
```python
# src/handler.py에 메트릭 추가
import boto3
cloudwatch = boto3.client("cloudwatch")

def _publish_metrics(source: str, count: int):
    cloudwatch.put_metric_data(
        Namespace="PaperWatcher",
        MetricData=[
            {
                "MetricName": "PapersFound",
                "Dimensions": [{"Name": "Source", "Value": source}],
                "Value": count,
                "Unit": "Count",
            }
        ],
    )
```

```yaml
# template.yaml에 X-Ray 추가
  PaperWatcherFunction:
    Properties:
      Tracing: Active  # X-Ray 활성화
```

**우선순위**: P2 (관측성)

---

### F-14: EventBridge 재시도 없음

**위치**: `template.yaml:70`

**발견 내용**:
```yaml
RetryPolicy:
  MaximumRetryAttempts: 0  # 재시도 없음
```

**권고 사항**:
```yaml
RetryPolicy:
  MaximumRetryAttempts: 2
  MaximumEventAgeInSeconds: 3600
```

**우선순위**: P2 (안정성)

---

### F-15: 이메일 발송 실패 시 DDB 롤백 없음

**위치**: `src/handler.py:141-147`

**발견 내용**:
```python
# DynamoDB 업데이트
repository.mark_seen(flat_items)

# 이메일 발송 (실패 가능)
send_email(...)  # ⚠️ 실패 시 이미 "seen" 마킹됨
```

**문제점**:
- 이메일 발송 실패 → DDB는 이미 업데이트 → 해당 논문 영구 손실

**권고 사항**:
```python
# 순서 변경: 이메일 먼저, DDB 나중
send_email(...)  # 먼저 실행
repository.mark_seen(flat_items)  # 성공 후 마킹
```

**트레이드오프**:
- 이메일 발송 성공 후 DDB 실패 시 다음 실행에서 중복 발송
- 하지만 "논문 손실"보다는 "중복 발송"이 나음

**우선순위**: P2 (데이터 보존)

---

## Quick Wins 우선순위 요약

| 순위 | ID | 작업 | 예상 시간 | ROI |
|------|-----|------|-----------|-----|
| 1 | F-01 | `runtime.py:58` 키워드 하드코딩 제거 | 5분 | ⭐⭐⭐⭐⭐ |
| 2 | F-03 | `dal.py:31` ConsistentRead=True | 2분 | ⭐⭐⭐⭐⭐ |
| 3 | F-10 | requirements.txt 버전 고정 | 10분 | ⭐⭐⭐⭐ |
| 4 | F-05 | Lambda timeout 180초로 증가 | 2분 | ⭐⭐⭐⭐ |
| 5 | F-02 | Secrets Manager 캐싱 추가 | 30분 | ⭐⭐⭐⭐ |
| 6 | F-04 | BatchWriteItem 재시도 로직 | 30분 | ⭐⭐⭐ |
| 7 | F-07 | API 키 로깅 마스킹 | 15분 | ⭐⭐⭐ |
| 8 | F-08 | HTML 파싱을 html.parser로 교체 | 20분 | ⭐⭐⭐ |
| 9 | F-09 | Dead Letter Queue 추가 | 20분 | ⭐⭐⭐ |
| 10 | F-14 | EventBridge 재시도 정책 | 2분 | ⭐⭐⭐ |

**총 예상 시간**: ~2.5시간
**누적 개선 효과**: 중복 발송 방지 + 비용 절감 + 안정성 향상

---

## 추가 개선 제안 (장기)

### 아키텍처 개선
1. **Step Functions 도입**: 소스별 병렬 처리 + 에러 핸들링
2. **S3 기반 키워드 관리**: 동적 키워드 업데이트
3. **SQS를 통한 비동기 처리**: 이메일 발송 분리

### 운영 개선
1. **CloudWatch 대시보드**: 실시간 모니터링
2. **알람 설정**: 연속 실패 알림
3. **Cost Explorer 통합**: 비용 추적

### 코드 품질
1. **타입 힌트 개선**: mypy strict 모드
2. **Linting 강화**: ruff, black 도입
3. **Pre-commit hooks**: 자동 코드 품질 검사

---

**작성일**: 2025-01-27
**대상 리포지토리**: https://github.com/jijae92/demoSES
**리뷰어**: Senior Python/Serverless Reviewer
