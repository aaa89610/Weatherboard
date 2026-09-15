"""實測配對、分地點／提前時間驗證、校正訓練與獨立驗證閘門。"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta

from .config import (BASE_MODEL, CALIB_BOOT, CALIB_MIN_IMPROVE, CALIB_MIN_TEST, CALIB_MIN_TRAIN,
                     CALIB_MIN_TEST_DAYS, CALIB_MIN_WET_TEST, VERIFY_DAYS, EVENT_MM, HORIZON_H, LEAD_BUCKETS, STATION_MAX_KM, TZ)
from .store import Store, iso, parse

PAST_K = [1, 3, 6, 12, 24]
MODEL_PAIR_HOURS = {7}      # 比較模型只配對 07 時發布的預報，控制資料量
SNAP_TOL_MIN = 15           # 快照時間距整點 ±15 分鐘內才採用


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bucket_of(lead_h: float) -> str | None:
    for name, lo, hi in LEAD_BUCKETS:
        if lo < lead_h <= hi:
            return name
    return None


def nearest_stations(locs, stations, max_km=STATION_MAX_KM, k=3) -> dict:
    out = {}
    for loc in locs:
        ds = sorted(((haversine_km(loc.lat, loc.lon, s["lat"], s["lon"]), s) for s in stations),
                    key=lambda x: x[0])
        out[loc.key] = [(round(d, 2), s) for d, s in ds[:k] if d <= max_km]
    return out


# ---------------- 實測視窗 ----------------
def _hour_snap(s: dict):
    t = s["obs_time"]
    r = (t + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
    off = abs((t - r).total_seconds()) / 60
    # 超出容許偏移，或 23:5x 進位到隔天 00:00（本日累積語意會錯）→ 捨棄
    if off > SNAP_TOL_MIN or r.date() != t.date():
        return None, off
    return r, off


def windows_from_snaps(snaps: list[dict]) -> list[tuple]:
    """由連續快照推出區間雨量。回傳 (t_start, t_end, mm, method, qc)。"""
    by_hour = {}
    for s in snaps:
        h, off = _hour_snap(s)
        if h is not None and (h not in by_hour or off < by_hour[h][1]):
            by_hour[h] = (s, off)
    hours = sorted(by_hour)
    out = []
    for a, b in zip(hours, hours[1:]):
        sa, oa = by_hour[a]
        sb, ob = by_hour[b]
        gap = (b - a).total_seconds() / 3600
        if gap <= 0 or gap > 24:
            continue
        off_note = "" if max(oa, ob) == 0 else f"(偏移{int(max(oa, ob))}分)"
        mm, method = None, None
        if a.date() == b.date() and sa.get("now") is not None and sb.get("now") is not None:
            mm, method = sb["now"] - sa["now"], "本日累積差"
        else:
            k = next((k for k in PAST_K if k >= gap), None)
            pk = sb.get({1: "p1h", 3: "p3h", 6: "p6h", 12: "p12h", 24: "p24h"}[k]) if k else None
            if pk is not None:
                c = b - timedelta(hours=k)
                if c == a:
                    mm, method = pk, f"過去{k}小時"
                elif c < a and c.date() == a.date() and c in by_hour and \
                        by_hour[c][0].get("now") is not None and sa.get("now") is not None:
                    mm, method = pk - (sa["now"] - by_hour[c][0]["now"]), f"過去{k}小時扣除"
        if mm is None:
            continue
        qc = "ok"
        if mm < -0.05:
            qc = "負值"
        elif sb.get("p1h") is not None and gap >= 1 and mm + 0.05 < sb["p1h"]:
            qc = "小於過去1小時"
        elif gap <= 3 and sb.get("p3h") is not None and mm > sb["p3h"] + 0.15:
            qc = "大於過去3小時"
        out.append((a, b, round(max(mm, 0.0), 1), method, qc + (off_note if qc == "ok" else "")))
    return out


def update_windows(store: Store, locs, loc_st: dict, since: datetime) -> int:
    rows = []
    for loc in locs:
        for dist, st in loc_st.get(loc.key, []):
            for a, b, mm, method, qc in windows_from_snaps(store.snaps_for(st["station_id"], since)):
                rows.append((loc.key, st["station_id"], dist, iso(a), iso(b), mm, method, qc))
    # 依距離排序插入，同一視窗以最近測站優先（PRIMARY KEY 忽略重複）
    rows.sort(key=lambda r: r[2])
    return store.save_windows(rows)


# ---------------- 配對 ----------------
def update_pairs(store: Store, since: datetime) -> int:
    wins = [w for w in store.windows(since) if w["qc"].startswith("ok")]
    if not wins:
        return 0
    cache: dict = {}
    rows = []
    for w in wins:
        ts, te = parse(w["t_start"]), parse(w["t_end"])
        n_h = int(round((te - ts).total_seconds() / 3600))
        for run_id, rt in store.runs_between(te - timedelta(hours=HORIZON_H), ts):
            if run_id not in cache:
                cache[run_id] = store.load_run(run_id)
            loc_fc = cache[run_id].get(w["loc"], {})
            for model, s in loc_fc.items():
                if model != BASE_MODEL and rt.hour not in MODEL_PAIR_HOURS:
                    continue
                idx = [i for i, t in enumerate(s["times"]) if ts < t <= te]
                if len(idx) != n_h or s["precip"] is None:
                    continue
                vals = [s["precip"][i] for i in idx]
                if any(v is None for v in vals):
                    continue
                prob = None
                if s["prob"] is not None:
                    ps = [s["prob"][i] for i in idx if s["prob"][i] is not None]
                    prob = max(ps) if ps else None
                lead = (te - rt).total_seconds() / 3600
                rows.append((w["loc"], run_id, model, w["t_start"], w["t_end"], round(lead, 2),
                             round(sum(vals), 2), prob, w["mm"]))
    return store.save_pairs(rows)


# ---------------- 驗證指標 ----------------
def metrics(pairs: list[dict]) -> dict:
    n = len(pairs)
    if n == 0:
        return {"n": 0}
    err = [p["fc_mm"] - p["obs_mm"] for p in pairs]
    hits = sum(1 for p in pairs if p["fc_mm"] >= EVENT_MM and p["obs_mm"] >= EVENT_MM)
    miss = sum(1 for p in pairs if p["fc_mm"] < EVENT_MM and p["obs_mm"] >= EVENT_MM)
    fa = sum(1 for p in pairs if p["fc_mm"] >= EVENT_MM and p["obs_mm"] < EVENT_MM)
    pp = [p for p in pairs if p["fc_prob"] is not None]
    brier = (sum((p["fc_prob"] / 100 - (1.0 if p["obs_mm"] >= EVENT_MM else 0.0)) ** 2 for p in pp)
             / len(pp)) if pp else None
    return {
        "n": n, "n_wet_obs": hits + miss,
        "mae": sum(abs(e) for e in err) / n,
        "bias": sum(err) / n,
        "rmse": math.sqrt(sum(e * e for e in err) / n),
        "obs_mean": sum(p["obs_mm"] for p in pairs) / n,
        "fc_mean": sum(p["fc_mm"] for p in pairs) / n,
        "pod": hits / (hits + miss) if hits + miss else None,
        "far": fa / (hits + fa) if hits + fa else None,
        "csi": hits / (hits + miss + fa) if hits + miss + fa else None,
        "brier": brier, "n_prob": len(pp),
    }


def verification_table(store: Store, locs, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(TZ)
    by = defaultdict(list)
    for p in store.pairs(since=now - timedelta(days=VERIFY_DAYS)):
        b = bucket_of(p["lead_h"])
        if b:
            by[(p["loc"], b, p["model"])].append(p)
    out = []
    for loc in locs:
        for b, _, _ in LEAD_BUCKETS:
            models = sorted({k[2] for k in by if k[0] == loc.key and k[1] == b},
                            key=lambda m: (m != BASE_MODEL, m))
            if not models:
                out.append({"loc": loc.key, "loc_name": loc.name, "bucket": b, "model": BASE_MODEL, "n": 0})
            for m in models:
                out.append({"loc": loc.key, "loc_name": loc.name, "bucket": b, "model": m,
                            **metrics(by[(loc.key, b, m)])})
    return out


# ---------------- 校正（時間切分獨立驗證） ----------------
def _fit_factor(ps):
    so, sf = sum(p["obs_mm"] for p in ps), sum(p["fc_mm"] for p in ps)
    return min(2.0, max(0.5, (so + 10.0) / (sf + 10.0)))


def evaluate_calibration(ps: list[dict], seed: int = 42) -> dict:
    days = sorted({p["t_end"][:10] for p in ps})
    res = {"factor": None, "n_train": 0, "n_test": 0, "n_wet_test": 0, "mae_raw": None,
           "mae_cal": None, "improve": None, "ci_low": None, "enabled": 0}
    if len(days) < 4:
        res["status"] = f"校正待驗證（實測天數 {len(days)}，樣本不足）"
        return res
    cut = days[int(len(days) * 0.7)]
    train = [p for p in ps if p["t_end"][:10] < cut]
    test = [p for p in ps if p["t_end"][:10] >= cut]
    n_test_days = len({p["t_end"][:10] for p in test})
    f = _fit_factor(train)
    wet = sum(1 for p in test if p["obs_mm"] >= 1.0 or p["fc_mm"] >= 1.0)
    res.update(factor=round(f, 3), n_train=len(train), n_test=len(test), n_wet_test=wet)
    if (len(train) < CALIB_MIN_TRAIN or len(test) < CALIB_MIN_TEST or wet < CALIB_MIN_WET_TEST
            or n_test_days < CALIB_MIN_TEST_DAYS):
        res["status"] = (f"校正待驗證（訓練 {len(train)}/{CALIB_MIN_TRAIN}、測試 {len(test)}/{CALIB_MIN_TEST}、"
                         f"測試天數 {n_test_days}/{CALIB_MIN_TEST_DAYS}、測試期有雨視窗 {wet}/{CALIB_MIN_WET_TEST}）")
        return res
    raw = [abs(p["fc_mm"] - p["obs_mm"]) for p in test]
    cal = [abs(p["fc_mm"] * f - p["obs_mm"]) for p in test]
    mae_raw, mae_cal = sum(raw) / len(raw), sum(cal) / len(cal)
    imp = (mae_raw - mae_cal) / mae_raw if mae_raw > 0 else 0.0
    # 依日區塊 bootstrap 改善量
    by_day = defaultdict(list)
    for p, r_, c_ in zip(test, raw, cal):
        by_day[p["t_end"][:10]].append(r_ - c_)
    keys = list(by_day)
    rng = random.Random(seed)
    boots = []
    for _ in range(CALIB_BOOT):
        smp = [d for _ in keys for d in by_day[rng.choice(keys)]]
        boots.append(sum(smp) / len(smp))
    boots.sort()
    ci_low = boots[int(0.025 * len(boots))]
    ok = imp >= CALIB_MIN_IMPROVE and ci_low > 0
    res.update(mae_raw=round(mae_raw, 3), mae_cal=round(mae_cal, 3), improve=round(imp, 4),
               ci_low=round(ci_low, 4), enabled=int(ok))
    if ok:
        res["status"] = f"已啟用（獨立測試期 MAE 改善 {imp:.0%}，95% 下界 {ci_low:+.3f} mm，係數 {f:.2f}）"
    elif imp >= CALIB_MIN_IMPROVE:
        res["status"] = f"未啟用（測試期 MAE 改善 {imp:.0%}，但依日 bootstrap 95% 下界 {ci_low:+.3f} mm ≤ 0，不夠穩定）"
    else:
        res["status"] = f"未啟用（測試期 MAE {'改善' if imp >= 0 else '變差'} {abs(imp):.0%}，未達 {CALIB_MIN_IMPROVE:.0%} 門檻）"
    return res


def update_calibration(store: Store, locs, now: datetime | None = None) -> dict:
    now = now or datetime.now(TZ)
    by = defaultdict(list)
    for p in store.pairs(BASE_MODEL, since=now - timedelta(days=VERIFY_DAYS)):
        b = bucket_of(p["lead_h"])
        if b:
            by[(p["loc"], b)].append(p)
    stamp = now.isoformat(timespec="minutes")
    rows = []
    for loc in locs:
        for b, _, _ in LEAD_BUCKETS:
            r = evaluate_calibration(by.get((loc.key, b), []))
            rows.append((loc.key, b, BASE_MODEL, r["factor"], r["n_train"], r["n_test"], r["n_wet_test"],
                         r["mae_raw"], r["mae_cal"], r["improve"], r["ci_low"], r["enabled"],
                         r["status"], stamp))
    store.save_calib(rows)
    return store.calib()


def calib_factor(calib: dict, loc: str, lead_h: float) -> float | None:
    b = bucket_of(lead_h)
    c = calib.get((loc, b, BASE_MODEL)) if b else None
    return c["factor"] if c and c["enabled"] else None
