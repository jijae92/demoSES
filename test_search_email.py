#!/usr/bin/env python3
"""
실제 PubMed 검색 결과로 이메일 테스트
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from src.sources.pubmed import fetch_pubmed
from src.emailer import Emailer, EmailStats
from src.crawler.interface import ResultItem
from src.storage import SeenStorage

print("=" * 70)
print("PUBMED 검색 + 이메일 테스트")
print("=" * 70)
print()

# 설정
sender = os.getenv("EMAIL_FROM", "jijae92@gmail.com")
recipients = os.getenv("EMAIL_TO", "jws0408@naver.com").split(",")
aws_region = os.getenv("AWS_REGION", "ap-northeast-2")

# 검색 키워드 (config.yaml과 동일)
keywords = ["parp", "isg", "interferon", "sting"]
print(f"키워드: {', '.join(keywords)}")
print(f"발신자: {sender}")
print(f"수신자: {', '.join(recipients)}")
print()

# 중복 제거 스토리지 초기화 (영구 모드)
storage = SeenStorage(storage_path=".data/seen.json", dedup_window_days=14)
print(f"중복 제거 활성화: 한 번 본 논문은 절대 다시 보내지 않습니다 (영구 저장)")
print()

# PubMed에서 2025년 10월 데이터 검색 (이번 달)
print("PubMed 검색 중 (2025년 10월)...")
window_start = datetime(2025, 10, 1, tzinfo=timezone.utc)
window_end = datetime(2025, 10, 31, tzinfo=timezone.utc)

try:
    papers = fetch_pubmed(
        keywords=keywords,
        match_mode="OR",
        window_start_dt=window_start,
        window_end_dt=window_end,
        user_agent="PaperWatcher/1.0 Test",
        api_key=None
    )

    print(f"✓ {len(papers)} 개의 논문을 찾았습니다")
    print()

    if not papers:
        print("검색 결과가 없습니다. 종료합니다.")
        sys.exit(0)

    # ResultItem으로 변환
    all_results = []
    for paper in papers:
        # 요약문을 snippet으로 사용 (최대 300자)
        snippet = paper.summary[:300] if paper.summary else "초록이 없습니다."

        result = ResultItem(
            title=paper.title,
            url=paper.url,
            snippet=snippet,
            published_at=paper.published
        )
        all_results.append(result)

    # 중복 제거: 이미 본 논문은 제외
    results = []
    duplicates_count = 0
    for result in all_results:
        if storage.is_seen(result):
            duplicates_count += 1
        else:
            results.append(result)

    print(f"중복 제거 결과:")
    print(f"  - 전체: {len(all_results)}개")
    print(f"  - 중복: {duplicates_count}개")
    print(f"  - 새로운 논문: {len(results)}개")
    print()

    if not results:
        print("모든 논문이 이미 발송되었습니다. 새로운 논문이 없습니다.")
        sys.exit(0)

    # 결과 미리보기 (상위 5개)
    print("검색 결과 미리보기 (상위 5개):")
    print("-" * 70)
    for i, result in enumerate(results[:5], 1):
        print(f"{i}. {result.title}")
        print(f"   {result.url}")
        print()

    if len(results) > 5:
        print(f"... 외 {len(results) - 5}개 (총 {len(results)}개 논문을 이메일로 발송합니다)\n")
    else:
        print(f"총 {len(results)}개 논문을 이메일로 발송합니다.\n")

    # 이메일 발송
    print("이메일 발송 중...")
    print("-" * 70)

    stats = EmailStats()
    stats.total_found = len(all_results)
    stats.total_new = len(results)
    stats.total_duplicates = duplicates_count

    emailer = Emailer(
        sender=sender,
        recipients=recipients,
        subject_prefix="[PubMed Test]",
        aws_region=aws_region
    )

    success = emailer.send_email(
        results=results,
        keywords=keywords,
        stats=stats,
        min_results=1
    )

    print("-" * 70)
    print()

    if success:
        # 발송 성공 시 새로운 논문들을 '본 것'으로 표시
        storage.mark_seen(results)
        print("✓ 성공! 이메일이 발송되었습니다.")
        print(f"  수신함을 확인하세요: {', '.join(recipients)}")
        print(f"  {len(results)}개 논문을 중복 제거 목록에 추가했습니다.")
        sys.exit(0)
    else:
        print("✗ 실패: 이메일 발송에 실패했습니다.")
        sys.exit(1)

except Exception as e:
    print(f"✗ 오류 발생: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
