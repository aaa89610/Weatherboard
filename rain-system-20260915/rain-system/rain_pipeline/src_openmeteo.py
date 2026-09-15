"""Open-Meteo 資料源：Best Match 基準 + 多模型比較 + 模型更新時間 + 過去各提前時間預報（回測用）。

輸出格式（與其他模組的唯一介面）：
    {loc_key: {model: {"times": [datetime(TZ)...], "precip": [float|None], "prob": [float|None] | None}}}
逐時值為「前一小時累積」（hour-ending），times 為該小時結束時間（台灣時間）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .config import BASE_MODEL, COMPARE_MODELS, HORIZON_H, TZ, Location
from .net import FetchError, get_json

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
META_URL = "https://api.open-meteo.com/data/{name}/static/meta.json"
META_NAMES = ["ecmwf_ifs025", "ncep_gfs025", "dwd_icon", "jma_gsm", "jma_msm",
              "cma_grapes_global", "kma_gdps", "ukmo_global_deterministic_10km"]


def _coords(locs: list[Location]) -> dict:
    return {"latitude": ",".join(f"{l.lat:.4f}" for l in locs),
            "longitude": ",".join(f"{l.lon:.4f}" for l in locs)}


def _parse_times(ts: list[str]) -> list[datetime]:
    return [datetime.fromisoformat(t).replace(tzinfo=TZ) for t in ts]


def _pick(hourly: dict, var: str, model: str, single: bool):
    keys = (var, f"{var}_{model}") if single else (f"{var}_{model}",)
    for k in keys:
        if k in hourly:
            return hourly[k]
    return None


def _slice(series: dict, now: datetime) -> dict:
    idx = [i for i, t in enumerate(series["times"]) if t > now][:HORIZON_H]
    out = {"times": [series["times"][i] for i in idx],
           "precip": [series["precip"][i] for i in idx] if series["precip"] else None,
           "prob": [series["prob"][i] for i in idx] if series["prob"] else None}
    if out["prob"] is not None and all(v is None for v in out["prob"]):
        out["prob"] = None
    return out


def _request_models(locs, models: list[str], now: datetime) -> dict:
    params = {**_coords(locs), "hourly": "precipitation_probability,precipitation",
              "models": ",".join(models), "timezone": "Asia/Taipei",
              "forecast_days": 9, "precipitation_unit": "mm"}
    data = get_json(FORECAST_URL, params, "Open-Meteo")
    items = data if isinstance(data, list) else [data]
    if len(items) != len(locs):
        raise FetchError("Open-Meteo", "bad_response", f"預期 {len(locs)} 個地點，實得 {len(items)}")
    out: dict = {}
    single = len(models) == 1
    for loc, item in zip(locs, items):
        hourly = item.get("hourly") or {}
        times = _parse_times(hourly.get("time", []))
        out[loc.key] = {}
        for m in models:
            p = _pick(hourly, "precipitation", m, single)
            if p is None or all(v is None for v in p):
                continue
            prob = _pick(hourly, "precipitation_probability", m, single)
            out[loc.key][m] = _slice({"times": times, "precip": p, "prob": prob}, now)
    return out


def fetch_forecasts(locs: list[Location], now: datetime) -> tuple[dict, dict]:
    """回傳 (forecasts, info)。Best Match 失敗會丟例外；比較模型失敗只記錄。"""
    info = {"models_ok": [], "models_failed": {}, "fetched_at": datetime.now(TZ).isoformat()}
    fc = _request_models(locs, [BASE_MODEL], now)
    for loc in locs:
        s = fc[loc.key].get(BASE_MODEL)
        if not s or len(s["times"]) < HORIZON_H:
            n = len(s["times"]) if s else 0
            raise FetchError("Open-Meteo", "incomplete", f"{loc.name} Best Match 只有 {n}/{HORIZON_H} 小時")
    info["models_ok"].append(BASE_MODEL)

    def merge(part: dict):
        for k, v in part.items():
            fc[k].update(v)

    try:
        merge(_request_models(locs, COMPARE_MODELS, now))
    except FetchError as e:
        if e.kind == "network_blocked":
            raise
        for m in COMPARE_MODELS:          # 逐一重試，找出哪個模型不可用
            try:
                merge(_request_models(locs, [m], now))
            except FetchError as e2:
                info["models_failed"][m] = f"{e2.kind}: {e2.detail[:120]}"
    for m in COMPARE_MODELS:
        if m in info["models_failed"]:
            continue
        if any(m in fc[l.key] for l in locs):
            info["models_ok"].append(m)
        else:
            info["models_failed"][m] = "無資料（該區域或期間不提供）"
    return fc, info


def fetch_model_meta() -> dict:
    """各模型最近一次初始化／可用時間（best effort，失敗不影響主流程）。"""
    meta = {}
    for name in META_NAMES:
        try:
            d = get_json(META_URL.format(name=name), None, "Open-Meteo meta", timeout=10, retries=1)
            init = d.get("last_run_initialisation_time")
            avail = d.get("last_run_availability_time")
            meta[name] = {
                "init": datetime.fromtimestamp(init, TZ).isoformat() if init else None,
                "available": datetime.fromtimestamp(avail, TZ).isoformat() if avail else None,
            }
        except (FetchError, ValueError, TypeError, AttributeError):
            continue
    return meta


def fetch_previous_runs(loc: Location, past_days: int = 30, model: str = BASE_MODEL) -> dict:
    """過去 N 天，每小時「0～7 天前所發布預報」對該小時的預測值；用於依提前天數回測。"""
    vars_ = ["precipitation"] + [f"precipitation_previous_day{d}" for d in range(1, 8)]
    params = {"latitude": loc.lat, "longitude": loc.lon, "hourly": ",".join(vars_),
              "past_days": past_days, "forecast_days": 1, "timezone": "Asia/Taipei",
              "models": model}
    d = get_json(PREVIOUS_RUNS_URL, params, "Open-Meteo previous-runs")
    h = d.get("hourly") or {}
    out = {"times": _parse_times(h.get("time", []))}
    for v in vars_:
        out[v] = h.get(v) or h.get(f"{v}_{model}")
    return out
