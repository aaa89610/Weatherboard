"""單元測試（合成資料）：校正閘門、特殊值解析、編碼。"""
import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rain_pipeline.verify import evaluate_calibration
from rain_pipeline.src_cwa import parse_value
from rain_pipeline.store import enc, dec

rng = random.Random(1)
def mk(scale, days=30, noise=0.3):
    ps = []
    for d in range(days):
        for w in range(8):
            obs = max(0, rng.gauss(2, 2)) if rng.random() < 0.4 else 0.0
            ps.append({"t_end": f"2026-08-{d+1:02d}T{7+2*w:02d}:00", "obs_mm": round(obs, 1),
                       "fc_mm": max(0, obs * scale + rng.gauss(0, noise))})
    return ps
a = evaluate_calibration(mk(0.5)); print("系統性低估 → ", a["enabled"], a["status"])
b = evaluate_calibration(mk(1.0)); print("無偏差     → ", b["enabled"], b["status"])
c = evaluate_calibration(mk(0.5, days=10)); print("天數不足   → ", c["enabled"], c["status"])
assert a["enabled"] == 1 and b["enabled"] == 0 and c["enabled"] == 0
assert parse_value({"Precipitation": -98}) == 0.0 and parse_value("T") == 0.0
assert parse_value(-99) is None and parse_value("X") is None and parse_value({"Precipitation": "3.5"}) == 3.5
assert dec(enc([0.0, 1.2, None, 55.5])) == [0.0, 1.2, None, 55.5]
print("單元測試全部通過")
