"""檢查模擬結果：實測視窗是否等於真值、配對是否正確、校正是否依閘門啟用。"""
import json, sqlite3, sys
from datetime import datetime
from pathlib import Path
root = Path(sys.argv[1])
tr = json.loads((root / "_fixtures" / "truth.json").read_text())
t0 = datetime.fromisoformat(tr["t0"]); truth = tr["truth"]
db = sqlite3.connect(root / "data" / "rain.sqlite")
bad = 0; n = 0
for loc, ts, te, mm, qc in db.execute("select loc,t_start,t_end,mm,qc from obs_win"):
    a = int((datetime.fromisoformat(ts) - t0).total_seconds() // 3600)
    b = int((datetime.fromisoformat(te) - t0).total_seconds() // 3600)
    exp = round(sum(truth[loc][a:b]), 1); n += 1
    if abs(exp - mm) > 0.15: bad += 1; print("窗口不符", loc, ts, te, mm, exp, qc)
print(f"實測視窗 {n} 筆，不符 {bad} 筆")
print("配對數（依模型）:", db.execute("select model,count(*) from pairs group by model").fetchall())
for r in db.execute("select loc,bucket,factor,n_train,n_test,n_wet_test,mae_raw,mae_cal,improve,ci_low,enabled,status from calib order by loc,bucket"):
    print(r)
