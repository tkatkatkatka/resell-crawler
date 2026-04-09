import sys
import json
import time
import random
import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor
import threading

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

def get_region_id(region):
    name = region.get('name3') or region.get('name', '')
    rid = region.get('id', '')
    if name and rid:
        return f"{name}-{rid}"
    return str(rid)

def search_region(keyword, region_id, retry=0):
    kw_enc = urllib.parse.quote(keyword)
    url = (f'https://www.daangn.com/kr/buy-sell/'
           f'?search={kw_enc}&in={region_id}'
           f'&_data=routes%2Fkr.buy-sell._index')
    try:
        time.sleep(random.uniform(0.5, 1.0))
        r = requests.get(url, headers=get_headers(), timeout=15)
        if r.status_code in (403, 429):
            return 'blocked', []
        data = r.json()
        articles = (data.get('allPage') or {}).get('fleamarketArticles', [])
        return 'ok', articles
    except Exception:
        if retry < 2:
            time.sleep(random.uniform(1.0, 2.0))
            return search_region(keyword, region_id, retry + 1)
        return 'timeout', []

def parse_articles(articles):
    results = []
    for a in articles:
        aid = a.get('id')
        if not aid or a.get('status') != 'Ongoing':
            continue
        price_raw = a.get('price') or '0'
        price = int(float(price_raw)) if price_raw else 0
        region = a.get('region', {})
        rname = region.get('name3') or region.get('name') or ''
        results.append({
            'id': aid,
            'title': a.get('title', ''),
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
    keyword = sys.argv[1] if len(sys.argv) > 1 else '루이비통'
    chunk = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    total_chunks = int(sys.argv[3]) if len(sys.argv) > 3 else 80

    try:
        with open('regions.json', encoding='utf-8') as f:
            all_regions = json.load(f)
    except Exception as e:
        print(f"지역 목록 로드 실패: {e}")
        sys.exit(1)

    total = len(all_regions)
    chunk_size = (total + total_chunks - 1) // total_chunks
    start = (chunk - 1) * chunk_size
    end = min(start + chunk_size, total)
    regions = all_regions[start:end]
    print(f"청크 {chunk}/{total_chunks}: {start}~{end} ({len(regions)}개 지역) 키워드: {keyword}")

    results = {}
    blocked_regions = []
    done = 0
    blocked = 0
    timeout_cnt = 0
    lock = threading.Lock()

    def process(region):
        nonlocal done, blocked, timeout_cnt
        rid = get_region_id(region)

        status, articles = search_region(keyword, rid)

        # 차단 시: 점점 늘어나는 대기 후 최대 3회 재시도
        if status == 'blocked':
            with lock:
                blocked += 1
            for wait in [5, 10, 20]:
                time.sleep(random.uniform(wait, wait * 1.5))
                status, articles = search_region(keyword, rid)
                if status != 'blocked':
                    with lock:
                        blocked -= 1  # 재시도 성공 시 차단 카운트 취소
                    break
            else:
                # 3회 모두 차단 → blocked_regions에 기록
                with lock:
                    blocked_regions.append(rid)
                return

        if status == 'timeout':
            with lock:
                timeout_cnt += 1
            return

        if status == 'ok':
            parsed = parse_articles(articles)
            with lock:
                for item in parsed:
                    results[item['id']] = item

        with lock:
            done += 1
            if done % 50 == 0:
                print(f"진행: {done}/{len(regions)} / 수집: {len(results)}건 / 차단: {blocked} / 타임아웃: {timeout_cnt}")

    with ThreadPoolExecutor(max_workers=3) as executor:
        executor.map(process, regions)

    # IP 전체 차단 감지: 수집 0건 + 차단 지역이 절반 이상이면 경고
    block_rate = len(blocked_regions) / len(regions) if regions else 0
    if block_rate >= 0.5:
        print(f"⚠️  경고: IP 차단 의심 - 차단율 {block_rate*100:.0f}% ({len(blocked_regions)}/{len(regions)}개 지역)")

    output = {
        'items': list(results.values()),
        'blocked_regions': blocked_regions,
        'stats': {
            'total_regions': len(regions),
            'collected': len(results),
            'blocked': len(blocked_regions),
            'timeout': timeout_cnt,
            'block_rate': round(block_rate, 3),
        }
    }
    output_file = f'results_{chunk}.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"완료! {len(results)}건 저장 / 차단지역: {len(blocked_regions)}개 -> {output_file}")

if __name__ == '__main__':
    main()
