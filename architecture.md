# demoSES Architecture Review

## 1. 리포지토리 구조 매핑

```
demoSES/
├── template.yaml              # AWS SAM IaC 정의
├── samconfig.toml            # SAM 배포 설정
├── requirements.txt          # 루트 의존성 (빌드용)
├── .env.example             # 로컬 실행 환경변수 예제
├── event.json / event-wide.json  # Lambda 테스트 이벤트
│
├── src/                      # Lambda 함수 코드 (CodeUri)
│   ├── handler.py           # Lambda 진입점 (lambda_handler)
│   ├── config.py            # 환경변수 및 Secrets Manager 통합
│   ├── dal.py               # DynamoDB 접근 계층
│   ├── mailer.py            # SES API/SMTP 이메일 전송
│   ├── util.py              # 공통 유틸리티 (PaperItem, 키워드 파싱 등)
│   ├── runtime.py           # 런타임 파라미터 오버라이드 처리
│   ├── requirements.txt     # Lambda 레이어 의존성
│   │
│   ├── pipeline/
│   │   └── filtering.py     # 키워드 매칭 및 중복 제거 로직
│   │
│   └── sources/             # 외부 API 클라이언트
│       ├── crossref.py      # Crossref REST API (Nature/Cell/Science)
│       ├── pubmed.py        # PubMed E-utilities (esearch + efetch)
│       └── rss.py           # RSS 피드 fallback (feedparser)
│
├── config/
│   └── keywords.yml         # (사용되지 않음, 레거시)
│
├── backend/search/          # (미사용, 레거시)
├── tests/                   # (빈 디렉토리, 테스트 파일 없음)
└── vendor/                  # (외부 라이브러리, 정확한 용도 불명)
```

## 2. 진입점 및 실행 흐름

### 2.1 Lambda Handler (`src/handler.py:lambda_handler`)

```python
def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
```

**실행 순서:**

1. **설정 로드** (`config.get_config()`)
   - 환경변수 파싱
   - Secrets Manager에서 SES/API 시크릿 조회

2. **런타임 옵션 병합** (`runtime.derive_runtime_options()`)
   - 이벤트 페이로드에서 오버라이드 추출
   - **주의**: `runtime.py:58`에서 하드코딩된 `FIXED_KEYWORDS` 강제 적용

3. **소스별 데이터 수집** (`_fetch_sources()`)
   - `crossref.fetch_crossref()` - Crossref REST API
   - `pubmed.fetch_pubmed()` - PubMed E-utilities (esearch → efetch)
   - `rss.fetch_rss()` - 피드파서로 RSS 파싱

4. **필터링 파이프라인** (`pipeline.filtering.filter_items()`)
   - 키워드 매칭 (AND/OR 모드)
   - 중복 제거 (paper_id 기준)

5. **신규 아이템 확인** (`dal.SeenRepository.is_seen()`)
   - DynamoDB GetItem으로 기존 발송 여부 확인

6. **DynamoDB 업데이트** (`dal.SeenRepository.mark_seen()`)
   - BatchWriteItem으로 신규 아이템 기록

7. **이메일 발송** (`mailer.send_email()`)
   - SES API (기본) 또는 SMTP (USE_SMTP=true)

### 2.2 주요 모듈 상세

#### `src/config.py`
- **클래스**: `ConfigLoader`, `AppConfig`, `SesSecrets`, `ApiSecrets`
- **역할**: 환경변수 검증 및 Secrets Manager 통합
- **문제점**:
  - Secrets Manager 캐싱 없음 (매 호출마다 API 요청)
  - 시크릿 조회 실패 시 Lambda 전체 실패

#### `src/dal.py`
- **클래스**: `SeenRepository`
- **역할**: DynamoDB paper_seen 테이블 CRUD
- **문제점**:
  - `is_seen()`에서 `ConsistentRead=False` → eventual consistency로 중복 발송 가능
  - `mark_seen()`에서 UnprocessedItems 재시도 없음

#### `src/mailer.py`
- **함수**: `send_email()`, `_send_via_ses_api()`, `_send_via_smtp()`
- **역할**: 이메일 본문 렌더링 및 SES/SMTP 전송
- **문제점**:
  - 한국어 하드코딩 (국제화 불가)
  - HTML 이메일 미지원 (텍스트 전용)

#### `src/runtime.py`
- **함수**: `derive_runtime_options()`
- **역할**: 이벤트 페이로드에서 파라미터 오버라이드
- **치명적 문제**:
  - 라인 58: `keywords = FIXED_KEYWORDS` - 사용자 입력 무시하고 하드코딩 강제

#### `src/sources/*.py`
- **Crossref**:
  - API: `https://api.crossref.org/works`
  - 레이트 리미트: 429 응답 처리 (tenacity 리트라이)
  - 필터: container-title, from-pub-date, until-pub-date
- **PubMed**:
  - API: E-utilities (esearch → efetch)
  - 레이트 리미트: API 키 있으면 0.11초, 없으면 0.34초 sleep
  - XML 파싱: ElementTree
- **RSS**:
  - 피드: Nature/Cell/Science 공식 RSS
  - 파서: feedparser
  - HTML 태그 제거: 정규식 (취약)

#### `src/pipeline/filtering.py`
- **함수**: `filter_items()`, `keyword_match()`
- **역할**: 후처리 키워드 매칭 및 중복 제거
- **로직**:
  1. HTML 태그 제거
  2. 소문자 변환 및 구두점 제거
  3. 키워드 정규화 (따옴표 처리)
  4. AND/OR 매칭
  5. paper_id 기준 중복 제거
  6. 매칭 키워드로 하이라이팅 ([keyword])

## 3. 런타임 및 배포 설정

### 3.1 AWS SAM 템플릿 (`template.yaml`)

| 리소스 | 타입 | 속성 |
|--------|------|------|
| **PaperWatcherFunction** | AWS::Serverless::Function | Runtime: python3.11<br/>Handler: handler.lambda_handler<br/>Timeout: 60초<br/>Memory: 512MB<br/>Arch: x86_64 |
| **PaperSeenTable** | AWS::DynamoDB::Table | BillingMode: PAY_PER_REQUEST<br/>KeySchema: paper_id (HASH) |
| **DailySchedule** | EventBridge Schedule | cron(0 9 * * ? *) UTC<br/>RetryPolicy: MaxRetry=0 |

**IAM 정책:**
- `AWSLambdaBasicExecutionRole` (CloudWatch Logs)
- DynamoDB: GetItem, PutItem, BatchWriteItem
- Secrets Manager: GetSecretValue (2개 시크릿)
- SES: SendEmail, SendRawEmail (리소스: "*")

### 3.2 환경변수 (Globals.Function.Environment.Variables)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `KEYWORDS` | "parp, isg, interferon, sting" | 키워드 목록 (CSV) |
| `MATCH_MODE` | "OR" | AND/OR 매칭 모드 |
| `WINDOW_HOURS` | "24" | 검색 시간 윈도우 |
| `SOURCES` | "crossref,pubmed,rss" | 활성화된 소스 |
| `APP_NAME` | "paper-watcher" | User-Agent 접두사 |
| `DDB_TABLE` | !Ref TableName | DynamoDB 테이블명 |
| `SES_SECRET_NAME` | !Ref SesSecretName | SES 시크릿 ARN |
| `API_SECRET_NAME` | !Ref ApiSecretName | API 시크릿 ARN |
| `USE_SMTP` | !Ref UseSmtp | SMTP 사용 여부 (true/false) |

### 3.3 Secrets Manager 시크릿 구조

#### `paperwatcher/ses` (SES 설정)
```json
{
  "sender": "alerts@example.com",          // 필수
  "recipients": ["user@example.com"],      // 필수
  "region": "ap-northeast-2",              // 필수
  "reply_to": ["noreply@example.com"],     // 선택
  "subject_prefix": "[PaperWatcher]",      // 선택
  "smtp_user": "AKIAIOSFODNN7EXAMPLE",     // SMTP 전용
  "smtp_pass": "wJalrXUtnFEMI/...",        // SMTP 전용
  "host": "email-smtp.ap-northeast-2.amazonaws.com", // SMTP 전용
  "port": 587                               // SMTP 전용
}
```

#### `paperwatcher/api` (API 설정)
```json
{
  "pubmed_api_key": "abcd1234",            // 선택
  "user_agent_email": "you@example.com"    // 선택 (Crossref polite pool)
}
```

### 3.4 배포 경로 (SAM)

```bash
# 빌드
sam build

# 배포 (대화형)
sam deploy --guided

# 배포 (samconfig.toml 사용)
sam deploy
```

**samconfig.toml 설정:**
- Region: `ap-northeast-2`
- Stack: `PaperWatcherStack`
- S3 버킷: 자동 생성 (resolve_s3=true)
- IAM Capability: `CAPABILITY_IAM`
- Rollback 비활성화: `disable_rollback=true`

### 3.5 EventBridge 스케줄

| 속성 | 값 |
|------|-----|
| 표현식 | `cron(0 9 * * ? *)` |
| 설명 | 매일 09:00 UTC (한국 18:00 KST) |
| 재시도 | 0회 (실패 시 재시도 없음) |

## 4. 아키텍처 다이어그램

```
┌─────────────────┐
│ EventBridge     │
│ Schedule        │  cron(0 9 * * ? *)
│ (daily 09:00)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ Lambda: PaperWatcherFunction                       │
│ ┌─────────────────────────────────────────────┐   │
│ │ handler.lambda_handler()                     │   │
│ │  1. Load config from Secrets Manager        │   │
│ │  2. Fetch from Crossref/PubMed/RSS          │   │
│ │  3. Filter by keywords (AND/OR)             │   │
│ │  4. Deduplicate by paper_id                 │   │
│ │  5. Check DynamoDB for seen items           │   │
│ │  6. Mark new items as seen                  │   │
│ │  7. Send SES email                          │   │
│ └─────────────────────────────────────────────┘   │
└───┬──────────┬──────────┬──────────┬──────────────┘
    │          │          │          │
    ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────────────┐
│Crossref│ │PubMed  │ │  RSS   │ │ Secrets Manager│
│  API   │ │E-utils │ │ Feeds  │ │ - SES secrets  │
└────────┘ └────────┘ └────────┘ │ - API secrets  │
                                  └────────────────┘
    │          │          │
    ▼          ▼          ▼
┌─────────────────────────────────┐
│ DynamoDB: paper_seen            │
│ - paper_id (PK)                 │
│ - source, title, created_at     │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│ Amazon SES                      │
│ - SendEmail API (default)       │
│ - SMTP (if USE_SMTP=true)       │
└─────────────────────────────────┘
```

## 5. 데이터 흐름

### 5.1 Happy Path (신규 논문 발견 시)

```
EventBridge → Lambda.handler.lambda_handler()
  → config.get_config()
    → boto3.client("secretsmanager").get_secret_value(SES_SECRET_NAME)
    → boto3.client("secretsmanager").get_secret_value(API_SECRET_NAME)
  → runtime.derive_runtime_options(config, event)
    → FORCED override: keywords = FIXED_KEYWORDS
  → _fetch_sources()
    → crossref.fetch_crossref() [Nature, Cell, Science]
      → requests.get(CROSSREF_URL) with filters
      → keyword_match() per result
    → pubmed.fetch_pubmed()
      → requests.get(ESEARCH_URL) → ID list
      → requests.get(EFETCH_URL) → XML parsing
      → keyword_match() per article
    → rss.fetch_rss() [Nature, Cell, Science RSS]
      → feedparser.parse()
      → keyword_match() per entry
  → filtering.filter_items()
    → Deduplicate by paper_id
    → Highlight matched keywords
  → _filter_seen_items()
    → dal.SeenRepository.is_seen(paper_id)
      → dynamodb.get_item(ConsistentRead=False)  ⚠️
  → dal.SeenRepository.mark_seen(new_items)
    → dynamodb.batch_write_item() chunks of 25
  → mailer.send_email()
    → _render_body() (Korean text)
    → _send_via_ses_api() OR _send_via_smtp()
      → boto3.client("ses").send_email()
```

### 5.2 Error Paths

| 에러 타입 | 처리 방식 | 영향 |
|-----------|-----------|------|
| Secrets Manager 실패 | Lambda 즉시 종료 (raise) | 전체 실행 중단 |
| 소스 API 실패 | 개별 소스 스킵 (continue) | 다른 소스는 계속 |
| DynamoDB GetItem 실패 | 예외 전파 (raise) | 전체 실행 중단 |
| DynamoDB BatchWriteItem 실패 | 예외 전파 (raise) | 이메일 발송 전 중단 |
| SES/SMTP 전송 실패 | EmailDeliveryError (raise) | 전체 실행 중단 (하지만 DDB는 이미 업데이트됨) ⚠️ |

## 6. 주요 설계 결정 및 트레이드오프

### 6.1 긍정적 측면

✅ **서버리스 아키텍처**: 관리 오버헤드 최소화, 자동 스케일링
✅ **멀티 소스 전략**: Crossref + PubMed + RSS로 coverage 향상
✅ **Secrets Manager 사용**: 시크릿이 코드/환경변수에 노출되지 않음
✅ **Tenacity 리트라이**: 일시적 네트워크 오류 복원력
✅ **DynamoDB 중복 방지**: 동일 논문 재발송 방지
✅ **SAM IaC**: 인프라 재현 가능

### 6.2 문제점 및 리스크

❌ **하드코딩된 키워드** (`runtime.py:58`): 사용자 설정 무시, 유연성 제로
❌ **Secrets 캐싱 없음**: 매 Lambda 호출마다 2번의 GetSecretValue API 호출 (비용 + 레이턴시)
❌ **Eventual Consistency**: `ConsistentRead=False` → 중복 이메일 가능
❌ **원자성 위반**: DDB 업데이트 후 이메일 실패 시 복구 불가 (이미 "seen" 마킹됨)
❌ **테스트 부재**: `tests/` 디렉토리 빈 상태
❌ **하드코딩된 타임아웃**: 10초 HTTP 타임아웃 vs 60초 Lambda 타임아웃 불균형
❌ **Dead Letter Queue 없음**: 실패 시 재처리 불가
❌ **메트릭 부재**: CloudWatch Metrics/X-Ray 통합 없음

## 7. 기술 스택

| 계층 | 기술 |
|------|------|
| **런타임** | Python 3.11 (x86_64) |
| **IaC** | AWS SAM (CloudFormation) |
| **컴퓨팅** | AWS Lambda (512MB, 60초 timeout) |
| **스토리지** | DynamoDB (PAY_PER_REQUEST) |
| **스케줄러** | EventBridge (cron) |
| **이메일** | Amazon SES (API/SMTP) |
| **시크릿** | AWS Secrets Manager |
| **HTTP 클라이언트** | requests |
| **XML 파싱** | xml.etree.ElementTree |
| **RSS 파싱** | feedparser |
| **리트라이** | tenacity |
| **설정 관리** | PyYAML (사용되지 않음) |

## 8. 의존성 분석

### 루트 `requirements.txt`
```
requests          # HTTP 클라이언트
feedparser        # RSS 파서
tenacity          # 리트라이 데코레이터
PyYAML>=6.0,<7    # (사용되지 않음)
```

### `src/requirements.txt`
```
boto3>=1.33.0     # AWS SDK
```

**문제점:**
- 대부분 의존성이 버전 고정 안 됨 → 재현성 낮음
- boto3는 Lambda 런타임에 포함되어 있으므로 불필요 (단, 특정 버전 필요 시 예외)

## 9. 보안 모델

### 9.1 IAM 권한

```yaml
Policies:
  - AWSLambdaBasicExecutionRole  # CloudWatch Logs
  - DynamoDB:
      Actions: [GetItem, PutItem, BatchWriteItem]
      Resource: !GetAtt PaperSeenTable.Arn
  - SecretsManager:
      Actions: [GetSecretValue]
      Resource:
        - arn:aws:secretsmanager:*:*:secret:paperwatcher/ses*
        - arn:aws:secretsmanager:*:*:secret:paperwatcher/api*
  - SES:
      Actions: [SendEmail, SendRawEmail]
      Resource: "*"  # ⚠️ 과도한 권한
```

**보안 이슈:**
- SES 권한이 `Resource: "*"` → 최소 권한 원칙 위배
- 시크릿 ARN에 와일드카드 사용 → 다른 시크릿도 접근 가능

### 9.2 데이터 보호

✅ **전송 중**: HTTPS (Crossref/PubMed/RSS), TLS (SES/SMTP)
✅ **저장 중**: Secrets Manager 암호화 (KMS), DynamoDB 기본 암호화
⚠️ **로그**: CloudWatch Logs에 타이틀/요약 평문 저장 (민감 정보 아니지만 주의)

### 9.3 입력 검증

✅ **이메일 헤더 인젝션 방지**: `util.sanitize_header()` CR/LF 체크
⚠️ **환경변수 검증 미흡**: `WINDOW_HOURS` 음수 체크는 있으나, 상한선 없음
⚠️ **HTML 태그 제거 취약**: 정규식 기반 → XSS 방어 불충분 (이메일은 텍스트 전용이므로 낮은 위험)

## 10. 운영 고려사항

### 10.1 모니터링

**현재 상태:**
- CloudWatch Logs: 기본 로깅 (INFO 레벨)
- 메트릭: Lambda 기본 메트릭만 (Invocations, Errors, Duration)

**부족한 부분:**
- 커스텀 메트릭 없음 (논문 발견 수, 소스별 성공률 등)
- X-Ray 추적 없음
- 알람 없음

### 10.2 비용 추정

| 서비스 | 사용량 (월) | 예상 비용 |
|--------|-------------|-----------|
| Lambda | 30 invocations × 60s × 512MB | 무료 티어 내 |
| DynamoDB | ~100 read/write per day | $0.05 |
| Secrets Manager | 2 secrets × 60 retrievals | $0.80 |
| SES | 100 emails | $0.01 |
| **총계** | | **~$0.86/month** |

**최적화 제안:**
- Secrets Manager 캐싱 → $0.70 절감

### 10.3 확장성

| 차원 | 현재 한계 | 확장 전략 |
|------|-----------|-----------|
| **논문 수** | Lambda 60초 timeout | Step Functions로 병렬 처리 |
| **키워드 수** | 메모리 내 처리 | S3 기반 키워드 관리 |
| **수신자 수** | SES 최대 50명/이메일 | SES SendBulkEmail 또는 SNS 팬아웃 |
| **빈도** | 일 1회 | EventBridge 스케줄 조정 |

## 11. 레거시 및 미사용 코드

| 경로 | 상태 | 조치 필요 |
|------|------|-----------|
| `config/keywords.yml` | 사용되지 않음 | 삭제 권장 |
| `backend/search/` | 사용되지 않음 | 삭제 권장 |
| `tests/` | 빈 디렉토리 | 테스트 작성 또는 삭제 |
| `vendor/` | 용도 불명 | 조사 후 정리 |
| `.env.example` | 로컬 실행용 (Lambda에서 미사용) | 문서화 개선 |

---

**작성일**: 2025-01-27
**대상 리포지토리**: https://github.com/jijae92/demoSES
**리뷰어**: Senior Python/Serverless Reviewer
