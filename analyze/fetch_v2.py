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

    obs_time = None
    m = re.search(r"資料觀測時間[：:]\s*([0-9/\-: ]+)", t)
    if m:
        obs_time = m.group(1).strip()

    obs, hit6, hit5, miss = {}, [], [], []
    for sid in sp.ST:
        for code, bucket in ((sid, hit6), (sid[:-1], hit5)):
            i = t.find(f"({code})")
            if i < 0:
                continue
            cells = [c.strip() for c in t[i:i + 260].split("|")[1:]][:14]
            nums = [c for c in cells if c == "-" or re.match(r"^\d+(\.\d+)?$", c)]
            vals = [None if c == "-" else float(c) for c in nums[:7]]
            if len(vals) < 7:
                continue
            p10, p1h, now = vals[0], vals[1], vals[6]
            if p10 is None and p1h is None and now is None:
                continue
            obs[sid] = {'p10': p10 or 0.0, 'p1h': p1h or 0.0, 'now': now or 0.0}
            bucket.append(sid)
            break
        else:
            miss.append(sid)
    return obs, {'obs_time': obs_time, 'matched_6': len(hit6), 'matched_5': len(hit5),
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

    try:
        warnings = [{'title': w['title'], 'issued': w['issued'],
                     'validto': w['validto'], 'text': w['text']}
                    for w in bb.cwa_warnings()]
    except Exception as e:
        bb.note_fail('氣象署特報', e)
        warnings = []

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
        'meta': {k: meta[k] for k in ('station_match', 'matched_6', 'matched_5', 'missing')},
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
    print(f"  特報 {len(warnings)} 則；失敗來源 {len(bb.errors)} 個")
    if meta['missing']:
        print(f"  未命中站：{', '.join(meta['missing'][:12])}"
              + (' …' if len(meta['missing']) > 12 else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
