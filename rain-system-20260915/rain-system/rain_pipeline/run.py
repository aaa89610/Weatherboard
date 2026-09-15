"""主流程：python -m rain_pipeline.run --root <資料夾>

步驟：氣象署實測 → 配對／驗證／校正 → Open-Meteo 預報 → 保存原始預報 → 文字分析 → Excel（失敗保留原檔）。
輸出：stdout 最後一行為 JSON 摘要；reports/latest.md 為本次繁體中文分析。
結束碼：0 成功；2 預報下載失敗（Excel 未更動）；3 Excel 寫入失敗（原檔保留）。
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from . import report as R
from .config import (BASE_MODEL, COMPARE_MODELS, EVENT_MM, HORIZON_H, LEAD_BUCKETS, NOTABLE_DAY_MM,
                     NOTABLE_DAY_PROB, STATION_MAX_KM, TZ, UMBRELLA_MM, UMBRELLA_PROB, load_settings)
from .excel_writer import build_workbook, safe_write
from .net import FetchError
from .src_cwa import fetch_radar, fetch_rain_obs
from .src_openmeteo import fetch_forecasts, fetch_model_meta
from .store import Store, iso, parse
from .verify import (bucket_of, nearest_stations, update_calibration, update_pairs, update_windows,
                     verification_table)

PAIR_ROWS_MAX = 3000


def run_summary(locs, fc, now) -> dict:
    dly = R.daily(locs, fc)
    near = {r["loc"]: r for r in R.near_term(locs, fc, now)}
    today = {r["loc"]: r for r in R.today_remaining(locs, fc, now)}
    out = {}
    for l in locs:
        b = fc[l.key][BASE_MODEL]
        n24 = sum(v or 0 for t, v in zip(b["times"], b["precip"]) if t <= now + timedelta(hours=24))
        probs = [p for p in (b["prob"] or []) if p is not None]
        md = max(dly[l.key].items(), key=lambda kv: kv[1]["mm"])
        out[l.key] = {"next6": near[l.name]["mm"], "today": today[l.name]["mm"], "next24": round(n24, 1),
                      "total7": round(sum(v or 0 for v in b["precip"]), 1), "pmax": max(probs) if probs else None,
                      "maxday_date": md[0].isoformat(), "maxday_mm": round(md[1]["mm"], 1)}
    return out


def load_fixture(path: Path, locs, now) -> tuple[dict, dict]:
    """測試用：讀取已正規化的預報 JSON（非真實資料，不得用於正式 Excel）。"""
    d = json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_text("utf-8"))
    fc = {}
    for lk, models in d["fc"].items():
        fc[lk] = {}
        for m, s in models.items():
            times = [datetime.fromisoformat(t) for t in s["times"]]
            idx = [i for i, t in enumerate(times) if t > now][:HORIZON_H]
            fc[lk][m] = {"times": [times[i] for i in idx], "precip": [s["precip"][i] for i in idx],
                         "prob": [s["prob"][i] for i in idx] if s.get("prob") else None}
    info = {"models_ok": [BASE_MODEL] + [m for m in COMPARE_MODELS if any(m in fc[k] for k in fc)],
            "models_failed": {}, "fetched_at": now.isoformat(timespec="minutes"), "fixture": str(path)}
    return fc, info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--now", help="測試用：覆寫目前時間 ISO")
    ap.add_argument("--fixture", help="測試用：離線預報檔（非真實資料）")
    ap.add_argument("--obs-fixture", help="測試用：離線氣象署 JSON（非真實資料）")
    ap.add_argument("--skip-cwa", action="store_true")
    a = ap.parse_args(argv)

    S = load_settings(a.root)
    locs = S.locations
    now = datetime.fromisoformat(a.now).astimezone(TZ) if a.now else datetime.now(TZ)
    now = now.replace(second=0, microsecond=0)
    run_id = now.strftime("%Y%m%dT%H%M")
    store = Store(S.db_path)
    if a.fixture and any("fixture" not in (r["status"] or "") for r in store.runs()):
        print("拒絕執行：此資料夾已有真實預報紀錄，測試資料不得寫入正式資料庫。")
        store.close()
        return 4
    log = {"run_id": run_id, "now": now.isoformat(), "steps": {}}
    S.report_dir.mkdir(parents=True, exist_ok=True)
    S.log_path.parent.mkdir(parents=True, exist_ok=True)

    def finish(code: int, text: str | None = None) -> int:
        log["exit_code"] = code
        with S.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log, ensure_ascii=False, default=str) + "\n")
        if text:
            (S.report_dir / "latest.md").write_text(text, encoding="utf-8")
            (S.report_dir / f"{run_id}.md").write_text(text, encoding="utf-8")
            print(text)
        store.close()
        print("\n@@SUMMARY@@ " + json.dumps(log, ensure_ascii=False, default=str))
        return code

    # ---- 1. 氣象署實測（獨立於預報，失敗不影響預報） ----
    cwa_status, realtime, radar_txt = "未設定授權碼：實測配對暫停、校正待驗證", [], None
    loc_st = {}
    if not a.skip_cwa and (S.cwa_api_key or a.obs_fixture):
        try:
            if a.obs_fixture:
                from .src_cwa import parse_rain_obs
                stations, snaps = parse_rain_obs(json.loads(Path(a.obs_fixture).read_text("utf-8")))
            else:
                stations, snaps = fetch_rain_obs(S.cwa_api_key)
            store.save_stations(stations)
            new_snaps = store.save_snaps(snaps)
            loc_st = nearest_stations(locs, stations)
            since = now - timedelta(days=9)
            new_win = update_windows(store, locs, loc_st, since)
            new_pairs = update_pairs(store, now - timedelta(days=2))
            obs_t = max((s["obs_time"] for s in snaps), default=None)
            cwa_status = (f"雨量站 {len(stations)} 站，觀測時間 {obs_t:%m/%d %H:%M}；新增快照 {new_snaps}、"
                          f"實測視窗 {new_win}、配對 {new_pairs}") if obs_t else "雨量站資料為空"
            log["steps"]["cwa"] = {"stations": len(stations), "snaps": new_snaps, "windows": new_win, "pairs": new_pairs}
            latest = {s["station_id"]: s for s in snaps}
            for l in locs:
                for dist, st in loc_st.get(l.key, []):
                    s = latest.get(st["station_id"])
                    if s and s.get("p1h") is not None:
                        realtime.append(f"{l.name}（{st['name']}站 {dist:.1f} km）1h {s['p1h']:.1f}／3h "
                                        f"{(s.get('p3h') or 0):.1f} mm")
                        break
                else:
                    realtime.append(f"{l.name}：{STATION_MAX_KM:g} km 內無可用雨量站資料")
        except FetchError as e:
            cwa_status = f"取得失敗（{e.kind}）：{e.detail[:120]}"
            log["steps"]["cwa"] = {"error": str(e)}
        if S.cwa_api_key and not a.obs_fixture:
            try:
                rd = fetch_radar(S.cwa_api_key, S.data_dir / "radar" / "latest.png")
                radar_txt = f"整合回波圖 {rd.get('time') or '時間未知'}" + ("（已存 data/radar/latest.png）" if rd.get("saved") else
                                                                          f"（圖檔未下載：{rd.get('image_error', '無網址')}）")
                log["steps"]["radar"] = rd
            except FetchError as e:
                radar_txt = f"取得失敗（{e.kind}）"
                log["steps"]["radar"] = {"error": str(e)}
    calib = update_calibration(store, locs, now)

    # ---- 2. Open-Meteo 預報 ----
    try:
        if a.fixture:
            fc, info = load_fixture(Path(a.fixture), locs, now)
        else:
            fc, info = fetch_forecasts(locs, now)
    except FetchError as e:
        log["steps"]["forecast"] = {"error": str(e), "kind": e.kind}
        hint = ("執行環境的網路允許清單未放行 Open-Meteo，請在 Claude 設定將 api.open-meteo.com 加入允許網域。"
                if e.kind == "network_blocked" else "Open-Meteo 暫時無法取得，將於下次排程重試。")
        txt = (f"## 台灣北部降雨預報｜{now:%Y/%m/%d %H:%M} 更新失敗\n\n- 原因：{e.kind}：{e.detail[:200]}\n- {hint}\n"
               f"- Excel 未更動（保留上一版）。\n- 氣象署資料：{cwa_status}")
        return finish(2, txt)
    meta = {} if a.fixture else fetch_model_meta()
    info["model_meta"] = meta
    info["cwa_status"] = cwa_status
    info["summary"] = run_summary(locs, fc, now)
    prev_id = store.previous_ok_run(run_id)
    version = store.save_run(run_id, now, fc, info, "ok(fixture)" if a.fixture else "ok")
    log["steps"]["forecast"] = {"models_ok": info["models_ok"], "models_failed": info["models_failed"],
                                "hours": {l.key: len(fc[l.key][BASE_MODEL]["times"]) for l in locs}}

    # ---- 3. 文字分析 ----
    prev = store.load_run(prev_id) if prev_id else None
    prev_time = next((r["run_time"] for r in store.runs() if r["run_id"] == prev_id), None) if prev_id else None
    dly = R.daily(locs, fc)
    mdl = R.model_daily(locs, fc)
    enabled = [c for c in calib.values() if c["enabled"]]
    calib_summary = (f"已啟用 {len(enabled)} 組（地點×提前時間）" if enabled else
                     "校正待驗證（尚未有任何地點／提前時間通過獨立驗證，目前顯示原始 Best Match）")
    init_txt = "；".join(f"{k} {v['init'][5:16].replace('T', ' ')}" for k, v in meta.items() if v.get("init"))
    ctx = {"now": now, "near": R.near_term(locs, fc, now), "today": R.today_remaining(locs, fc, now),
           "notable": R.notable_days(locs, dly), "peaks": R.peaks(locs, fc, dly),
           "compare": R.compare_prev(locs, fc, prev, now),
           "prev_time": f"{prev_time:%m/%d %H:%M}" if prev_time else None,
           "fetched_at": info["fetched_at"][:16].replace("T", " "), "model_init": init_txt,
           "models_ok": info["models_ok"], "models_failed": info["models_failed"], "cwa_status": cwa_status,
           "calib_summary": calib_summary, "spread": R.spread_d57(locs, mdl, now.date()),
           "realtime": realtime, "radar": radar_txt}
    text = R.build_text(ctx)
    if a.fixture:
        text = "> ⚠ 測試模式：以下為離線測試資料，非真實預報。\n\n" + text

    # ---- 4. Excel ----
    runs = sorted(store.runs(), key=lambda r: r["run_time"])
    hist_rows, trend, ver_rows = [], [], []
    for r in runs:
        sm = r["info"].get("summary") or {}
        if sm:
            trend.append((r["run_time"], {k: v["total7"] for k, v in sm.items()}))
        for l in locs:
            v = sm.get(l.key)
            if v:
                hist_rows.append([r["run_time"].replace(tzinfo=None), r["version"], r["status"], l.name, v["next6"],
                                  v["today"], v["next24"], v["total7"], v["pmax"],
                                  datetime.fromisoformat(v["maxday_date"]).date(), v["maxday_mm"]])
        ri = r["info"]
        ver_rows.append([r["version"], r["run_time"].replace(tzinfo=None), r["status"], len(ri.get("models_ok", [])),
                         ri.get("excel_backup") or "", ri.get("excel_error") or ri.get("note") or ""])
    names = {s["station_id"]: s["name"] for s in store.stations()}
    run_times = {r["run_id"]: r["run_time"] for r in runs}
    pr = []
    wins = {(w["loc"], w["t_start"], w["t_end"]): w for w in store.windows()}
    lname = {l.key: l.name for l in locs}
    for p in store.pairs(BASE_MODEL, limit=PAIR_ROWS_MAX)[::-1]:
        w = wins.get((p["loc"], p["t_start"], p["t_end"]), {})
        pr.append([lname.get(p["loc"], p["loc"]), names.get(w.get("station_id"), w.get("station_id")),
                   w.get("dist_km"), parse(p["t_start"]).replace(tzinfo=None), parse(p["t_end"]).replace(tzinfo=None),
                   p["obs_mm"], w.get("method"), w.get("qc"),
                   run_times.get(p["run_id"], parse(p["t_start"])).replace(tzinfo=None), p["lead_h"],
                   bucket_of(p["lead_h"]), p["model"], p["fc_mm"], p["fc_prob"]])
    pair_note = ("尚無實測配對：" + cwa_status + "。配對需同一雨量站連續兩次整點附近快照，"
                 "且該視窗之前已有保存的預報。")
    st_txt = "；".join(f"{l.name}: " + "、".join(f"{st['name']}({st['station_id']}) {d:.1f} km" for d, st in loc_st.get(l.key, []))
                      for l in locs if loc_st.get(l.key)) or "尚未取得氣象署雨量站清單"
    sources = [
        ("預報基準", "Open-Meteo Forecast API（https://api.open-meteo.com/v1/forecast），models=best_match，"
                 "逐時 precipitation_probability（%）與 precipitation（mm，前一小時累積）。"),
        ("比較模型", ", ".join(COMPARE_MODELS) + "（同一 API 的 models 參數；不可用者自動略過並記錄於版本紀錄）"),
        ("本次成功模型", ", ".join(info["models_ok"])),
        ("本次失敗模型", "; ".join(f"{k}: {v}" for k, v in info["models_failed"].items()) or "無"),
        ("模型初始化時間", init_txt or "未取得"),
        ("即時雨量", "中央氣象署 O-A0002-001 自動雨量站（需授權碼）。特殊值：-98 連續 6 小時無降水→0；T 雨跡→0；"
                 "-99/X 缺值。狀態：" + cwa_status),
        ("雷達", "中央氣象署 O-A0058-003 雷達整合回波圖（需授權碼）。狀態：" + (radar_txt or "未取得")),
        ("AccuWeather", "尚未安裝成功，未作為備援。"),
        ("地點代表座標", "；".join(f"{l.name} {l.lat:.4f}, {l.lon:.4f}（{l.note}）" for l in locs)),
        ("配對雨量站", st_txt + f"（{STATION_MAX_KM:g} km 內依距離，最近且資料有效者優先）"),
        ("實測視窗推算", "同日兩次快照：本日累積雨量差；跨日：過去 K 小時雨量（必要時扣除同日已知時段）。"
                   "快照須在整點 ±15 分鐘內；品質檢查不通過者不參與配對。假設「Now」為當日 00:00 起累積，"
                   "由品質檢查（不得小於過去 1 小時雨量）持續驗證。"),
        ("驗證分組", "、".join(n for n, _, _ in LEAD_BUCKETS) + "（依視窗結束時間距發布時間）"),
        ("驗證指標", f"MAE、偏差、RMSE（mm/視窗）；事件門檻 {EVENT_MM} mm 之 POD/FAR/CSI；Brier（視窗內最高逐時機率）。"),
        ("校正方法與閘門", "每地點×提前分組，乘法係數 (Σ實測+10)/(Σ預報+10)，限制 0.5–2.0；依日期時間切分前 70% 訓練、"
                     "後 30% 獨立測試。需訓練 ≥60、測試 ≥30、測試期有雨視窗 ≥10，且測試期 MAE 改善 ≥5% 與依日 "
                     "bootstrap 95% 下界 >0 才啟用；否則標示「校正待驗證」或「未啟用」，Excel 顯示原始值。"),
        ("文字分析門檻", f"帶傘：逐時機率 ≥{UMBRELLA_PROB}% 或雨量 ≥{UMBRELLA_MM} mm；明顯雨勢日：日雨量 ≥{NOTABLE_DAY_MM:g} mm "
                   f"或機率 ≥{NOTABLE_DAY_PROB}%；風險高：6h 最高機率 ≥60% 或累積 ≥3 mm，中：≥30% 或 ≥0.5 mm。"),
        ("原始預報保存", "每次發布之全部模型逐時值（0.1 mm 精度，即 API 原始精度）保存於 data/rain.sqlite，供事後配對。"),
        ("版本與備份", "每次成功寫入前，將舊檔複製到 backup/（依星期×時段輪替，最多 56 份）；寫入失敗時原檔不動。"),
        ("不確定性", "第 5–7 天之降雨時間與量值不確定性高，模型比較頁的「差距」可作為參考。"),
    ]
    if S.excel_path.exists():
        from .excel_writer import backup_name
        for row in ver_rows:
            if row[0] == version:
                row[4] = "backup/" + backup_name(S.excel_path, now)
    hourly = R.hourly_rows(locs, fc, calib, now)
    wctx = {"locs": locs, "version": version, "now": now, "status": "成功" if not a.fixture else "測試資料",
            "text": text, "compare_models": [m for m in COMPARE_MODELS if m in info["models_ok"]],
            "hourly": hourly, "model_daily": mdl, "history_rows": hist_rows, "history_trend": trend,
            "pair_rows": pr, "pair_note": pair_note, "verif": verification_table(store, locs, now), "calib": calib,
            "sources": sources, "version_rows": ver_rows}
    try:
        wb = build_workbook(wctx)
        res = safe_write(wb, S.excel_path, S.data_dir / "_write_tmp.xlsx", S.backup_dir, now, len(hourly))
    except Exception as e:     # noqa: BLE001
        res = {"ok": False, "backup": None, "error": f"建立活頁簿失敗：{e}\n{traceback.format_exc()[-800:]}"}
    info["excel_backup"] = res.get("backup")
    info["excel_error"] = res.get("error")
    store.update_run_status(run_id, ("ok" if res["ok"] else "ok_excel_failed") + ("(fixture)" if a.fixture else ""), info)
    log["steps"]["excel"] = res
    log["version"] = version
    if not res["ok"]:
        text += f"\n\n> ⚠ Excel 更新失敗，原檔保留：{res['error'][:300]}"
        return finish(3, text)
    return finish(0, text)


if __name__ == "__main__":
    sys.exit(main())
