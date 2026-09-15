"""中央氣象署開放資料：自動雨量站即時雨量（O-A0002-001）與雷達整合回波圖（O-A0058-003）。

輸出（與其他模組的介面）：
    stations: [{"station_id","name","county","town","lat","lon","alt"}]
    snapshots: [{"station_id","obs_time"(datetime TZ),"now","p10m","p1h","p3h","p6h","p12h","p24h"}]
特殊值：-98 = 連續 6 小時無降水 → 0.0；T（雨跡）→ 0.0；-99 / X / 其他負值 → None（缺值）。
"""
from __future__ import annotations

import re
from datetime import datetime

from .config import TZ
from .net import FetchError, get_bytes, get_json

DATASTORE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/{id}"
FILEAPI = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/{id}"

FIELD_MAP = {"now": "now", "past10min": "p10m", "past1hr": "p1h", "past3hr": "p3h",
             "past6hr": "p6h", "past12hr": "p12h", "past24hr": "p24h"}


def parse_value(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("Precipitation", v.get("precipitation"))
    if v is None:
        return None
    s = str(v).strip()
    if s.upper() == "T":
        return 0.0
    try:
        x = float(s)
    except ValueError:
        return None
    if x == -98:
        return 0.0
    if x < 0:
        return None
    return x


def _wgs84(geo: dict) -> tuple[float | None, float | None]:
    coords = geo.get("Coordinates") or []
    for c in coords:
        if str(c.get("CoordinateName", "")).upper() == "WGS84":
            return float(c["StationLatitude"]), float(c["StationLongitude"])
    if coords:
        return float(coords[-1]["StationLatitude"]), float(coords[-1]["StationLongitude"])
    return None, None


def parse_rain_obs(data: dict) -> tuple[list[dict], list[dict]]:
    recs = (data.get("records") or {}).get("Station") or []
    stations, snaps = [], []
    for st in recs:
        geo = st.get("GeoInfo") or {}
        lat, lon = _wgs84(geo)
        if lat is None:
            continue
        sid = st.get("StationId")
        stations.append({"station_id": sid, "name": st.get("StationName"),
                         "county": geo.get("CountyName"), "town": geo.get("TownName"),
                         "lat": lat, "lon": lon, "alt": geo.get("StationAltitude")})
        t = (st.get("ObsTime") or {}).get("DateTime")
        if not t:
            continue
        obs_time = datetime.fromisoformat(t).astimezone(TZ)
        rain = st.get("RainfallElement") or {}
        snap = {"station_id": sid, "obs_time": obs_time}
        for k, v in rain.items():
            key = FIELD_MAP.get(k.lower())
            if key:
                snap[key] = parse_value(v)
        snaps.append(snap)
    return stations, snaps


def fetch_rain_obs(api_key: str) -> tuple[list[dict], list[dict]]:
    if not api_key:
        raise FetchError("CWA", "no_api_key", "尚未設定氣象署授權碼（config/settings.json 的 cwa_api_key）")
    data = get_json(DATASTORE.format(id="O-A0002-001"),
                    {"Authorization": api_key, "format": "JSON"}, "CWA 雨量站", timeout=40)
    if str(data.get("success")).lower() != "true":
        raise FetchError("CWA 雨量站", "bad_response", str(data)[:200])
    return parse_rain_obs(data)


def fetch_radar(api_key: str, save_to) -> dict:
    """雷達整合回波圖：回傳 {"time","url","saved"}；失敗丟 FetchError。"""
    if not api_key:
        raise FetchError("CWA", "no_api_key", "尚未設定氣象署授權碼")
    data = get_json(FILEAPI.format(id="O-A0058-003"),
                    {"Authorization": api_key, "format": "JSON"}, "CWA 雷達", timeout=30)
    text = str(data)
    url = next(iter(re.findall(r"https?://[^'\"\s]+?\.(?:png|jpg|jpeg)", text)), None)
    tm = next(iter(re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00", text)), None)
    out = {"time": tm, "url": url, "saved": None}
    if url and save_to is not None:
        try:
            save_to.parent.mkdir(parents=True, exist_ok=True)
            save_to.write_bytes(get_bytes(url, "CWA 雷達圖檔"))
            out["saved"] = str(save_to)
        except FetchError as e:
            out["image_error"] = f"{e.kind}: {e.detail[:100]}"
    return out
