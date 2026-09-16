#!/usr/bin/env python3
"""抓原始資料 → 跑空間分析 → 寫成 data/v2/<stamp>.json（schema: rain-snapshot/2）。

在 GitHub Actions 的 runner 上執行（網路不受限）。不做任何判讀，
判讀由讀這份快照的人／模型負責。

站碼對應：stations.json 用 6 碼，氣象署頁面歷史上出現過 5 碼，
因此先試 6 碼再退 5 碼，並在 meta.station_match 記錄實際命中方式。
"""
import json, os, re, sys, datetime as dt
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'spatial'))

import build_board as bb          # 共用既有的抓取層
import spatial as sp

TZ = ZoneInfo('Asia/Taipei')

# 金鑰只從環境變數讀。絕不寫進檔案——這個 repo 是公開的。
CWA_KEY = os.environ.get('CWA_KEY', '').strip()
OPENDATA = 'https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001'


def _scrub(msg):
    """錯誤訊息可能含完整 URL，把金鑰換掉再往外傳。"""
    return msg.replace(CWA_KEY, '<KEY>') if CWA_KEY else msg

# 鄉鎮 TID／縣市碼（座標與代表站來自 stations.json，不在這裡重複寫）
TID = {'台北市': ('6300200', '63'), '板橋區': ('6500100', '65'), '中和區': ('6500300', '65'),
       '土城區': ('6501300', '65'), '樹林區': ('6500700', '65'),
       '新竹市': ('1001802', '10018'), '竹北市': ('1000401', '10004')}


def fetch_stations_api():
    """走開放資料 API：欄位有名稱，且提供 ObsTime。需要 CWA_KEY。

    比爬網頁好的地方：不必靠欄位位置推斷語意，也拿得到精確觀測時刻。
    回傳 (obs, meta)；失敗回 (None, meta) 讓呼叫端退回爬網頁。
    """
    ids = list(sp.ST)
    obs, times, shapes = {}, [], set()
    # StationId 一次太多會被擋，拆成每組 10 個
    for i in range(0, len(ids), 10):
        group = ids[i:i + 10]
        url = (f"{OPENDATA}?Authorization={CWA_KEY}&format=JSON"
               f"&StationId={','.join(group)}")
        try:
            raw = json.loads(bb.get(url))
        except Exception as e:                      # noqa: BLE001
            return None, {'api_error': f"{type(e).__name__}: {_scrub(str(e))[:120]}"}

        rec = raw.get('records') or {}
        rows = rec.get('Station') or rec.get('location') or []
        shapes.add(','.join(sorted(rec.keys()))[:60])
        for st in rows:
            sid = st.get('StationId') or st.get('stationId')
            if sid not in sp.ST:
                continue
            el = st.get('RainfallElement') or {}

            def mm(key):
                v = (el.get(key) or {}).get('Precipitation')
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return None
                # 氣象署用負值當缺測哨兵（-99/-990/-998），不是 0
                return None if v < 0 else v

            p10, p1h, now = mm('Past10Min'), mm('Past1hr'), mm('Now')
            if p10 is None and p1h is None and now is None:
                continue                            # 整站缺測，不放進 obs
            obs[sid] = {'p10': p10 or 0.0, 'p1h': p1h or 0.0, 'now': now or 0.0}
            t = (st.get('ObsTime') or {}).get('DateTime')
            if t:
                times.append(t)

    if not obs:
        return None, {'api_error': 'API 回應中沒有任何可用測站', 'shapes': sorted(shapes)}
    return obs, {'obs_time': max(times) if times else None,
                 'source': 'opendata-api', 'matched_6': len(obs), 'matched_5': 0,
                 'missing': [s for s in sp.ST if s not in obs],
                 'station_match': 'API（StationId 直接比對）',
                 'time_pattern': 'ObsTime.DateTime', 'time_probe': [],
                 'shapes': sorted(shapes)}


def fetch_stations():
    """回傳 (obs, meta)。obs 只含真的抓到的站——抓不到的station不要放進去。"""
    page = bb.get(f"{bb.CWA}/V8/C/P/Rainfall/MOD_10M/10Min_MOD.html?ID=40786")
    t = re.sub(r"<[^>]+>", "|", page).replace("&nbsp;", " ")
    t = re.sub(r"\|+", "|", t)

    obs_time, time_pat = None, None
    for pat in (r"資料觀測時間[：:]\s*([0-9]{2,4}[/\-][0-9]{1,2}[/\-][0-9]{1,2}[^0-9]{0,3}[0-9]{1,2}:[0-9]{2})",
                r"觀測時間[：:]\s*([0-9]{2,4}[/\-][0-9]{1,2}[/\-][0-9]{1,2}[^0-9]{0,3}[0-9]{1,2}:[0-9]{2})",
                r"資料時間[：:]\s*([^|]{6,24}?[0-9]{1,2}:[0-9]{2})"):
        m = re.search(pat, t)
        if m:
            obs_time, time_pat = m.group(1).strip(), pat[:14]
            break
    # 抓不到時留下探針：下一次執行的 log 就能看出頁面實際格式，不必反覆猜
    # 2026-09-16 實測：這個 MOD 片段只有資料列，沒有表頭也沒有任何時間字串
    # （H:MM、中文時間、數字串三路探針全空）。留輕量探針，格式改版時會浮現。
    time_probe = [] if obs_time else re.findall(r"\d{1,2}[:時]\d{2}", t)[:2]

    obs, hit6, hit5, miss = {}, [], [], []
    for sid in sp.ST:
        for code, bucket in ((sid, hit6), (sid[:-1], hit5)):
            i = t.find(f"({code})")
            if i < 0:
                continue
            cells = [c.strip() for c in t[i:i + 260].split("|")[1:]][:14]
            nums = [c for c in cells if c == "-" or re.match(r"^\d+(\.\d+)?$", c)]
            # 站出現在頁面上＝有回報。"-" 是回報 0，不是沒回報——
            # 把回報 0 的站丟掉會讓環域覆蓋率永遠是 N/N，
            # 也會讓 terrain_split 的平地中位數只由濕站算出而低估地形分離。
            vals = [0.0 if c == "-" else float(c) for c in nums[:7]]
            if len(vals) < 7:
                continue
            obs[sid] = {'p10': vals[0], 'p1h': vals[1], 'now': vals[6]}
            bucket.append(sid)
            break
        else:
            miss.append(sid)
    return obs, {'obs_time': obs_time, 'time_pattern': time_pat, 'time_probe': time_probe,
                 'matched_6': len(hit6), 'matched_5': len(hit5),
                 'missing': miss, 'station_match': '6碼' if hit6 and not hit5 else
                 ('5碼' if hit5 and not hit6 else ('混合' if hit6 else '全部失敗'))}


def fetch_forecasts():
    """yr.no 逐日 mm + 氣象署鄉鎮 3 小時 PoP。任一地失敗就不放該地。"""
    yr_by_loc, pop_by_loc = {}, {}
    for loc, (lat, lon, _rep) in sp.LOC.items():
        try:
            y = bb.yr(lat, lon)
            days = y.get('days') or {}
            if days:
                yr_by_loc[loc] = days
        except Exception as e:
            bb.note_fail(f'yr.no（{loc}）', e)
        tid = TID.get(loc, (None,))[0]
        if not tid:
            continue
        try:
            rows = bb.cwa_hourly(tid)
            if rows:
                pop_by_loc[loc] = [{'date': d, 'hour': h, 'wx': w, 'pop': p}
                                   for d, h, w, p in rows[:24]]
        except Exception as e:
            bb.note_fail(f'鄉鎮逐時（{loc}）', e)

    out = {}
    if yr_by_loc:
        out['yr'] = {'issued': dt.datetime.now(TZ).isoformat(timespec='minutes'),
                     'unit': 'mm', 'by_loc': yr_by_loc}
    if pop_by_loc:
        out['cwa_pop'] = {'issued': dt.datetime.now(TZ).isoformat(timespec='minutes'),
                          'unit': '%', 'note': '鄉鎮 3 小時降雨機率（未來 24 筆）',
                          'by_loc': pop_by_loc}
    return out


# 本報告的七個地點所屬行政區。桃園、苗栗等鄰近縣市另外列，
# 因為「鄰近縣市有特報」與「本區有特報」是兩回事，不能混為一談。
AREA_OURS = ['臺北', '台北', '新北', '新竹', '大臺北', '大台北', '北部', '北臺', '北台']
AREA_NEAR = ['桃園', '苗栗', '基隆', '宜蘭']

def fetch_warnings():
    """全部中文特報都保留，只標記是否提到本區。

    抓取層不替判讀層做編輯決定：用內容關鍵字過濾會把「桃園以北」這類
    寫法不同的特報整則丟掉，而且丟掉之後判讀端無從得知。
    probe 記錄各階段筆數，便於分辨「真的沒有特報」與「解析失敗」。
    """
    try:
        t = bb.get(f"{bb.CWA}/Data/js/warn/Warning_Content.js")
    except Exception as e:
        bb.note_fail('氣象署特報', e)
        return [], {'error': type(e).__name__}

    raw = re.findall(r"'title':'([^']*)',\s*'issued':'([^']*)',\s*'validto':'([^']*)',\s*'content':'([^']*)'", t)
    out = []
    for title, issued, validto, content in raw:
        if not re.search(r"[一-鿿]", title):
            continue                      # 英文版是同一份資料的重複
        body = re.sub(r"\\n", " ", content).strip()
        body = re.sub(r"^發布時間：[\d/:\s]+", "", body)
        out.append({'title': title, 'issued': issued, 'validto': validto,
                    'text': body[:220].strip(),
                    'areas_ours': [a for a in AREA_OURS if a in body],
                    'areas_near': [a for a in AREA_NEAR if a in body]})
    return out, {'bytes': len(t), 'raw_matches': len(raw), 'zh_titled': len(out),
                 'hits_ours': sum(1 for w in out if w['areas_ours']),
                 'hits_near_only': sum(1 for w in out if not w['areas_ours'] and w['areas_near'])}


def main():
    now = dt.datetime.now(TZ)
    stamp = now.strftime('%Y%m%dT%H%M')

    api_note = None
    obs, meta = (None, {})
    if CWA_KEY:
        obs, meta = fetch_stations_api()
        if obs is None:
            api_note = meta.get('api_error', 'API 失敗')
            print(f"API 失敗，退回爬網頁：{api_note}", file=sys.stderr)
    if not obs:
        obs, meta = fetch_stations()
        meta['source'] = 'scrape'
        if api_note:
            meta['api_error'] = api_note
    if not obs:
        print('一站都沒抓到，不寫快照。', meta, file=sys.stderr)
        print('errors:', bb.errors, file=sys.stderr)
        return 1

    envelope = {}
    for loc in sp.LOC:
        s = sp.summarize(obs, loc)
        envelope[loc] = {'rep': s['rep_value'], 'env_max': s['env_max'],
                         'wet': f"{s['env_wet']}/{s['env_n']}",
                         'verdict': sp.verdict(s)}

    warnings, warn_probe = fetch_warnings()

    snap = {
        'schema': 'rain-snapshot/2',
        'stamp': now.isoformat(timespec='minutes'),
        'mode': 'actions+scrape',
        'obs': {
            'time': meta['obs_time'],          # 該頁不提供時，為 None，不要猜
            # 頁面每 10 分鐘更新一次，所以實際觀測時刻落在 [fetched_at - 10min, fetched_at]。
            # 這是有界限的說明，不是推估值；報告要寫區間而不是寫成精確時刻。
            'fetched_at': now.isoformat(timespec='minutes'),
            'time_bound_min': 10 if not meta['obs_time'] else 0,
            'station_count': len(obs), 'stations': obs},
        'spatial': {
            'terrain': sp.terrain_split(obs, box=(24.80, 25.25, 121.30, 121.70)),
            'track': sp.track(obs),
            'envelope': envelope,
        },
        'forecasts': fetch_forecasts(),
        'warnings': warnings,
        # parser 2 起，回報 0 的站也收進 obs（parser 1 會漏掉，覆蓋率失真）
        'meta': dict({k: meta.get(k) for k in ('station_match', 'matched_6', 'matched_5',
                                               'missing', 'time_pattern', 'time_probe',
                                               'source', 'api_error', 'shapes')},
                     parser=6, warn_probe=warn_probe),
        'errors': bb.errors,
    }

    d = os.path.join(ROOT, 'data', 'v2')
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f'{stamp}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print(f"寫入 {path}")
    print(f"  來源：{meta.get('source')}"
          + (f"（API 失敗：{meta['api_error']}）" if meta.get('api_error') else ''))
    print(f"  站碼比對：{meta.get('station_match')}，命中 {len(obs)}/{len(sp.ST)} 站")
    print(f"  地形分離：{snap['spatial']['terrain']['separation']}")
    print(f"  雨帶追蹤：{snap['spatial']['track']['confidence']}")
    print(f"  觀測時刻：{meta['obs_time'] or '該頁不提供，以抓取時刻回推 10 分鐘為界'}"
          + (f"（探針：{meta['time_probe']}）" if meta['time_probe'] else ''))
    print(f"  特報：原始 {warn_probe.get('raw_matches','?')} 筆 → 中文 {warn_probe.get('zh_titled','?')} 則"
          f"；提到本區 {warn_probe.get('hits_ours','?')} 則"
          f"、僅鄰近縣市 {warn_probe.get('hits_near_only','?')} 則"
          f"（檔案 {warn_probe.get('bytes','?')} bytes）")
    print(f"  失敗來源 {len(bb.errors)} 個")
    if meta['missing']:
        print(f"  未命中站：{', '.join(meta['missing'][:12])}"
              + (' …' if len(meta['missing']) > 12 else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
