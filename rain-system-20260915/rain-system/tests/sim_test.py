"""離線模擬測試（全部為合成資料，僅驗證程式邏輯，不代表真實天氣）。

模擬 N 天、每天 07–21 每 2 小時執行一次：
- 「真值」逐時雨量隨機產生；Best Match 故意低估為真值 × 0.6（加雜訊），校正應學到約 1.6 倍並通過獨立驗證。
- 雨量站快照依真值計算「本日累積／過去 N 小時」。
用法：python tests/sim_test.py <空的測試資料夾> [天數]
"""
import json
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rain_pipeline.config import DEFAULT_LOCATIONS, TZ  # noqa: E402

root = Path(sys.argv[1])
days = int(sys.argv[2]) if len(sys.argv) > 2 else 12
root.mkdir(parents=True, exist_ok=True)
rng = random.Random(7)
t0 = datetime(2026, 8, 1, 0, 0, tzinfo=TZ)
H = (days + 10) * 24
truth = {}
for loc in DEFAULT_LOCATIONS:
    s = [0.0] * H
    h = 0
    while h < H:
        h += rng.randint(6, 40)
        dur, inten = rng.randint(2, 7), rng.uniform(0.5, 6)
        for k in range(dur):
            if h + k < H:
                s[h + k] = round(inten * rng.uniform(0.3, 1.2), 1)
    truth[loc.key] = s   # s[i] = 小時 (t0+i, t0+i+1] 的雨量，時間戳記為 t0+i+1


def tv(key, t_end):
    i = int((t_end - t0).total_seconds() // 3600) - 1
    return truth[key][i] if 0 <= i < H else 0.0


fx = root / "_fixtures"
fx.mkdir(exist_ok=True)
(fx / "truth.json").write_text(json.dumps({"t0": t0.isoformat(), "truth": truth}), encoding="utf-8")
results = []
for d in range(days):
    for hr in range(7, 22, 2):
        now = t0 + timedelta(days=d, hours=hr)
        fc = {}
        for loc in DEFAULT_LOCATIONS:
            times = [now + timedelta(hours=i) for i in range(1, 9 * 24)]
            def noisy(scale, lead_noise):
                out = []
                for i, t in enumerate(times):
                    v = tv(loc.key, t) * scale + max(0.0, rng.gauss(0, 0.2 + lead_noise * i / 168))
                    out.append(round(max(v, 0.0), 1))
                return out
            base = noisy(0.6, 0.6)
            prob = [min(100, int(20 + 15 * v)) if v > 0.2 else rng.randint(0, 15) for v in base]
            fc[loc.key] = {
                "best_match": {"times": [t.isoformat() for t in times], "precip": base, "prob": prob},
                "gfs_seamless": {"times": [t.isoformat() for t in times], "precip": noisy(0.9, 1.0)},
                "ecmwf_ifs025": {"times": [t.isoformat() for t in times], "precip": noisy(1.1, 0.8)},
            }
        (fx / "fc.json").write_text(json.dumps({"fc": fc}), encoding="utf-8")
        # 雨量站快照：每地點 2 站（距離 1–4 km）
        stations = []
        for j, loc in enumerate(DEFAULT_LOCATIONS):
            for k, (dlat, dlon) in enumerate([(0.01, 0.0), (-0.02, 0.02)]):
                obs_t = now - timedelta(minutes=10 if (d + hr) % 5 == 0 else 0)
                day0 = obs_t.replace(hour=0, minute=0)
                def acc(hours):
                    return round(sum(tv(loc.key, now - timedelta(hours=q)) for q in range(hours)), 1)
                nowacc = round(sum(tv(loc.key, day0 + timedelta(hours=q + 1)) for q in range(now.hour)), 1)
                rain = {"Now": {"Precipitation": nowacc}, "Past10Min": {"Precipitation": 0.0},
                        "Past1hr": {"Precipitation": acc(1)}, "Past3hr": {"Precipitation": acc(3)},
                        "Past6Hr": {"Precipitation": acc(6)}, "Past12hr": {"Precipitation": acc(12)},
                        "Past24hr": {"Precipitation": acc(24) if acc(24) > 0 else -98}}
                stations.append({"StationName": f"測試{j}{k}", "StationId": f"T{j}{k}",
                                 "ObsTime": {"DateTime": obs_t.isoformat()},
                                 "GeoInfo": {"CountyName": "測試", "TownName": "測試",
                                             "Coordinates": [{"CoordinateName": "WGS84",
                                                              "StationLatitude": loc.lat + dlat,
                                                              "StationLongitude": loc.lon + dlon}]},
                                 "RainfallElement": rain})
        (fx / "obs.json").write_text(json.dumps({"success": "true", "records": {"Station": stations}},
                                                ensure_ascii=False), encoding="utf-8")
        p = subprocess.run([sys.executable, "-m", "rain_pipeline.run", "--root", str(root), "--now", now.isoformat(),
                            "--fixture", str(fx / "fc.json"), "--obs-fixture", str(fx / "obs.json")],
                           capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
        summ = json.loads(p.stdout.split("@@SUMMARY@@ ")[-1]) if "@@SUMMARY@@" in p.stdout else {}
        results.append((now.isoformat(), p.returncode, summ.get("steps", {}).get("cwa"),
                        (summ.get("steps", {}).get("excel") or {}).get("ok")))
        if p.returncode != 0:
            print(p.stdout[-2000:], p.stderr[-3000:])
            sys.exit(1)
    print(results[-1])
print("runs:", len(results), "all ok:", all(r[1] == 0 for r in results))
