"""由預報資料產生：逐時表、每日摘要、模型比較，以及繁體中文文字分析。不做任何網路存取。"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from .config import (BASE_MODEL, NOTABLE_DAY_MM, NOTABLE_DAY_PROB, UMBRELLA_MM, UMBRELLA_PROB)
from .verify import calib_factor

WD = "一二三四五六日"


def pdate(t: datetime) -> date:
    """逐時值為前一小時累積，歸屬日期以該小時開始時間計。"""
    return (t - timedelta(hours=1)).date()


def md(d: date) -> str:
    return f"{d.month}/{d.day}（{WD[d.weekday()]}）"


def hm(t: datetime) -> str:
    return t.strftime("%H:%M")


def base(fc: dict, loc: str) -> dict:
    return fc[loc][BASE_MODEL]


# ---------------- 表格資料 ----------------
def hourly_rows(locs, fc, calib, run_time) -> list[dict]:
    rows = []
    for loc in locs:
        b = base(fc, loc.key)
        others = {m: s for m, s in fc[loc.key].items() if m != BASE_MODEL}
        for i, t in enumerate(b["times"]):
            lead = (t - run_time).total_seconds() / 3600
            mm = b["precip"][i]
            f = calib_factor(calib, loc.key, lead)
            mv = {}
            for m, s in others.items():
                try:
                    j = s["times"].index(t)
                    mv[m] = s["precip"][j]
                except ValueError:
                    mv[m] = None
            vals = [v for v in mv.values() if v is not None]
            rows.append({"time": t, "date": pdate(t), "loc": loc.name, "loc_key": loc.key,
                         "lead": round(lead, 1), "prob": b["prob"][i] if b["prob"] else None,
                         "mm": mm, "mm_cal": round(mm * f, 2) if (f is not None and mm is not None) else None,
                         "models": mv, "m_min": min(vals) if vals else None,
                         "m_max": max(vals) if vals else None, "m_n": len(vals)})
    return rows


def daily(locs, fc, model=BASE_MODEL) -> dict:
    out = {}
    for loc in locs:
        s = fc[loc.key].get(model)
        if not s:
            continue
        d = defaultdict(lambda: {"mm": 0.0, "pmax": None, "rain_h": 0, "hours": 0})
        for i, t in enumerate(s["times"]):
            x = d[pdate(t)]
            v = s["precip"][i]
            x["hours"] += 1
            if v is not None:
                x["mm"] += v
                x["rain_h"] += v >= 0.1
            p = s["prob"][i] if s["prob"] else None
            if p is not None:
                x["pmax"] = p if x["pmax"] is None else max(x["pmax"], p)
        out[loc.key] = dict(sorted(d.items()))
    return out


def model_daily(locs, fc) -> dict:
    models = sorted({m for loc in locs for m in fc[loc.key]}, key=lambda m: (m != BASE_MODEL, m))
    return {m: daily(locs, fc, m) for m in models}


# ---------------- 文字分析 ----------------
def _periods(times: list[datetime]) -> list[str]:
    if not times:
        return []
    out, start, prev = [], times[0], times[0]
    for t in times[1:]:
        if t - prev > timedelta(hours=1):
            out.append((start, prev))
            start = t
        prev = t
    out.append((start, prev))
    return [f"{hm(a - timedelta(hours=1))}–{hm(b)}" for a, b in out]


def _risk(pmax, total):
    if (pmax or 0) >= 60 or total >= 3:
        return "高"
    if (pmax or 0) >= 30 or total >= 0.5:
        return "中"
    return "低"


def near_term(locs, fc, now) -> list[dict]:
    res = []
    for loc in locs:
        b = base(fc, loc.key)
        idx = [i for i, t in enumerate(b["times"]) if now < t <= now + timedelta(hours=6)]
        probs = [b["prob"][i] for i in idx if b["prob"] and b["prob"][i] is not None]
        total = sum(b["precip"][i] or 0 for i in idx)
        umb = [b["times"][i] for i in idx
               if (b["prob"] and (b["prob"][i] or 0) >= UMBRELLA_PROB) or (b["precip"][i] or 0) >= UMBRELLA_MM]
        pmax = max(probs) if probs else None
        res.append({"loc": loc.name, "pmax": pmax, "mm": round(total, 1),
                    "risk": _risk(pmax, total), "umbrella": _periods(umb)})
    return res


def today_remaining(locs, fc, now) -> list[dict]:
    today = now.date()
    res = []
    for loc in locs:
        b = base(fc, loc.key)
        idx = [i for i, t in enumerate(b["times"]) if t > now and pdate(t) == today]
        res.append({"loc": loc.name, "mm": round(sum(b["precip"][i] or 0 for i in idx), 1), "hours": len(idx)})
    return res


def notable_days(locs, dly) -> list[dict]:
    dates = sorted({d for v in dly.values() for d in v})
    out = []
    for d in dates:
        items = [(loc.name, dly[loc.key][d]) for loc in locs if d in dly.get(loc.key, {})]
        mx = max(items, key=lambda x: x[1]["mm"])
        pmax = max((x[1]["pmax"] or 0) for x in items)
        partial = any(x[1]["hours"] < 24 for x in items)
        if mx[1]["mm"] >= NOTABLE_DAY_MM or pmax >= NOTABLE_DAY_PROB:
            top = sorted(items, key=lambda x: -x[1]["mm"])[:3]
            out.append({"date": d, "partial": partial, "pmax": pmax,
                        "top": [(n, round(v["mm"], 1)) for n, v in top]})
    return out


def peaks(locs, fc, dly) -> dict:
    best_day = max(((loc.name, d, v["mm"]) for loc in locs for d, v in dly.get(loc.key, {}).items()),
                   key=lambda x: x[2], default=None)
    best6 = None
    for loc in locs:
        b = base(fc, loc.key)
        p = [v or 0 for v in b["precip"]]
        for i in range(0, max(0, len(p) - 5)):
            s = sum(p[i:i + 6])
            if best6 is None or s > best6[3]:
                best6 = (loc.name, b["times"][i] - timedelta(hours=1), b["times"][i + 5], s)
    return {"day": best_day, "six": best6}


def compare_prev(locs, fc, prev, now) -> list[dict] | None:
    if not prev:
        return None
    out = []
    for loc in locs:
        cur, old = base(fc, loc.key), (prev.get(loc.key) or {}).get(BASE_MODEL)
        if not old:
            continue
        om = {t: v for t, v in zip(old["times"], old["precip"])}
        common = [(v, om[t], t) for t, v in zip(cur["times"], cur["precip"]) if t in om]
        if not common:
            continue
        c_all = sum(a or 0 for a, _, _ in common)
        o_all = sum(b or 0 for _, b, _ in common)
        c24 = sum(a or 0 for a, _, t in common if t <= now + timedelta(hours=24))
        o24 = sum(b or 0 for _, b, t in common if t <= now + timedelta(hours=24))
        dd = defaultdict(lambda: [0.0, 0.0])
        for a, b, t in common:
            dd[pdate(t)][0] += a or 0
            dd[pdate(t)][1] += b or 0
        big = max(dd.items(), key=lambda kv: abs(kv[1][0] - kv[1][1]))
        out.append({"loc": loc.name, "all": (round(o_all, 1), round(c_all, 1)),
                    "h24": (round(o24, 1), round(c24, 1)),
                    "big_day": (big[0], round(big[1][1], 1), round(big[1][0], 1)), "hours": len(common)})
    return out


def spread_d57(locs, mdl: dict, run_date: date) -> list[dict]:
    """第 5–7 天：各模型日雨量的最小～最大（量化不確定性）。"""
    days = [run_date + timedelta(days=k) for k in (4, 5, 6)]
    out = []
    for loc in locs:
        vals = []
        for m, dl in mdl.items():
            v = dl.get(loc.key, {})
            if all(d in v for d in days):
                vals.append((m, sum(v[d]["mm"] for d in days)))
        if len(vals) >= 2:
            lo, hi = min(vals, key=lambda x: x[1]), max(vals, key=lambda x: x[1])
            out.append({"loc": loc.name, "n": len(vals), "min": (lo[0], round(lo[1], 1)),
                        "max": (hi[0], round(hi[1], 1))})
    return out


def fmt(v, unit="", nd=1, none="—"):
    if v is None:
        return none
    return f"{v:.{nd}f}{unit}" if isinstance(v, float) else f"{v}{unit}"


def build_text(ctx: dict) -> str:
    now: datetime = ctx["now"]
    L = []
    L.append(f"## 台灣北部降雨預報｜{now:%Y/%m/%d %H:%M} 更新")
    L.append("")
    L.append("### 1. 接下來 2–6 小時")
    for r in ctx["near"]:
        u = "、".join(r["umbrella"]) if r["umbrella"] else "無需特別帶傘"
        L.append(f"- **{r['loc']}**：風險{r['risk']}（最高機率 {fmt(r['pmax'], '%', 0)}，"
                 f"6 小時累積 {r['mm']:.1f} mm）；建議帶傘：{u}")
    if ctx.get("realtime"):
        L.append("- 即時實測（最近雨量站）：" + "；".join(ctx["realtime"]))
    if ctx.get("radar"):
        L.append(f"- 雷達：{ctx['radar']}")
    L.append("")
    L.append("### 2. 今日剩餘預估雨量")
    if all(r["hours"] == 0 for r in ctx["today"]):
        L.append("- 今日已無剩餘時段。")
    else:
        L.append("- " + "、".join(f"{r['loc']} {r['mm']:.1f} mm" for r in ctx["today"]))
    L.append("")
    L.append("### 3. 未來 7 天雨勢較明顯的日期")
    L.append(f"（門檻：任一地點日雨量 ≥ {NOTABLE_DAY_MM:g} mm 或逐時機率 ≥ {NOTABLE_DAY_PROB}%）")
    if ctx["notable"]:
        for n in ctx["notable"]:
            top = "、".join(f"{a} {b:.1f} mm" for a, b in n["top"])
            tag = "（非完整日）" if n["partial"] else ""
            L.append(f"- {md(n['date'])}{tag}：最高機率 {n['pmax']:.0f}%；{top}")
    else:
        L.append("- 未來 7 天沒有達門檻的日期。")
    L.append("")
    L.append("### 4. 預估雨量最高")
    pk = ctx["peaks"]
    if pk["day"]:
        L.append(f"- 最大日雨量：**{pk['day'][0]}** {md(pk['day'][1])}，{pk['day'][2]:.1f} mm")
    if pk["six"]:
        a = pk["six"]
        L.append(f"- 最大 6 小時累積：**{a[0]}** {a[1]:%m/%d %H:%M}–{a[2]:%H:%M}，{a[3]:.1f} mm")
    L.append("")
    L.append("### 5. 與上次預報相比")
    cp = ctx["compare"]
    if cp is None:
        L.append("- 首次成功執行（或無前次紀錄），無法比較。")
    else:
        L.append(f"- 上次預報：{ctx['prev_time']}")
        for c in cp:
            d_all = c["all"][1] - c["all"][0]
            d24 = c["h24"][1] - c["h24"][0]
            bd = c["big_day"]
            L.append(f"- {c['loc']}：重疊期間總量 {c['all'][0]:.1f} → {c['all'][1]:.1f} mm（{d_all:+.1f}）；"
                     f"未來 24h {c['h24'][0]:.1f} → {c['h24'][1]:.1f} mm（{d24:+.1f}）；"
                     f"變化最大 {md(bd[0])} {bd[1]:.1f} → {bd[2]:.1f} mm")
    L.append("")
    L.append("### 6. 資料時間、來源與不確定性")
    L.append(f"- 下載時間：{ctx['fetched_at']}；基準：Open-Meteo Best Match（逐時機率與雨量）")
    if ctx.get("model_init"):
        L.append(f"- 模型初始化時間：{ctx['model_init']}")
    L.append(f"- 比較模型：成功 {len(ctx['models_ok']) - 1} 個（{', '.join(m for m in ctx['models_ok'] if m != BASE_MODEL) or '無'}）"
             + (f"；失敗／無資料：{', '.join(ctx['models_failed'])}" if ctx["models_failed"] else ""))
    L.append(f"- 氣象署資料：{ctx['cwa_status']}")
    L.append(f"- 校正狀態：{ctx['calib_summary']}")
    if ctx["spread"]:
        s = "；".join(f"{x['loc']} {x['min'][1]:.1f}–{x['max'][1]:.1f} mm（{x['n']} 模型）" for x in ctx["spread"])
        L.append(f"- 第 5–7 天各模型三日總雨量差距：{s}")
    L.append("- 第 5–7 天預報的降雨時間與雨量不確定性高，只宜作為趨勢參考，請以後續更新為準。")
    L.append("- AccuWeather：尚未安裝成功，未作為備援。")
    return "\n".join(L)
