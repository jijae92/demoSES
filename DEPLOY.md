# Lambda + DynamoDB 배포 가이드

이 가이드는 Paper Watcher를 AWS Lambda + DynamoDB로 배포하는 방법을 안내합니다.

## 📋 사전 요구사항

1. **AWS CLI 설치 및 설정**
   ```bash
   aws configure
   # AWS Access Key ID, Secret Access Key, Region(ap-northeast-2) 입력
   ```

2. **AWS SAM CLI 설치**
   ```bash
   # macOS
   brew install aws-sam-cli

   # Linux/WSL
   pip install aws-sam-cli

   # 설치 확인
   sam --version
   ```

3. **AWS SES 이메일 검증 완료**
   - 발신자 이메일: jijae92@gmail.com
   - 수신자 이메일: jws0408@naver.com

---

## 🔐 1단계: AWS Secrets Manager 설정

Lambda는 민감한 정보를 Secrets Manager에서 가져옵니다.

### SES 설정 생성:

```bash
aws secretsmanager create-secret \
  --name paperwatcher/ses \
  --description "SES configuration for Paper Watcher" \
  --secret-string '{
    "sender": "jijae92@gmail.com",
    "recipients": ["jws0408@naver.com"],
    "subject_prefix": "[Daily Keyword Alerts]"
  }' \
  --region ap-northeast-2
```

### API 설정 생성:

```bash
aws secretsmanager create-secret \
  --name paperwatcher/api \
  --description "API configuration for Paper Watcher" \
  --secret-string '{
    "pubmed_api_key": "",
    "user_agent_email": "jijae92@gmail.com"
  }' \
  --region ap-northeast-2
```

> **참고:** PubMed API 키가 있으면 `pubmed_api_key`에 입력하세요. 없어도 작동합니다 (rate limit만 더 낮음).

---

## 🚀 2단계: Lambda 배포

### 빌드 및 배포:

```bash
cd /mnt/c/Users/User/Downloads/demoSES

# SAM 빌드
sam build

# 배포 (처음 배포 시)
sam deploy --guided

# 안내에 따라 입력:
# Stack Name: paper-watcher
# AWS Region: ap-northeast-2
# Parameter TableName: paper_seen
# Parameter SesSecretName: paperwatcher/ses
# Parameter ApiSecretName: paperwatcher/api
# Parameter ScheduleExpression: cron(0 0 * * ? *)  # 한국시간 오전 9시 = UTC 0시
# Parameter UseSmtp: false
# Confirm changes before deploy: Y
# Allow SAM CLI IAM role creation: Y
# Save arguments to configuration file: Y
```

### 이후 배포 (설정 저장됨):

```bash
sam build && sam deploy
```

---

## ⏰ 3단계: 스케줄 확인 및 변경

### 현재 스케줄:
- `cron(0 0 * * ? *)` = **매일 UTC 0시** = **한국 시간 오전 9시**

### 스케줄 변경하려면:

`template.yaml` 파일 수정:
```yaml
Parameters:
  ScheduleExpression:
    Type: String
    Default: cron(0 9 * * ? *)  # 한국 시간 오후 6시
```

그 후 다시 배포:
```bash
sam build && sam deploy
```

---

## 🧪 4단계: 수동 테스트

배포 후 Lambda를 수동으로 실행해서 테스트:

```bash
# Lambda 함수 이름 확인
aws lambda list-functions --region ap-northeast-2 | grep paper-watcher

# 수동 실행
aws lambda invoke \
  --function-name paper-watcher-PaperWatcherFunction-XXXX \
  --region ap-northeast-2 \
  --payload '{}' \
  response.json

# 결과 확인
cat response.json
```

---

## 📊 5단계: 모니터링

### CloudWatch Logs 확인:

```bash
# 로그 그룹 확인
aws logs describe-log-groups --region ap-northeast-2 | grep paper-watcher

# 최근 로그 확인
aws logs tail /aws/lambda/paper-watcher-PaperWatcherFunction-XXXX --follow
```

### DynamoDB 테이블 확인:

```bash
# 테이블 항목 수 확인
aws dynamodb scan \
  --table-name paper_seen \
  --select COUNT \
  --region ap-northeast-2

# 최근 항목 확인 (상위 5개)
aws dynamodb scan \
  --table-name paper_seen \
  --max-items 5 \
  --region ap-northeast-2
```

---

## 🔄 6단계: 업데이트 배포

코드나 설정을 변경한 후:

```bash
# 1. 코드 변경 후 빌드
sam build

# 2. 배포
sam deploy

# 3. 로그 확인
aws logs tail /aws/lambda/paper-watcher-PaperWatcherFunction-XXXX --follow
```

---

## 🗑️ 7단계: 리소스 삭제 (필요시)

모든 AWS 리소스를 삭제하려면:

```bash
# CloudFormation 스택 삭제 (Lambda, DynamoDB, IAM 등 모두 삭제)
aws cloudformation delete-stack \
  --stack-name paper-watcher \
  --region ap-northeast-2

# Secrets Manager 시크릿 삭제
aws secretsmanager delete-secret \
  --secret-id paperwatcher/ses \
  --force-delete-without-recovery \
  --region ap-northeast-2

aws secretsmanager delete-secret \
  --secret-id paperwatcher/api \
  --force-delete-without-recovery \
  --region ap-northeast-2
```

---

## 💰 비용 추정

**무료 티어 (1년간):**
- Lambda: 100만 요청/월 무료
- DynamoDB: 25GB 저장소 무료
- SES: 62,000통 이메일 무료 (EC2에서 발송 시)

**무료 티어 이후 (1일 1회 실행 기준):**
- Lambda: ~$0.02/월
- DynamoDB: ~$0.25/월
- SES: ~$0.01/월
- **총 ~$0.28/월** (약 400원)

---

## 🎯 주요 설정

### 현재 설정:
- **키워드**: parp, isg, interferon, sting
- **저널**: Nature, Cell, Science 계열 18개
- **검색 소스**: PubMed, Crossref, RSS
- **검색 범위**: 최근 24시간
- **중복 제거**: 영구 (한 번 본 논문은 절대 다시 안 받음)
- **스케줄**: 매일 한국시간 오전 9시

### 설정 변경:
`template.yaml`의 Environment Variables 섹션에서 변경 가능

---

## 🐛 문제 해결

### 이메일이 안 오는 경우:
1. CloudWatch Logs 확인
2. SES 이메일 검증 상태 확인
3. Lambda 실행 권한 확인

### DynamoDB 오류:
1. 테이블 이름 확인 (`paper_seen`)
2. IAM 권한 확인

### Lambda 타임아웃:
- `template.yaml`에서 Timeout 값 증가 (현재 60초)

---

## 📞 문의

문제가 있으면 CloudWatch Logs를 확인하세요:
```bash
aws logs tail /aws/lambda/paper-watcher-PaperWatcherFunction-XXXX --follow
```
