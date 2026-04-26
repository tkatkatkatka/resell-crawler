import sys    
import json
import time
import random
import urllib.parse
import hashlib
import requests
from concurrent.futures import ThreadPoolExecutor
import threading
import os

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
]
ACCEPT_LANGS = [
    'ko-KR,ko;q=0.9',
    'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'ko,en-US;q=0.9,en;q=0.8',
]
REFERERS = [
    'https://www.daangn.com/kr/buy-sell/',
    'https://www.daangn.com/kr/buy-sell/s/',
    'https://www.daangn.com/kr/',
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

def solve_pow(challenge, difficulty):
    target = difficulty // 4
    nonce = random.randint(0, 100000)
    for _ in range(10_000_000):
        h = hashlib.sha256(f'{challenge}{nonce}'.encode()).hexdigest()
        if h[:target] == '0' * target:
            return nonce
        nonce += 1
    return nonce

def get_pow_token(keyword, session):
    kw_enc = urllib.parse.quote(keyword)
    url = f'https://www.daangn.com/kr/buy-sell/s/?search={kw_enc}&_data=routes%2Fkr.buy-sell.s'
    try:
        r = session.get(url, headers=get_headers(), timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        pow_data = data.get('pow', {})
        if not pow_data:
            return {}
        challenge  = pow_data.get('challenge', '')
        difficulty = pow_data.get('difficulty', 4)
        expires_at = pow_data.get('expiresAt', 0)
        if not challenge:
            return {}
        print(f'[PoW] 챌린지 풀이 중 (difficulty={difficulty})...')
        nonce = solve_pow(challenge, difficulty)
        print(f'[PoW] 완료 nonce={nonce}')
        return {'nonce': nonce, 'expires_at': expires_at}
    except Exception as e:
        print(f'  [PoW] 오류: {e}')
        return {}

def search_region(keyword, region_id, delay_min, delay_max, session, pow_cache, pow_lock, retry=0):
    kw_enc = urllib.parse.quote(keyword)
    with pow_lock:
        pow_token  = pow_cache.get('token', {})
        pow_expires = pow_cache.get('expires', 0)
    now_ms = int(time.time() * 1000)
    if not pow_token or now_ms >= pow_expires - 5000:
        new_token = get_pow_token(keyword, session)
        if new_token:
            with pow_lock:
                pow_cache['token']   = new_token
                pow_cache['expires'] = new_token.get('expires_at', 0)
            pow_token = new_token
        else:
            return 'timeout', []
    nonce      = pow_token.get('nonce', 0)
    expires_at = pow_token.get('expires_at', 0)
    search_uri = urllib.parse.quote(
        f'http://www.daangn.com/kr/buy-sell/s/?search={kw_enc}', safe=''
    )
    url = (
        f'https://www.daangn.com/kr/api/v1/fleamarket/search'
        f'?region_id={region_id}'
        f'&search={kw_enc}'
        f'&uri={search_uri}'
        f'&nonce={nonce}'
        f'&expires_at={expires_at}'
    )
    try:
        time.sleep(random.uniform(delay_min, delay_max))
        r = session.get(url, headers=get_headers(), timeout=15)
        if r.status_code in (403, 429):
            return 'blocked', []
        if r.status_code == 401:
            with pow_lock:
                pow_cache['token']   = {}
                pow_cache['expires'] = 0
            if retry < 2:
                time.sleep(1.0)
                return search_region(keyword, region_id, delay_min, delay_max, session, pow_cache, pow_lock, retry+1)
            return 'timeout', []
        data     = r.json()
        articles = data.get('fleamarketArticles', [])
        return 'ok', articles
    except Exception as e:
        print(f'  [ERROR] 지역 {region_id} 예외: {e}')
        if retry < 2:
            time.sleep(random.uniform(1.0, 2.0))
            return search_region(keyword, region_id, delay_min, delay_max, session, pow_cache, pow_lock, retry+1)
        return 'timeout', []

def parse_articles(articles, keyword, search_scope):
    results  = []
    kw_lower = keyword.lower() if keyword else ''
    for a in articles:
        aid = a.get('id', '')
        if not aid:
            continue
        slug   = aid.rstrip('/').split('/')[-1]
        status = a.get('status', '')
        if status != 'Ongoing':
            continue
        title   = a.get('title', '')
        content = a.get('content', '')
        if kw_lower:
            if search_scope == 'title':
                if kw_lower not in title.lower():
                    continue
            else:
                if kw_lower not in title.lower() and kw_lower not in content.lower():
                    continue
        price_raw = a.get('price') or '0'
        try:
            price = int(float(price_raw))
        except:
            price = 0
        region     = a.get('region', {})
        rname      = region.get('name', '') or ''
        created_at = a.get('createdAt', '')
        boosted_at = a.get('boostedAt', '')
        results.append({
            'id':         slug,
            'title':      title,
            'price':      price,
            'price_fmt':  f"{price:,}원" if price else '가격없음',
            'thumbnail':  a.get('thumbnail', ''),
            'url':        a.get('href', ''),
            'region':     rname,
            'full_region': rname,
            'created_at': created_at or boosted_at,
            'boosted_at': boosted_at,
            'content':    content[:100],
        })
    return results

def main():
    arg_count = len(sys.argv) - 1
    keyword = '루이비통'
    search_scope = 'both'
    chunk = 1
    total_chunks = None
    max_workers = 3
    delay_min = 0.5
    delay_max = 1.0
    is_retry = False

    if arg_count >= 7:
        keyword      = sys.argv[1]
        search_scope = sys.argv[2]
        chunk        = int(sys.argv[3])
        total_chunks = int(sys.argv[4])
        max_workers  = int(sys.argv[5])
        delay_min    = float(sys.argv[6])
        delay_max    = float(sys.argv[7])
    elif arg_count >= 5:
        if arg_count == 6:
            keyword      = sys.argv[1]
            search_scope = sys.argv[2]
            chunk        = int(sys.argv[3])
            max_workers  = int(sys.argv[4])
            delay_min    = float(sys.argv[5])
            delay_max    = float(sys.argv[6])
        else:
            keyword      = sys.argv[1]
            chunk        = int(sys.argv[2])
            max_workers  = int(sys.argv[3])
            delay_min    = float(sys.argv[4])
            delay_max    = float(sys.argv[5])
            search_scope = 'both'
        is_retry = True
    else:
        print(f"⚠️ 인자 부족 ({arg_count}개). 기본값으로 실행합니다.")

    print(f"=== Crawler 시작 ===")
    print(f"키워드: {keyword}, 검색범위: {search_scope}, 청크: {chunk}, workers: {max_workers}, 딜레이: {delay_min}~{delay_max}, 재시도: {is_retry}")

    output_file = f'results_{chunk}.json'
    existing_results = {}
    existing_blocked = []

    if is_retry:
        if not os.path.exists(output_file):
            print(f"❌ 재시도 모드이나 결과 파일이 없습니다: {output_file}")
            sys.exit(1)
        with open(output_file, 'r', encoding='utf-8') as f:
            old_data = json.load(f)
            for item in old_data.get('items', []):
                existing_results[item['id']] = item
            existing_blocked = old_data.get('blocked_regions', [])
        if not existing_blocked:
            print("⚠️ 재시도할 차단 지역이 없습니다. 종료합니다.")
            return

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
    else:
        total      = len(all_regions)
        chunk_size = (total + total_chunks - 1) // total_chunks
        start      = (chunk - 1) * chunk_size
        end        = min(start + chunk_size, total)
        regions    = all_regions[start:end]
        print(f"청크 범위: {start}~{end} (총 {len(regions)}개 지역)")

    session    = requests.Session()
    pow_cache  = {'token': {}, 'expires': 0}
    pow_lock   = threading.Lock()

    print('[PoW] 초기 토큰 획득 중...')
    init_token = get_pow_token(keyword, session)
    if init_token:
        pow_cache['token']   = init_token
        pow_cache['expires'] = init_token.get('expires_at', 0)
        print(f'[PoW] 토큰 획득 완료')
    else:
        print('[PoW] 초기 토큰 획득 실패 - 계속 진행')

    results       = dict(existing_results) if is_retry else {}
    blocked_regions = []
    done = blocked = timeout_cnt = 0
    lock = threading.Lock()

    def process(region):
        nonlocal done, blocked, timeout_cnt
        rid = str(region.get('id', ''))
        if not rid:
            return
        status, articles = search_region(
            keyword, rid, delay_min, delay_max, session, pow_cache, pow_lock
        )
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
            parsed = parse_articles(articles, keyword, search_scope)
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

    block_rate = len(blocked_regions) / len(regions) if regions else 0
    if block_rate >= 0.5:
        print(f"⚠️ 경고: IP 차단 의심 - 차단율 {block_rate*100:.0f}%")

    output = {
        'items': list(results.values()),
        'blocked_regions': blocked_regions,
        'stats': {
            'total_regions': len(regions),
            'collected':     len(results),
            'blocked':       len(blocked_regions),
            'timeout':       timeout_cnt,
            'block_rate':    round(block_rate, 3),
        }
    }
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False)
    print(f"✅ 완료! {len(results)}건 저장 / 차단지역: {len(blocked_regions)}개 -> {output_file}")

if __name__ == '__main__':
    main()
