import sys
import json
import time
import random
import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor
import threading
import os
import re

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
]
ACCEPT_LANGS = [
    'ko-KR,ko;q=0.9',
    'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'ko,en-US;q=0.9,en;q=0.8',
    'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',
]
REFERERS = [
    'https://www.daangn.com/kr/buy-sell/',
    'https://www.daangn.com/kr/buy-sell/s/',
    'https://www.daangn.com/kr/',
    'https://www.daangn.com/',
]

def get_headers():
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': random.choice(ACCEPT_LANGS),
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': random.choice(REFERERS),
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'Connection': 'keep-alive',
    }

def search_region(keyword, region_id, retry=0):
    kw_enc = urllib.parse.quote(keyword)
    url = (f'https://www.daangn.com/kr/buy-sell/'
           f'?search={kw_enc}&in={region_id}'
           f'&_data=routes%2Fkr.buy-sell._index')
    try:
        time.sleep(random.uniform(delay_min, delay_max))
        r = requests.get(url, headers=get_headers(), timeout=15)
        if r.status_code in (403, 429):
            return 'blocked', []
        data = r.json()
        articles = (data.get('allPage') or {}).get('fleamarketArticles', [])
        if not articles:
            print(f"  [DEBUG] 지역 {region_id} 응답: {str(data)[:200]}")
        return 'ok', articles
    except Exception as e:
        print(f"  [ERROR] 지역 {region_id} 예외: {e}")
        if retry < 2:
            time.sleep(random.uniform(1.0, 2.0))
            return search_region(keyword, region_id, retry + 1)
        return 'timeout', []

def parse_articles(articles, keyword):
    """매물 파싱 + 브랜드 필터 (제목에 검색어 포함 필수)"""
    results = []
    kw_lower = keyword.lower() if keyword else ''
    
    for a in articles:
        aid = a.get('id')
        if not aid or a.get('status') != 'Ongoing':
            continue
        
        title = a.get('title', '')
        
        # ✅ 브랜드 필터: 제목에 검색어(브랜드명)가 없으면 건너뜀
        if kw_lower and kw_lower not in title.lower():
            continue
        
        price_raw = a.get('price') or '0'
        price = int(float(price_raw)) if price_raw else 0
        region = a.get('region', {})
        rname = region.get('name3') or region.get('name') or ''
        results.append({
            'id': aid,
            'title': title,
            'price': price,
            'price_fmt': f"{price:,}원" if price else '가격없음',
            'thumbnail': a.get('thumbnail', ''),
            'url': a.get('href', ''),
            'region': rname,
            'full_region': f"{region.get('name1','')} {region.get('name2','')} {rname}".strip(),
            'created_at': a.get('createdAt') or a.get('boostedAt', ''),
            'content': (a.get('content') or '')[:100],
        })
    return results

def main():
    global delay_min, delay_max
    keyword      = sys.argv[1] if len(sys.argv) > 1 else '루이비통'
    chunk        = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    # 인자 개수로 1차/2차 구분
    arg_count = len(sys.argv) - 1
    if arg_count >= 6:
        total_chunks = int(sys.argv[3])
        max_workers  = int(sys.argv[4])
        delay_min    = float(sys.argv[5])
        delay_max    = float(sys.argv[6])
        is_retry = False
    else:
        total_chunks = None
        max_workers  = int(sys.argv[3]) if arg_count >= 3 else 3
        delay_min    = float(sys.argv[4]) if arg_count >= 4 else 0.5
        delay_max    = float(sys.argv[5]) if arg_count >= 5 else 1.0
        is_retry = True

    print(f"=== Crawler 시작 ===")
    print(f"키워드: {keyword}, 청크: {chunk}, workers: {max_workers}, 딜레이: {delay_min}~{delay_max}, 재시도: {is_retry}")

    output_file = f'results_{chunk}.json'
    existing_results = {}
    existing_blocked = []

    if is_retry:
        if not os.path.exists(output_file):
            print(f"❌ 재시도 모드이나 결과 파일이 없습니다: {output_file}")
            sys.exit(1)
        print(f"📂 기존 결과 파일 발견: {output_file} → 차단 지역만 재시도합니다.")
        with open(output_file, 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            for item in old_data.get('items', []):
                existing_results[item['id']] = item
            existing_blocked = old_data.get('blocked_regions', [])
        print(f"   기존 수집: {len(existing_results)}건, 차단 지역: {len(existing_blocked)}개")
        if not existing_blocked:
            print("⚠️ 재시도할 차단 지역이 없습니다. 종료합니다.")
            return
    else:
        print(f"🆕 첫 실행: 전체 지역을 크롤링합니다.")

    try:
        with open('regions.json', encoding='utf-8') as f:
            all_regions = json.load(f)
        print(f"regions.json 로드 성공: 총 {len(all_regions)}개 지역")
    except Exception as e:
        print(f"❌ regions.json 로드 실패: {e}")
        sys.exit(1)

    if is_retry:
        blocked_set = set(existing_blocked)
        regions = [r for r in all_regions if str(r.get('id', '')) in blocked_set]
        print(f"🔄 재시도 대상 지역: {len(regions)}개")
    else:
        total = len(all_regions)
        chunk_size = (total + total_chunks - 1) // total_chunks
        start = (chunk - 1) * chunk_size
        end = min(start + chunk_size, total)
        regions = all_regions[start:end]
        print(f"청크 범위: {start}~{end} (총 {len(regions)}개 지역)")

    results = dict(existing_results) if is_retry else {}
    blocked_regions = []
    done = 0
    blocked = 0
    timeout_cnt = 0
    lock = threading.Lock()

    def process(region):
        nonlocal done, blocked, timeout_cnt
        rid = str(region.get('id', ''))
        if not rid:
            print(f"  [경고] 지역 ID 없음: {region}")
            return

        status, articles = search_region(keyword, rid)

        if status == 'blocked':
            with lock:
                blocked += 1
                blocked_regions.append(rid)
            return

        if status == 'timeout':
            with lock:
                timeout_cnt += 1
            return

        if status == 'ok':
            parsed = parse_articles(articles, keyword)   # ✅ keyword 전달
            with lock:
                for item in parsed:
                    results[item['id']] = item
                if parsed:
                    print(f"  [수집] 지역 {rid} ({region.get('name', '')}) - {len(parsed)}건")

        with lock:
            done += 1
            if done % 10 == 0:
                print(f"진행: {done}/{len(regions)} / 누적 {len(results)}건 / 차단:{blocked} / 타임아웃:{timeout_cnt}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        executor.map(process, regions)

    final_blocked = blocked_regions
    block_rate = len(final_blocked) / len(regions) if regions else 0
    if block_rate >= 0.5:
        print(f"⚠️ 경고: IP 차단 의심 - 차단율 {block_rate*100:.0f}% ({len(final_blocked)}/{len(regions)}개 지역)")

    output = {
        'items': list(results.values()),
        'blocked_regions': final_blocked,
        'stats': {
            'total_regions': len(regions),
            'collected': len(results),
            'blocked': len(final_blocked),
            'timeout': timeout_cnt,
            'block_rate': round(block_rate, 3),
        }
    }
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"✅ 완료! {len(results)}건 저장 / 차단지역: {len(final_blocked)}개 -> {output_file}")

if __name__ == '__main__':
    main()
