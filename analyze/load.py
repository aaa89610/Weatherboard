#!/usr/bin/env python3
"""讀 data/ 整個資料夾，整理成判讀用的摘要（低耦合：純函式，只吐 dict，不做判斷）。

兩種來源：
  data/v2/*.json   固定 schema（rain-snapshot/2），可跨時間比較
  data/raw/*.json  舊快照，每筆 schema 都不同，只做盡力而為的淺層抽取

判斷一律留給讀這份摘要的人（或模型），這裡不寫任何閾值。
"""
import json, os, glob, sys, datetime as dt
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCS = ['台北市', '板橋區', '中和區', '土城區', '樹林區', '新竹市', '竹北市']


def load_v2(d=None):
    """回傳 [(stamp, snapshot), ...]，依時間排序。只收 schema 正確的。"""
    out = []
    for p in sorted(glob.glob(os.path.join(d or os.path.join(ROOT, 'data/v2'), '*.json'))):
        try:
            s = json.load(open(p, encoding='utf-8'))
        except Exception as e:
            print(f"# 跳過無法解析：{os.path.basename(p)}（{type(e).__name__}）", file=sys.stderr)
            continue
        if str(s.get('schema', '')).startswith('rain-snapshot/'):
            out.append((s.get('stamp') or os.path.basename(p), s))
    return sorted(out, key=lambda r: r[0])


def load_legacy(d=None):
    """舊快照只抽得出來的共同欄位，抽不到的就不放。"""
    out = []
    for p in sorted(glob.glob(os.path.join(d or os.path.join(ROOT, 'data/raw'), '*.json'))):
        try:
            s = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        rec = {'file': os.path.basename(p), 'keys': sorted(s.keys())}
        for k in ('run_time', 'stamp', 'mode', 'note'):
            if k in s:
                rec[k] = s[k]
        w = s.get('warnings') or s.get('warning')
        if w:
            rec['warnings'] = w if isinstance(w, list) else [w]
        out.append(rec)
    return out


def envelope_series(v2):
    """各地點的環域觀測隨時間變化：{loc: [(stamp, rep, env_max, wet), ...]}"""
    ser = {l: [] for l in LOCS}
    for stamp, s in v2:
        env = (s.get('spatial') or {}).get('envelope') or {}
        for l, v in env.items():
            ser.setdefault(l, []).append(
                (stamp, v.get('rep'), v.get('env_max'), v.get('wet')))
    return {l: v for l, v in ser.items() if v}


def terrain_series(v2):
    """地形分離隨時間變化，含山區/平地中位數。"""
    return [(stamp, (s.get('spatial') or {}).get('terrain') or {}) for stamp, s in v2]


def warning_timeline(v2, legacy):
    """特報依發布時間排序去重，v2 優先。"""
    seen, out = set(), []
    for _stamp, s in v2:
        for w in s.get('warnings') or []:
            if isinstance(w, dict):
                k = (w.get('title'), w.get('issued'))
                if k not in seen:
                    seen.add(k)
                    out.append(w)
    for rec in legacy:
        for w in rec.get('warnings', []):
            t = w if isinstance(w, str) else json.dumps(w, ensure_ascii=False)
            if ('legacy', t[:40]) not in seen:
                seen.add(('legacy', t[:40]))
                out.append({'title': t[:120], 'issued': rec.get('run_time', ''), 'legacy': True})
    return sorted(out, key=lambda w: str(w.get('issued') or ''), reverse=True)


def digest():
    v2, legacy = load_v2(), load_legacy()
    return {'v2_count': len(v2), 'legacy_count': len(legacy),
            'latest_stamp': v2[-1][0] if v2 else None,
            'envelope': envelope_series(v2), 'terrain': terrain_series(v2),
            'warnings': warning_timeline(v2, legacy),
            'legacy_files': [r['file'] for r in legacy]}


def age_minutes(stamp):
    """最新快照距現在幾分鐘。stamp 解析不了就回 None，不猜。"""
    try:
        t = dt.datetime.fromisoformat(stamp)
    except Exception:
        return None
    now = dt.datetime.now(ZoneInfo('Asia/Taipei'))
    if t.tzinfo is None:
        t = t.replace(tzinfo=ZoneInfo('Asia/Taipei'))
    return int((now - t).total_seconds() // 60)


if __name__ == '__main__':
    d = digest()
    age = age_minutes(d['latest_stamp']) if d['latest_stamp'] else None
    if age is None:
        tag = '（無法判斷新鮮度）'
    elif age > 180:
        tag = f'← 已經 {age} 分鐘前，過舊，不可當成現況'
    elif age > 90:
        tag = f'← {age} 分鐘前，偏舊，報告要標明觀測時刻'
    else:
        tag = f'← {age} 分鐘前'
    print(f"v2 快照 {d['v2_count']} 筆；舊快照 {d['legacy_count']} 筆")
    print(f"最新 {d['latest_stamp']}  {tag}\n")

    print("── 地形分離 ──")
    for stamp, t in d['terrain']:
        if t:
            print(f"  {stamp}  {t.get('separation')}  "
                  f"山區中位數 {t.get('high_med')} / 邊緣 {t.get('edge_med')} / 平地 {t.get('low_med')}"
                  f"  比值 {t.get('orographic_ratio')}")

    print("\n── 環域觀測（代表站 / 環域最大 / 有雨站）──")
    for l, rows in d['envelope'].items():
        for stamp, rep, mx, wet in rows:
            flag = '  ← 代表站漏接' if rep in (0, 0.0) and mx and mx > 0 else ''
            print(f"  {l:5s} {stamp[:16]}  rep={rep}  env_max={mx}  wet={wet}{flag}")

    print("\n── 特報（新到舊，前 5 則）──")
    for w in d['warnings'][:5]:
        tag = '[舊格式] ' if w.get('legacy') else ''
        print(f"  {tag}{w.get('issued','')}  {w.get('title','')}")
        if w.get('text'):
            print(f"      {w['text'][:90]}")
