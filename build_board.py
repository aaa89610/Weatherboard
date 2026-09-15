#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台灣北部六地逐時降雨看板 — 自動抓取與產生
在 GitHub Actions 上執行；每次產生 data.json、index.html 與 history/<stamp>.json。
資料來源：中央氣象署（鄉鎮逐時／一週、鄉鎮即時、縣市 36 小時、特報、天氣概況、定量降水預報、雨量站）、
          yr.no（MET Norway / ECMWF）、meteoblue。
原則：只寫實際取得的數值；任一來源失敗就標示失敗，絕不推估或捏造。
"""
import io, json, os, re, sys, time, datetime as dt
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Taipei")
CWA = "https://www.cwa.gov.tw"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
ROOT = os.path.dirname(os.path.abspath(__file__))

LOCS = [
    dict(name="台北市", sub="信義區", tid="6300200", cid="63",  lat=25.0375, lon=121.5637,
         st=[("C0AC7", "信義"), ("A1AG4", "四獸山"), ("A1AC7", "挹翠山莊")]),
    dict(name="板橋區", sub="新北市", tid="6500100", cid="65",  lat=25.0120, lon=121.4650,
         st=[("C0AJ8", "板橋")]),
    dict(name="中和區", sub="新北市", tid="6500300", cid="65",  lat=24.9994, lon=121.4990,
         st=[("C0AG8", "中和")]),
    dict(name="土城區", sub="新北市", tid="6501300", cid="65",  lat=24.9722, lon=121.4445,
         st=[("C0AD4", "土城"), ("CAA05", "國三S037K")]),
    dict(name="新竹市", sub="北區",   tid="1001802", cid="10018", lat=24.8069, lon=120.9689,
         st=[("C0D66", "新竹市東區")]),
    dict(name="竹北市", sub="新竹縣", tid="1000401", cid="10004", lat=24.8387, lon=121.0070,
         st=[("467571", "新竹(竹北)")]),
]

errors = []          # 取得失敗的來源，會顯示在看板上
def note_fail(what, e):
    msg = f"{what}：{type(e).__name__}"
    errors.append(msg)
    print("FAIL", what, repr(e), file=sys.stderr)

def get(url, binary=False, tries=3):
    sep = "&" if "?" in url else "?"
    last = None
    for i in range(tries):
        try:
            r = requests.get(f"{url}{sep}T={int(time.time()*1000)}", headers=UA, timeout=40)
            r.raise_for_status()
            if binary:
                return r.content
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(2 + 3 * i)
    raise last

def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ")
    s = re.sub(r"&[a-z]+;", " ", s)
    return re.sub(r"\s+", " ", s)

# ---------------------------------------------------------------- 氣象署

def cwa_hourly(tid):
    """[(MM/DD, HH, 天氣, PoP|None)] — 逐 1/3 小時，未來 3 天"""
    t = strip_html(get(f"{CWA}/V8/C/W/Town/MOD/3hr/{tid}_3hr_m.html"))
    out = []
    for m in re.finditer(r"(\d\d/\d\d)\(.\) (\d\d):\d\d (\S+) 看更多 溫度 [\d\s]+ 降雨機率 (\d+|-)", t):
        out.append((m.group(1), int(m.group(2)), m.group(3), None if m.group(4) == "-" else int(m.group(4))))
    return out

def cwa_week(tid):
    """{MM/DD: {'day':(wx,pop), 'night':(wx,pop)}} — 未來 7 天"""
    t = strip_html(get(f"{CWA}/V8/C/W/Town/MOD/Week/{tid}_Week_m.html"))
    out = {}
    for m in re.finditer(r"(\d\d/\d\d)\(.\) (白天|晚上) (\S+) 看更多 溫度 [\d~\s]+ 降雨機率 (\d+|-)", t):
        d = out.setdefault(m.group(1), {})
        d["day" if m.group(2) == "白天" else "night"] = (m.group(3), None if m.group(4) == "-" else int(m.group(4)))
    return out

def cwa_now(cid, tid):
    """(觀測時間, 時雨量)"""
    t = get(f"{CWA}/Data/js/GT/TableData_GT_T_{cid}.js")
    tm = re.search(r"GT_Time = \{'C':'([^']*)'", t)
    tm = re.sub(r"<br>", " ", tm.group(1)) if tm else ""
    m = re.search(r"'%s':\{[^}]*'Rain':'([^']*)'" % tid, t)
    return tm, (float(m.group(1)) if m and re.match(r"^[\d.]+$", m.group(1)) else 0.0)

def cwa_36hr():
    t = get(f"{CWA}/Data/js/TableData_36hr_County_C.js")
    issued = re.search(r"IssuedTime_36hr = '([^']*)'", t)
    out = {"issued": issued.group(1) if issued else ""}
    for cid in ("63", "65", "10018", "10004"):
        blk = re.search(r"'%s':\[(.*?)\n    \]" % cid, t, re.S)
        rows = []
        if blk:
            for m in re.finditer(r"'TimeRange':'([^']*)'.*?'PoP':'([^']*)'.*?'Wx':'([^']*)'", blk.group(1), re.S):
                rows.append(f"{m.group(1).replace(' ', '')} {m.group(2)}% {m.group(3)}")
        out[cid] = " ; ".join(rows)
    return out

def cwa_warnings():
    t = get(f"{CWA}/Data/js/warn/Warning_Content.js")
    out = []
    for m in re.finditer(r"'title':'([^']*)',\s*'issued':'([^']*)',\s*'validto':'([^']*)',\s*'content':'([^']*)'", t):
        title, issued, validto, content = m.groups()
        if not re.search(r"[一-鿿]", title):
            continue
        content = content.replace("\\n", " ").strip()
        if not re.search(r"臺北|新北|新竹|北部|大臺北|北臺", content):
            continue
        body = re.sub(r"^發布時間：[\d/:\s]+", "", content)
        out.append({"title": title, "issued": issued, "validto": validto, "text": body[:220].strip()})
    return out

def cwa_summary():
    t = get(f"{CWA}/Data/js/fcst/W50_Data.js")
    out = {}
    for cid, key in (("63", "taipei"), ("65", "newtaipei"), ("10018", "hsinchu")):
        m = re.search(r"'%s':\{.*?'Content':\[\s*'([^']*)'" % cid, t, re.S)
        out[key] = m.group(1) if m else ""
    return out

QPF_LEGEND = [((0xc2, 0xc2, 0xc2), "0.5-1"), ((0x9c, 0xfc, 0xff), "1-2"), ((0x03, 0xc9, 0xff), "2-5"),
              ((0x05, 0x9b, 0xff), "5-10"), ((0x03, 0x63, 0xff), "10-15"), ((0x05, 0x99, 0x02), "15-20"),
              ((0x3a, 0xff, 0x03), "20-30"), ((0xff, 0xfb, 0x03), "30-40"), ((0xff, 0xc8, 0x00), "40-50"),
              ((0xff, 0x95, 0x00), "50-70"), ((0xff, 0x00, 0x00), "70-90"), ((0xcc, 0x00, 0x00), "90-110"),
              ((0x99, 0x00, 0x00), "110-130"), ((0x96, 0x00, 0x99), "130-150"), ((0xc9, 0x00, 0xcc), "150-200"),
              ((0xfb, 0x00, 0xff), "200-300"), ((0xfd, 0xc9, 0xff), ">=300")]

def qpf_lower(label):
    """把圖例區間換成下限（mm），供比較大小用"""
    if label == "<0.5":
        return 0.0
    return float(label.replace(">=", "").split("-")[0])

def qpf_blocks():
    """{'6_06': {地點: 區間字串}} — 每格 6 小時，共 48 小時"""
    from PIL import Image
    out = {}
    for tag in ("6_06", "6_12", "6_18", "6_24", "6_30", "6_36", "6_42", "6_48"):
        raw = get(f"{CWA}/Data/fcst_img/QPF_ChFcstPrecip_{tag}.png", binary=True)
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        res = {}
        for L in LOCS:
            cx = round(-42887.6 + 360.55 * L["lon"])
            cy = round(9286.3 - 359.1 * L["lat"])
            best, bd = "<0.5", 1500
            for (R, G, B), lab in QPF_LEGEND:
                r, g, b = im.getpixel((cx, cy))
                d = (R - r) ** 2 + (G - g) ** 2 + (B - b) ** 2
                if d < bd:
                    bd, best = d, lab
            res[L["name"]] = best
        out[tag] = res
    return out

def cwa_stations():
    """{站碼: {'10m','1h','3h','6h','12h','24h','today'}}"""
    t = get(f"{CWA}/V8/C/P/Rainfall/MOD_10M/10Min_MOD.html?ID=40786")
    t = re.sub(r"<[^>]+>", "|", t).replace("&nbsp;", " ")
    t = re.sub(r"\|+", "|", t)
    want = {code for L in LOCS for code, _ in L["st"]}
    out = {}
    for code in want:
        i = t.find(f"({code})")
        if i < 0:
            continue
        cells = [c.strip() for c in t[i:i + 260].split("|")[1:]][:14]
        nums = [c for c in cells if c == "-" or re.match(r"^\d+(\.\d+)?$", c)]
        vals = [None if c == "-" else float(c) for c in nums[:7]]
        vals += [None] * (7 - len(vals))
        out[code] = dict(zip(("10m", "1h", "3h", "6h", "12h", "24h", "today"), vals))
    return out

# ---------------------------------------------------------------- 國外模式

def yr(lat, lon):
    j = requests.get(f"https://www.yr.no/api/v0/locations/{lat},{lon}/forecast",
                     headers=UA, timeout=40).json()
    days = {}
    for d in j.get("dayIntervals", []):
        days[d["start"][5:10].replace("-", "/")] = (d.get("precipitation") or {}).get("value")
    hours = []
    for s in j.get("shortIntervals", []):
        v = (s.get("precipitation") or {}).get("value") or 0
        if v > 0:
            hours.append((s["start"][5:10].replace("-", "/"), int(s["start"][11:13]), v))
    return {"update": j.get("update", ""), "days": days, "wet": hours}

def meteoblue(lat, lon):
    h = get(f"https://www.meteoblue.com/en/weather/week/{lat:.3f}N{lon:.3f}E")
    out = {}
    for chunk in h.split('<time datetime="')[1:]:
        day = chunk[:10]
        if not re.match(r"\d{4}-\d\d-\d\d", day):
            continue
        m = re.search(r"tab-precip[^>]*>([\s\S]{0,300}?)</div>", chunk)
        if not m:
            continue
        val = re.sub(r"<[^>]+>", "", m.group(1)).replace("&nbsp;", " ")
        val = re.sub(r"\s+", " ", val).strip().replace(" mm", "")
        p = re.search(r'tab-predictability[^>]*title="([^"]*)"', chunk)
        out[day[5:].replace("-", "/")] = {
            "precip": "—" if val in ("-", "") else val.replace("-", "–"),
            "pred": (p.group(1).replace("Predictability: ", "") if p else "")}
    return out


# ---------------------------------------------------------------- 抓取

def fetch_all():
    """抓齊所有來源，回傳原始資料。失敗的來源記在 errors，不中斷。"""
    warnings_raw, summary, c36, qpf, stations = [], {}, {}, {}, {}
    try: warnings_raw = cwa_warnings()
    except Exception as e: note_fail("氣象署特報", e)
    try: summary = cwa_summary()
    except Exception as e: note_fail("氣象署天氣概況", e)
    try: c36 = cwa_36hr()
    except Exception as e: note_fail("氣象署 36 小時預報", e)
    try: qpf = qpf_blocks()
    except Exception as e: note_fail("氣象署定量降水預報", e)
    try: stations = cwa_stations()
    except Exception as e: note_fail("氣象署雨量站", e)

    per = {}
    for L in LOCS:
        d = {}
        try: d["hourly"] = cwa_hourly(L["tid"])
        except Exception as e: note_fail(f"鄉鎮逐時預報（{L['name']}）", e); d["hourly"] = []
        try: d["week"] = cwa_week(L["tid"])
        except Exception as e: note_fail(f"鄉鎮一週預報（{L['name']}）", e); d["week"] = {}
        try: d["obs_time"], d["rain1h"] = cwa_now(L["cid"], L["tid"])
        except Exception as e: note_fail(f"鄉鎮即時觀測（{L['name']}）", e); d["obs_time"], d["rain1h"] = "", 0.0
        try: d["yr"] = yr(L["lat"], L["lon"])
        except Exception as e: note_fail(f"yr.no（{L['name']}）", e); d["yr"] = {"update": "", "days": {}, "wet": []}
        try: d["mb"] = meteoblue(L["lat"], L["lon"])
        except Exception as e: note_fail(f"meteoblue（{L['name']}）", e); d["mb"] = {}
        per[L["name"]] = d
    return dict(warnings_raw=warnings_raw, summary=summary, c36=c36,
                qpf=qpf, stations=stations, per=per)

# ---------------------------------------------------------------- 組裝

def md(d):                       # date -> "MM/DD"
    return d.strftime("%m/%d")

def risk_of(pop, qpf_mm, yr_mm, warned):
    lvl = 0
    if pop and pop >= 30 or yr_mm >= 0.3:
        lvl = 1
    if pop and pop >= 50 or qpf_mm >= 1 or yr_mm >= 2:
        lvl = 2
    if pop and pop >= 70 or qpf_mm >= 5 or yr_mm >= 6:
        lvl = 3
    if qpf_mm >= 15 or yr_mm >= 15:
        lvl = 4
    if warned and lvl < 2:
        lvl = max(lvl, 1)
    return lvl, ["低", "低–中", "中", "中–高", "高"][lvl]

def main(raw=None, write_history=True):
    now = dt.datetime.now(TZ)
    today, tomorrow = now.date(), now.date() + dt.timedelta(days=1)
    stamp = now.strftime("%Y%m%dT%H%M")

    prev = {}
    try:
        prev = json.load(open(os.path.join(ROOT, "data.json"), encoding="utf-8"))
    except Exception:                      # noqa: BLE001
        pass

    # ---- 抓取（--from-raw 時直接沿用 Actions 抓好的快照，不重抓）
    if raw is None:
        raw = fetch_all()
    warnings_raw, summary, c36 = raw["warnings_raw"], raw["summary"], raw["c36"]
    qpf, stations, per = raw["qpf"], raw["stations"], raw["per"]

    # ---- 特報
    warn_out, warned_area = [], set()
    for w in warnings_raw:
        lvl = "alert" if ("豪雨" in w["title"] or "大雨" in w["title"]) else "warning"
        warn_out.append({"level": lvl, "title": w["title"],
                         "valid": f"{w['issued'][5:]} → {w['validto'][5:]}", "text": w["text"]})
        if "大雨" in w["title"] or "豪雨" in w["title"]:
            for kw, nm in (("臺北", "台北市"), ("新北", "板橋區"), ("新竹", "新竹市")):
                if kw in w["text"]:
                    warned_area.add(nm)

    # ---- 今日、未來 6 小時
    locations = []
    for L in LOCS:
        d = per[L["name"]]
        nxt = [h for h in d["hourly"]
               if (h[0] == md(today) and h[1] >= now.hour) or (h[0] == md(tomorrow) and h[1] + 24 <= now.hour + 6)][:6]
        pops = [h[3] for h in nxt if h[3] is not None]
        pop_max = max(pops) if pops else None
        wet_hours = [h[1] for h in nxt if (h[3] or 0) >= 30 or "雨" in h[2]]
        qmm = 0.0
        if qpf:
            qmm = max(qpf_lower(v[L["name"]]) for v in list(qpf.values())[:1])
        yr_today_rest = sum(v for (dd, hh, v) in d["yr"]["wet"] if dd == md(today) and hh >= now.hour)
        lvl, label = risk_of(pop_max, qmm, yr_today_rest, L["name"] in warned_area)

        todays, notes = None, []
        for code, nm in L["st"]:
            v = stations.get(code, {}).get("today")
            if v is not None:
                if todays is None:
                    todays = v
                else:
                    notes.append(f"{nm} {v}")
        past6 = stations.get(L["st"][0][0], {}).get("6h")
        remaining = "< 0.5" if (qmm < 0.5 and yr_today_rest < 0.5) else f"{min(qmm, yr_today_rest):.1f}–{max(qmm, yr_today_rest, 0.5):.1f}"
        if wet_hours:
            umb = f"{min(wet_hours):02d}–{max(wet_hours)+1:02d} 時建議帶傘"
        else:
            umb = "不需要"
        locations.append({
            "name": L["name"], "sub": L["sub"], "risk": label, "level": lvl,
            "now": ("無雨" if (d["rain1h"] or 0) == 0 else f"正在下雨，時雨量 {d['rain1h']} mm")
                   + ("" if L["st"][0][0] not in stations
                      else f"，過去 6 小時 {past6 if past6 is not None else 0} mm"),
            "rain1h": d["rain1h"] or 0,
            "today": todays if todays is not None else 0,
            "todayNote": f"{L['st'][0][1]}站" + ("；" + "、".join(notes) if notes else ""),
            "remaining": remaining,
            "umbrella": umb,
            "pop": (f"未來 6 小時最高 {pop_max}%" if pop_max is not None else "未提供"),
        })

    # ---- 未來 7 天矩陣
    days = [tomorrow + dt.timedelta(days=i) for i in range(7)]
    matrix = {}
    for L in LOCS:
        d, row = per[L["name"]], []
        for day in days:
            key, iso = md(day), day.strftime("%m/%d")
            yv = d["yr"]["days"].get(key)
            wk = d["week"].get(key, {})
            pops = [p for (_w, p) in wk.values() if p is not None]
            wxs = [w for (w, _p) in wk.values()]
            mb = d["mb"].get(key, {})
            row.append({"yr": round(yv, 1) if isinstance(yv, (int, float)) else 0.0,
                        "mb": mb.get("precip", "—"),
                        "cwa": (f"{max(pops)}%" if pops else ""),
                        "wx": ("／".join(dict.fromkeys(wxs)) if wxs else "—")})
        matrix[L["name"]] = row

    # ---- 明顯雨日、最大值
    daily_max = []
    for i, day in enumerate(days):
        top = max(((matrix[L["name"]][i]["yr"], L["name"]) for L in LOCS), default=(0, ""))
        daily_max.append((top[0], top[1], i, day))
    notable = []
    for val, who, i, day in sorted(daily_max, reverse=True)[:4]:
        if val < 1:
            continue
        detail = "；".join(f"{L['name']} yr {matrix[L['name']][i]['yr']}／mb {matrix[L['name']][i]['mb']}"
                           for L in LOCS if matrix[L["name"]][i]["yr"] >= 1 or matrix[L["name"]][i]["mb"] != "—")
        mb_wet = sum(1 for L in LOCS if matrix[L["name"]][i]["mb"] != "—")
        agree = "高" if mb_wet >= 4 else ("中" if mb_wet >= 2 else "低（僅 yr 有訊號）")
        notable.append({"when": f"{day.month}/{day.day}（{'一二三四五六日'[day.weekday()]}）",
                        "where": who, "detail": detail + " mm", "agree": agree})
    pk = max(((matrix[L["name"]][i]["yr"], L["name"], i) for L in LOCS for i in range(7)), default=(0, "", 0))
    peak = {"value": f"約 {pk[0]:.0f} mm", "where": pk[1],
            "when": f"{days[pk[2]].month}/{days[pk[2]].day}（{'一二三四五六日'[days[pk[2]].weekday()]}）",
            "note": f"yr.no 日雨量；同日 meteoblue 估 {matrix[pk[1]][pk[2]]['mb']} mm"}

    # ---- 與上次比較
    changes = []
    if prev:
        pm, pd_ = prev.get("matrix", {}), prev.get("days", [])
        for L in LOCS:
            for i, day in enumerate(days):
                iso = day.isoformat()
                if iso in pd_ and L["name"] in pm:
                    old = pm[L["name"]][pd_.index(iso)]["yr"]
                    new = matrix[L["name"]][i]["yr"]
                    if abs(new - old) >= max(2.0, old * 0.4):
                        changes.append(f"{L['name']} {day.month}/{day.day} yr 由 {old} 改為 {new} mm")
        oldw = {w["title"] for w in prev.get("warnings", [])}
        neww = {w["title"] for w in warn_out}
        for t in neww - oldw:
            changes.append(f"新增特報：{t}")
        for t in oldw - neww:
            changes.append(f"特報解除：{t}")
        if prev.get("peak", {}).get("value") != peak["value"]:
            changes.append(f"最大雨量由 {prev.get('peak', {}).get('value', '—')} 改為 {peak['value']}（{peak['where']} {peak['when']}）")
    changes = changes[:8] or ["與上次相比沒有超過門檻的變動（yr 日雨量變化未達 2 mm 或 40%）"]

    # ---- 標題與不確定性
    wet_today = [l["name"] for l in locations if (l["today"] or 0) > 0]
    headline = (f"{peak['where']}{peak['when']}預估 {peak['value']} 為未來 7 天最大；"
                + (f"今日已累積降雨：{'、'.join(wet_today)}。" if wet_today else "今日六地尚未累積降雨。")
                + (f" 目前有 {len(warn_out)} 則特報生效。" if warn_out else ""))
    uncertainty = ("第 5–7 天（" + f"{days[4].month}/{days[4].day}–{days[6].month}/{days[6].day}"
                   + "）僅 yr.no 與 meteoblue 有數值，氣象署一週預報多半不再提供降雨機率；"
                   "meteoblue 在這幾天的可預報度常標示為 low，兩家的量級落差可能達數倍，請以「會不會下」而非「下多少」來看。"
                   "本頁數值皆為來源原始輸出，未做任何校正或推估。")
    if errors:
        uncertainty += " 本次取得失敗的來源：" + "、".join(sorted(set(errors))) + "（該欄位沿用上一次或顯示 0）。"

    obs_time = next((per[L["name"]]["obs_time"] for L in LOCS if per[L["name"]]["obs_time"]), "")
    yr_upd = next((per[L["name"]]["yr"]["update"] for L in LOCS if per[L["name"]]["yr"]["update"]), "")
    sources = [["氣象署鄉鎮逐時／一週預報", now.strftime("%m/%d %H:%M") + " 讀取"],
               ["氣象署鄉鎮即時觀測", obs_time],
               ["氣象署雨量站（10 分鐘）", now.strftime("%m/%d %H:%M") + " 讀取"],
               ["氣象署縣市 36 小時預報", (c36.get("issued", "") or "—") + " 發布"],
               ["氣象署定量降水預報", ("48 小時逐 6 小時" if qpf else "取得失敗")],
               ["yr.no（挪威氣象局／ECMWF）", (yr_upd[5:16].replace("T", " ") if yr_upd else "—")],
               ["meteoblue（多模式）", now.strftime("%m/%d %H:%M") + " 讀取"]]
    if warn_out:
        sources.append(["氣象署特報", "、".join(w["title"] for w in warn_out)])

    data = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "next": (now + dt.timedelta(hours=2)).strftime("%m/%d %H:00"),
        "mode": "自動" if not errors else "自動（部分來源失敗）",
        "headline": headline,
        "warnings": warn_out,
        "locations": locations,
        "days": [d.isoformat() for d in days],
        "matrix": matrix,
        "notable": notable or [{"when": "—", "where": "六地", "detail": "未來 7 天各來源都沒有超過 1 mm 的日雨量", "agree": "高"}],
        "peak": peak,
        "changes": changes,
        "sources": sources,
        "uncertainty": uncertainty,
    }

    with open(os.path.join(ROOT, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
    html = tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    if not html.lstrip().startswith("<!doctype"):
        html = ("<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
                "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
                "<title>北部六地雨情看板</title></head><body>\n" + html + "\n</body></html>")
    with open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    if write_history:
        os.makedirs(os.path.join(ROOT, "history"), exist_ok=True)
        snap = {"run_time": now.isoformat(timespec="minutes"), "mode": data["mode"],
                "stations": stations, "warnings": [w["title"] + "｜" + w["valid"] for w in warn_out],
                "county36": c36, "summary": summary,
                "qpf": {k: v for k, v in qpf.items()},
                "yr": {L["name"]: per[L["name"]]["yr"] for L in LOCS},
                "meteoblue": {L["name"]: per[L["name"]]["mb"] for L in LOCS},
                "cwa_hourly": {L["name"]: per[L["name"]]["hourly"][:24] for L in LOCS},
                "errors": errors}
        with open(os.path.join(ROOT, "history", f"{stamp}.json"), "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)

    print("OK", data["updated"], "errors:", errors)
    return 0

# ---------------------------------------------------------------- 兩段式執行

RAW_KEYS = ("warnings_raw", "summary", "c36", "qpf", "stations", "per")

def dump_raw():
    """只抓取，把完整原始資料寫進 history/<stamp>.json。由 GitHub Actions 執行。

    不做任何判讀，也不碰 data.json / index.html —— 那是判讀階段的事。
    """
    now = dt.datetime.now(TZ)
    stamp = now.strftime("%Y%m%dT%H%M")
    raw = fetch_all()

    got = (raw["stations"] or raw["c36"] or raw["summary"]
           or any(raw["per"][L["name"]]["hourly"] for L in LOCS))
    if not got:
        print("所有來源都失敗，不寫快照", errors, file=sys.stderr)
        return 1

    snap = {"run_time": now.isoformat(timespec="minutes"), "kind": "raw",
            "errors": errors, "data": {k: raw[k] for k in RAW_KEYS}}
    os.makedirs(os.path.join(ROOT, "history"), exist_ok=True)
    path = os.path.join(ROOT, "history", f"{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print("RAW OK", stamp, "errors:", errors)
    return 0

def load_raw(path):
    """讀回 dump_raw() 寫的快照，形狀與 fetch_all() 的回傳值相同。"""
    snap = json.load(open(path, encoding="utf-8"))
    if snap.get("kind") != "raw":
        raise SystemExit(f"{path} 不是 --fetch-only 產生的原始快照")
    errors.extend(snap.get("errors", []))
    return snap["data"]

if __name__ == "__main__":
    if "--fetch-only" in sys.argv:
        sys.exit(dump_raw())
    if "--from-raw" in sys.argv:
        src_path = sys.argv[sys.argv.index("--from-raw") + 1]
        sys.exit(main(raw=load_raw(src_path), write_history=False))
    sys.exit(main())
