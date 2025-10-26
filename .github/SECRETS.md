# GitHub Secrets 설정 가이드

GitHub Actions에서 Paper Watcher를 실행하려면 다음 Secrets를 설정해야 합니다.

## 설정 위치

Repository → Settings → Secrets and variables → Actions → New repository secret

---

## 필수 Secrets

### EMAIL_FROM
- **설명**: 발신 이메일 주소
- **예시**: `alerts@your-domain.com`
- **필수**: ✅
- **주의**: SES에서 검증된 이메일 주소여야 함

### EMAIL_TO
- **설명**: 수신 이메일 주소
- **예시**: `recipient@example.com`
- **필수**: ✅
- **주의**: 여러 수신자는 콤마로 구분 (현재 워크플로우는 1명만 지원, config.yaml에서 여러 명 설정 가능)

### AWS_REGION
- **설명**: AWS 리전
- **예시**: `ap-northeast-2` (서울), `us-east-1` (버지니아)
- **필수**: ✅

### AWS_ACCESS_KEY_ID
- **설명**: AWS Access Key ID
- **예시**: `AKIAIOSFODNN7EXAMPLE`
- **필수**: ✅
- **생성 방법**: AWS Console → IAM → Users → Security credentials → Access keys

### AWS_SECRET_ACCESS_KEY
- **설명**: AWS Secret Access Key
- **예시**: `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`
- **필수**: ✅
- **주의**: 절대 공개하지 마세요!

---

## 선택 Secrets

### BING_API_KEY
- **설명**: Bing Web Search API 키
- **예시**: `abc123def456...`
- **필수**: ❌ (provider=bing 사용 시 필요)
- **발급**: https://www.microsoft.com/en-us/bing/apis/bing-web-search-api
- **무료 티어**: 1,000 트랜잭션/월

### SMTP_HOST
- **설명**: SMTP 서버 주소
- **예시**: `smtp.gmail.com`, `email-smtp.ap-northeast-2.amazonaws.com`
- **필수**: ❌ (SMTP fallback 사용 시 필요)

### SMTP_PORT
- **설명**: SMTP 포트
- **예시**: `587` (TLS), `465` (SSL)
- **필수**: ❌

### SMTP_USER
- **설명**: SMTP 사용자명
- **예시**: `your_email@gmail.com`
- **필수**: ❌

### SMTP_PASSWORD
- **설명**: SMTP 비밀번호 또는 앱 비밀번호
- **예시**: Gmail 앱 비밀번호
- **필수**: ❌
- **주의**: Gmail의 경우 2단계 인증 활성화 후 앱 비밀번호 생성 필요

---

## AWS IAM 권한 설정

GitHub Actions에서 사용할 IAM 사용자에게 다음 권한을 부여해야 합니다:

### SES 권한 (필수)

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

### 권한 설정 방법

1. AWS Console → IAM → Users
2. 사용자 선택 → Permissions 탭
3. Add permissions → Attach policies directly
4. "Create policy" 클릭
5. JSON 탭에서 위의 정책 붙여넣기
6. 정책 이름: `PaperWatcherSESAccess`
7. Create policy → 사용자에게 연결

---

## AWS SES 설정

### 1. 이메일 주소 검증

1. AWS Console → Amazon SES → Verified identities
2. Create identity
3. Email address 선택
4. 이메일 주소 입력 (EMAIL_FROM)
5. 검증 이메일 확인 및 링크 클릭

### 2. Production Access 신청 (선택)

Sandbox 모드에서는 검증된 이메일로만 발송 가능합니다.

Production access 신청:
1. AWS Console → Amazon SES → Account dashboard
2. "Request production access" 클릭
3. Use case 설명 작성
4. 승인 대기 (보통 24시간 이내)

---

## 테스트

Secrets 설정 후 수동으로 워크플로우 실행:

1. Repository → Actions
2. "Daily Paper Watcher" 선택
3. "Run workflow" 클릭
4. **Dry run** 체크박스 활성화
5. Run workflow

로그를 확인하여 설정이 올바른지 확인하세요.

---

## 보안 모범 사례

1. ✅ 최소 권한 원칙: IAM 사용자에게 필요한 최소 권한만 부여
2. ✅ 키 로테이션: 정기적으로 Access Key 변경
3. ✅ MFA 활성화: IAM 사용자에 MFA 설정
4. ✅ 모니터링: CloudTrail로 API 호출 추적
5. ❌ 코드에 직접 포함 금지: 절대 credentials를 코드에 커밋하지 마세요
6. ❌ Public 로그: Secrets는 자동으로 마스킹되지만 로그 확인 필요

---

## 문제 해결

### 워크플로우가 실행되지 않음
- Repository Settings → Actions → General → "Allow all actions" 확인

### SES 발송 실패: "Email address is not verified"
- SES → Verified identities에서 이메일 검증 상태 확인

### SES 발송 실패: "Access Denied"
- IAM 사용자의 SES 권한 확인
- AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY 확인

### 모든 소스가 403 에러
- HTTP provider는 일부 사이트에서 봇 차단
- `--provider bing` 사용 권장 (BING_API_KEY 필요)

---

## 참고 자료

- [AWS SES 문서](https://docs.aws.amazon.com/ses/)
- [GitHub Actions Secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Bing Web Search API](https://www.microsoft.com/en-us/bing/apis/bing-web-search-api)
