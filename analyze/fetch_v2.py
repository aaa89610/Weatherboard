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

# 鄉鎮 TID／縣市碼（座標與代表站來自 stations.json，不在這裡重複寫）
TID = {'台北市': ('6300200', '63'), '板橋區': ('6500100', '65'), '中和區': ('6500300', '65'),
       '土城區': ('6501300', '65'), '樹林區': ('6500700', '65'),
       '新竹市': ('1001802', '10018'), '竹北市': ('1000401', '10004')}


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
    if obs_time:
        time_probe = []
    else:
        # H:MM 找不到時，把頁首文字與其他時間樣候選一起留下——
        # 空探針只說明「沒有 H:MM」，說不出頁面長什麼樣。
        time_probe = {
            'hhmm': re.findall(r"[^|]{0,18}\d{1,2}:\d{2}[^|]{0,8}", t)[:3],
            'cjk_time': re.findall(r"\d{1,2}\s*[時点]\s*\d{0,2}\s*分?", t)[:3],
            'digits8plus': re.findall(r"\d{8,14}", t)[:3],
            'head': t[:400],
        }

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

    obs, meta = fetch_stations()
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
        'obs': {'time': meta['obs_time'], 'station_count': len(obs), 'stations': obs},
        'spatial': {
            'terrain': sp.terrain_split(obs, box=(24.80, 25.25, 121.30, 121.70)),
            'track': sp.track(obs),
            'envelope': envelope,
        },
        'forecasts': fetch_forecasts(),
        'warnings': warnings,
        # parser 2 起，回報 0 的站也收進 obs（parser 1 會漏掉，覆蓋率失真）
        'meta': dict({k: meta[k] for k in ('station_match', 'matched_6', 'matched_5',
                                           'missing', 'time_pattern', 'time_probe')},
                     parser=4, warn_probe=warn_probe),
        'errors': bb.errors,
    }

    d = os.path.join(ROOT, 'data', 'v2')
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f'{stamp}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)

    print(f"寫入 {path}")
    print(f"  站碼比對：{meta['station_match']}（6碼 {meta['matched_6']} / 5碼 {meta['matched_5']}）"
          f"，命中 {len(obs)}/{len(sp.ST)} 站")
    print(f"  地形分離：{snap['spatial']['terrain']['separation']}")
    print(f"  雨帶追蹤：{snap['spatial']['track']['confidence']}")
    print(f"  觀測時刻：{meta['obs_time'] or '未取得'}"
          + ('' if meta['obs_time'] else f"（探針：{meta['time_probe']}）"))
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
