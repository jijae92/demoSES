#!/bin/bash
# Paper Watcher Lambda 배포 스크립트

set -e

echo "=========================================="
echo "Paper Watcher Lambda 배포 시작"
echo "=========================================="
echo ""

# 리전 설정
REGION="ap-northeast-2"

# AWS CLI 확인
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI가 설치되어 있지 않습니다."
    echo "설치: https://aws.amazon.com/cli/"
    exit 1
fi

# SAM CLI 확인
if ! command -v sam &> /dev/null; then
    echo "❌ SAM CLI가 설치되어 있지 않습니다."
    echo "설치: pip install aws-sam-cli"
    exit 1
fi

echo "✓ AWS CLI 및 SAM CLI 확인 완료"
echo ""

# Secrets Manager 확인
echo "Secrets Manager 시크릿 확인 중..."

SES_SECRET=$(aws secretsmanager describe-secret --secret-id paperwatcher/ses --region $REGION 2>/dev/null || echo "")
API_SECRET=$(aws secretsmanager describe-secret --secret-id paperwatcher/api --region $REGION 2>/dev/null || echo "")

if [ -z "$SES_SECRET" ]; then
    echo "⚠️  paperwatcher/ses 시크릿이 없습니다. 생성하시겠습니까? (y/n)"
    read -r answer
    if [ "$answer" = "y" ]; then
        echo "SES 설정 생성 중..."
        aws secretsmanager create-secret \
          --name paperwatcher/ses \
          --description "SES configuration for Paper Watcher" \
          --secret-string '{
            "sender": "jijae92@gmail.com",
            "recipients": ["jws0408@naver.com"],
            "subject_prefix": "[Daily Keyword Alerts]"
          }' \
          --region $REGION
        echo "✓ paperwatcher/ses 생성 완료"
    else
        echo "❌ SES 시크릿이 필요합니다. DEPLOY.md를 참조하세요."
        exit 1
    fi
else
    echo "✓ paperwatcher/ses 확인됨"
fi

if [ -z "$API_SECRET" ]; then
    echo "⚠️  paperwatcher/api 시크릿이 없습니다. 생성하시겠습니까? (y/n)"
    read -r answer
    if [ "$answer" = "y" ]; then
        echo "API 설정 생성 중..."
        aws secretsmanager create-secret \
          --name paperwatcher/api \
          --description "API configuration for Paper Watcher" \
          --secret-string '{
            "pubmed_api_key": "",
            "user_agent_email": "jijae92@gmail.com"
          }' \
          --region $REGION
        echo "✓ paperwatcher/api 생성 완료"
    else
        echo "❌ API 시크릿이 필요합니다. DEPLOY.md를 참조하세요."
        exit 1
    fi
else
    echo "✓ paperwatcher/api 확인됨"
fi

echo ""
echo "=========================================="
echo "SAM 빌드 시작"
echo "=========================================="
sam build

if [ $? -ne 0 ]; then
    echo "❌ SAM 빌드 실패"
    exit 1
fi

echo ""
echo "=========================================="
echo "SAM 배포 시작"
echo "=========================================="

# samconfig.toml이 있는지 확인
if [ -f "samconfig.toml" ]; then
    echo "기존 설정 파일 사용"
    sam deploy
else
    echo "처음 배포입니다. 가이드 모드로 진행합니다."
    sam deploy --guided
fi

if [ $? -ne 0 ]; then
    echo "❌ SAM 배포 실패"
    exit 1
fi

echo ""
echo "=========================================="
echo "배포 완료!"
echo "=========================================="
echo ""
echo "다음 명령어로 Lambda 함수를 수동 실행할 수 있습니다:"
echo ""
echo "  aws lambda invoke \\"
echo "    --function-name paper-watcher-PaperWatcherFunction-XXXX \\"
echo "    --region $REGION \\"
echo "    --payload '{}' \\"
echo "    response.json"
echo ""
echo "CloudWatch Logs:"
echo "  aws logs tail /aws/lambda/paper-watcher-PaperWatcherFunction-XXXX --follow"
echo ""
echo "DynamoDB 테이블 확인:"
echo "  aws dynamodb scan --table-name paper_seen --select COUNT --region $REGION"
echo ""
