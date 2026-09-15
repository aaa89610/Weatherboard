#!/usr/bin/env python3
"""北部降雨空間分析模組（低耦合，純函式，以 dict/JSON 溝通）

輸入一律是 obs：{station_id: {"p10":float, "p1h":float, "now":float}}
（缺的站直接不要放進 dict，不要填 0 冒充）

四個互不依賴的功能：
  envelope(loc)         地點的環域站群（依距離自動算）
  summarize(obs, loc)   代表值 / 環域最大 / 覆蓋率 / 最近有雨站
  terrain_split(obs)    山區 vs 平地 中位數與地形比值
  track(obs)            雨帶質心位移與 1 小時外推
"""
import json, math, os

BASE = os.path.dirname(os.path.abspath(__file__))
_S = json.load(open(os.path.join(BASE, 'stations.json')))
ST, LOC = _S['stations'], _S['locations']

TERRAIN_HIGH = {'windward', 'hill'}      # 迎風面與山區
TERRAIN_LOW  = {'floor', 'plain'}        # 盆地底與平原
# 'edge'（盆地邊緣）刻意兩邊都不算，它正是 09/15 早上出事的地帶

def _km(a_lat, a_lon, b_lat, b_lon):
    """兩點距離（km），小範圍用等距圓柱近似即可，誤差 <0.3%。"""
    dy = (b_lat - a_lat) * 110.57
    dx = (b_lon - a_lon) * 111.32 * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dx, dy)

def _bearing(dlat, dlon, lat0):
    """位移向量 → 方位角（度，0=北，順時針）與距離 km。"""
    dy = dlat * 110.57
    dx = dlon * 111.32 * math.cos(math.radians(lat0))
    return (math.degrees(math.atan2(dx, dy)) % 360, math.hypot(dx, dy))

_DIRS = ['北','北北東','東北','東北東','東','東南東','東南','南南東',
         '南','南南西','西南','西南西','西','西北西','西北','北北西']
def compass(deg):
    return _DIRS[int((deg % 360) / 22.5 + 0.5) % 16]

# ---------------------------------------------------------------- 1. 環域

def envelope(loc, radius_km=9.0):
    """回傳 [(station_id, name, terrain, 距離km), ...]，由近到遠。"""
    lat, lon, _rep = LOC[loc]
    out = []
    for sid, (name, _town, slat, slon, terr) in ST.items():
        d = _km(lat, lon, slat, slon)
        if d <= radius_km:
            out.append((sid, name, terr, round(d, 1)))
    return sorted(out, key=lambda r: r[3])

# ---------------------------------------------------------------- 2. 地點摘要

def summarize(obs, loc, field='now', radius_km=9.0):
    """單站 → 環域。回傳代表值、環域最大、有雨站比例、最近有雨站。"""
    rep_id = LOC[loc][2]
    env = envelope(loc, radius_km)
    have = [(sid, nm, tr, d, obs[sid][field]) for sid, nm, tr, d in env if sid in obs]
    wet  = [r for r in have if r[4] > 0]
    rep  = obs.get(rep_id, {}).get(field)
    return {
        'loc': loc,
        'rep_station': ST[rep_id][0],
        'rep_value': rep,                       # None = 該站沒資料，不要當 0
        'env_n': len(have),
        'env_wet': len(wet),
        'env_max': max((r[4] for r in have), default=None),
        'env_max_at': max(have, key=lambda r: r[4])[1] if have else None,
        'nearest_wet': (wet[0][1], wet[0][3], wet[0][4]) if wet else None,
        'coverage': round(len(wet) / len(have), 2) if have else None,
        'detail': [(nm, tr, d, v) for _s, nm, tr, d, v in have],
    }

def verdict(s):
    """把摘要翻成一句可直接寫進報告的判斷。"""
    if s['env_n'] == 0:
        return '環域內無可用測站'
    if s['env_wet'] == 0:
        return f"環域 {s['env_n']} 站全 0（含代表站）"
    if s['rep_value'] in (0, 0.0, None) and s['env_wet'] > 0:
        nw = s['nearest_wet']
        return (f"代表站 {s['rep_station']} 報 0，但環域 {s['env_wet']}/{s['env_n']} 站有雨；"
                f"最近的是 {nw[0]}（{nw[1]} km，{nw[2]} mm）→ 局部有雨，站點可能漏接")
    return (f"代表站 {s['rep_station']} {s['rep_value']} mm；"
            f"環域最大 {s['env_max']} mm（{s['env_max_at']}），"
            f"{s['env_wet']}/{s['env_n']} 站有雨")

# ---------------------------------------------------------------- 3. 地形比值

def terrain_split(obs, field='now', box=None):
    """山區/迎風面 vs 盆地平地 的中位數與比值。box=(lat0,lat1,lon0,lon1) 可限定範圍。"""
    def med(v):
        v = sorted(v)
        n = len(v)
        return None if n == 0 else (v[n//2] if n % 2 else (v[n//2-1]+v[n//2])/2)
    hi, lo, edge = [], [], []
    for sid, rec in obs.items():
        if sid not in ST:
            continue
        nm, _t, lat, lon, terr = ST[sid]
        if box and not (box[0] <= lat <= box[1] and box[2] <= lon <= box[3]):
            continue
        v = rec.get(field)
        if v is None:
            continue
        (hi if terr in TERRAIN_HIGH else lo if terr in TERRAIN_LOW else edge).append(v)
    mh, ml, me = med(hi), med(lo), med(edge)
    ratio = None
    if mh is not None and ml is not None:
        ratio = round(mh / ml, 1) if ml > 0 else ('∞' if mh > 0 else None)
    sep = None
    if mh is not None and ml is not None:
        sep = ('完全分離（山區有雨、平地掛零）' if ml == 0 and mh > 0 else
               '強烈地形分離（≥3 倍）' if isinstance(ratio, float) and ratio >= 3 else
               '中度分離（1.5–3 倍）'   if isinstance(ratio, float) and ratio >= 1.5 else
               '無明顯地形分離')
    return {'separation': sep,
            'high_n': len(hi), 'high_med': mh, 'high_max': max(hi, default=None),
            'edge_n': len(edge), 'edge_med': me, 'edge_max': max(edge, default=None),
            'low_n': len(lo), 'low_med': ml, 'low_max': max(lo, default=None),
            'orographic_ratio': ratio}

# ---------------------------------------------------------------- 4. 雨帶追蹤

def track(obs, box=(24.70, 25.35, 121.15, 121.80)):
    """單次 API 快照即可估雨帶移動。

    近況質心 A：權重 p10（有效時刻 ≈ T-5 分）
    前況質心 B：權重 max(p1h - p10, 0)（過去 50 分鐘的雨，有效時刻 ≈ T-35 分）
    位移 A-B ÷ 0.5 小時 = 移速向量，再外推 1 小時。
    """
    def centroid(w_fn):
        sw = sx = sy = 0.0
        pts = []
        for sid, rec in obs.items():
            if sid not in ST:
                continue
            nm, _t, lat, lon, _terr = ST[sid]
            if not (box[0] <= lat <= box[1] and box[2] <= lon <= box[3]):
                continue
            w = w_fn(rec)
            if w and w > 0:
                sw += w; sy += w * lat; sx += w * lon
                pts.append((nm, w))
        return (None if sw == 0 else (sy/sw, sx/sw, sw, pts))

    A = centroid(lambda r: r.get('p10') or 0)
    B = centroid(lambda r: max((r.get('p1h') or 0) - (r.get('p10') or 0), 0))
    out = {'now_centroid': None, 'prev_centroid': None, 'motion': None,
           'trend': None, 'forecast_1h': None, 'confidence': 'none', 'note': ''}
    if A: out['now_centroid']  = {'lat': round(A[0],4), 'lon': round(A[1],4),
                                  'weight': round(A[2],1), 'stations': A[3]}
    if B: out['prev_centroid'] = {'lat': round(B[0],4), 'lon': round(B[1],4),
                                  'weight': round(B[2],1), 'stations': B[3]}
    if not A:
        out['note'] = '目前 10 分鐘內範圍內無站有雨，無法定位雨區'
        return out
    if not B:
        out['note'] = '前一時段無雨（雨剛開始），只有現況位置，無法算移動'
        out['confidence'] = 'position_only'
        return out
    # --- 消散/增長判定：雨區縮小時，質心位移是假象不是移動 ---
    na, nb = len(A[3]), len(B[3])
    wr = A[2] / B[2] if B[2] else None
    ar = na / nb
    trend = ('decaying' if ar < 0.6 else 'growing' if ar > 1.6 else 'steady')
    out['trend'] = {'wet_now': na, 'wet_prev': nb, 'area_ratio': round(ar, 2),
                    'weight_ratio': round(wr, 2) if wr else None, 'state': trend}

    deg, dist = _bearing(A[0]-B[0], A[1]-B[1], A[0])
    spd = dist / 0.5                                   # km/h
    out['motion'] = {'toward': compass(deg), 'bearing': round(deg),
                     'displacement_km': round(dist, 1), 'speed_kmh': round(spd, 1)}

    if trend == 'decaying':
        out['confidence'] = 'unusable'
        out['note'] = (f'雨區站數由 {nb} 減到 {na}（{int(ar*100)}%），質心位移主要來自雨區消散，'
                       '不是平流移動——方向與速度都不要採用。此時該講的是「雨在減弱、'
                       '殘留在哪幾站」，而不是「往哪裡去」。')
        out['forecast_1h'] = None
        return out

    f_lat = A[0] + (A[0]-B[0]) * 2                     # 再外推 1 小時 = 位移 ×2
    f_lon = A[1] + (A[1]-B[1]) * 2
    dists = sorted([(l, round(_km(f_lat, f_lon, LOC[l][0], LOC[l][1]), 1)) for l in LOC],
                   key=lambda r: r[1])
    out['forecast_1h'] = {'lat': round(f_lat, 4), 'lon': round(f_lon, 4),
                          'all_locs': dists,
                          'may_affect': [l for l, d in dists if d <= 12]}
    if   spd > 90 or na < 3:            out['confidence'] = 'low'
    elif na >= 6 and trend == 'steady': out['confidence'] = 'medium'
    else:                               out['confidence'] = 'low'
    out['note'] = ('站網間距約 5 km，只抓得到 >10 km 的中尺度雨帶，抓不到單一對流胞；'
                   '兩個質心的有效時刻是近似值，方向比速度可信。'
                   + ('（雨區正在擴大）' if trend == 'growing' else ''))
    return out
