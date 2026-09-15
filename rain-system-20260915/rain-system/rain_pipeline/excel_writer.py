"""Excel 輸出：先寫暫存檔並驗證，成功後才備份舊檔並覆寫；任何失敗都保留原檔。

注意：在使用者電腦的共享資料夾中可能無法刪除／改名覆蓋檔案，因此
- 暫存檔使用固定檔名（每次覆寫，不刪除）
- 覆寫正式檔採「內容複製」而非改名
- 備份採固定輪替檔名（星期×時段，最多 56 份），自然覆蓋舊版
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .config import BASE_MODEL, LEAD_BUCKETS
from .report import WD

FONT = "Microsoft JhengHei"
F_BODY = Font(name=FONT, size=10)
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_TITLE = Font(name=FONT, size=14, bold=True, color="0B1F3A")
F_NOTE = Font(name=FONT, size=9, italic=True, color="555555")
FILL_HEAD = PatternFill("solid", fgColor="0B1F3A")
FILL_SUB = PatternFill("solid", fgColor="DCE6F2")
THIN = Side(style="thin", color="C8D0DA")
BORDER = Border(bottom=THIN)

SHEETS = ["總覽", "逐時預報", "每日摘要", "趨勢圖", "模型比較", "預報歷史", "實測配對", "驗證結果", "來源", "版本紀錄"]


def _header(ws, row, headers, widths=None):
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=row, column=j, value=h)
        c.font, c.fill = F_HEAD, FILL_HEAD
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    ws.row_dimensions[row].height = 30


def _title(ws, text, note=None):
    ws["A1"] = text
    ws["A1"].font = F_TITLE
    if note:
        ws["A2"] = note
        ws["A2"].font = F_NOTE


def _body(ws, r0, r1, c1):
    for row in ws.iter_rows(min_row=r0, max_row=r1, max_col=c1):
        for c in row:
            if c.font is None or c.font.name != FONT or not c.font.b:
                c.font = F_BODY


def build_workbook(ctx: dict) -> Workbook:
    wb = Workbook()
    wb.remove(wb.active)
    for name in SHEETS:
        wb.create_sheet(name)
    locs = ctx["locs"]
    loc_names = [l.name for l in locs]

    # ---------------- 總覽 ----------------
    ws = wb["總覽"]
    _title(ws, "台灣北部 7 天逐時降雨預測", f"版本 v{ctx['version']}｜發布 {ctx['now']:%Y/%m/%d %H:%M}（台灣時間）｜狀態：{ctx['status']}")
    r = 4
    for line in ctx["text"].splitlines():
        c = ws.cell(row=r, column=1, value=line.replace("**", "").lstrip("# "))
        c.font = Font(name=FONT, size=12 if line.startswith("### ") else 10, bold=line.startswith("#"),
                      color="0B1F3A" if line.startswith("#") else "000000")
        c.alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    ws.column_dimensions["A"].width = 140

    # ---------------- 逐時預報 ----------------
    ws = wb["逐時預報"]
    models = ctx["compare_models"]
    heads = ["預報時間(小時結束)", "歸屬日期", "地點", "提前時數(h)", "降雨機率(%)", "雨量 Best Match(mm)",
             "校正後雨量(mm)"] + [f"{m}(mm)" for m in models] + ["模型最小(mm)", "模型最大(mm)", "模型數"]
    _header(ws, 1, heads, [18, 11, 14, 10, 10, 12, 13] + [11] * len(models) + [11, 11, 8])
    rows = ctx["hourly"]
    for i, h in enumerate(rows, 2):
        vals = [h["time"].replace(tzinfo=None), h["date"], h["loc"], h["lead"], h["prob"], h["mm"],
                h["mm_cal"] if h["mm_cal"] is not None else "校正待驗證"]
        vals += [h["models"].get(m) for m in models] + [h["m_min"], h["m_max"], h["m_n"]]
        for j, v in enumerate(vals, 1):
            ws.cell(row=i, column=j, value=v)
        ws.cell(row=i, column=1).number_format = "yyyy/mm/dd hh:mm"
        ws.cell(row=i, column=2).number_format = "m/d"
        for j in range(6, len(vals) - 0):
            ws.cell(row=i, column=j).number_format = "0.0"
        ws.cell(row=i, column=5).number_format = "0"
        ws.cell(row=i, column=len(vals)).number_format = "0"
    n = len(rows) + 1
    _body(ws, 2, n, len(heads))
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(heads))}{n}"
    ws.conditional_formatting.add(f"E2:E{n}", ColorScaleRule(start_type="num", start_value=0, start_color="FFFFFF",
                                                             end_type="num", end_value=100, end_color="3C78D8"))
    ws.conditional_formatting.add(f"F2:F{n}", DataBarRule(start_type="num", start_value=0, end_type="max",
                                                          color="5B9BD5"))

    # ---------------- 每日摘要（公式取自逐時預報） ----------------
    ws = wb["每日摘要"]
    _title(ws, "每日摘要（依逐時預報以公式彙總；歸屬日期以該小時開始時間計）",
           "首尾兩天可能不足 24 小時，請參考「預報小時數」欄。")
    dates = sorted({h["date"] for h in rows})
    blocks = [("日雨量 (mm)", "SUMIFS('逐時預報'!$F:$F,'逐時預報'!$B:$B,$A{r},'逐時預報'!$C:$C,{c}$4)", "0.0"),
              ("最高降雨機率 (%)", "_xlfn.MAXIFS('逐時預報'!$E:$E,'逐時預報'!$B:$B,$A{r},'逐時預報'!$C:$C,{c}$4)", "0"),
              ("降雨時數 (≥0.1 mm)", "COUNTIFS('逐時預報'!$B:$B,$A{r},'逐時預報'!$C:$C,{c}$4,'逐時預報'!$F:$F,\">=0.1\")", "0")]
    start = 4
    ctx["_daily_block"] = (start, len(dates))
    for bi, (label, tmpl, fmtc) in enumerate(blocks):
        hr = start + bi * (len(dates) + 3)
        heads = ["日期", "星期"] + loc_names + ["預報小時數"]
        _header(ws, hr, heads, [11, 6] + [14] * len(loc_names) + [11])
        ws.cell(row=hr - 1, column=1, value=label).font = Font(name=FONT, bold=True, size=11, color="0B1F3A")
        # 標頭列同時是 SUMIFS 的地點條件
        for k, d in enumerate(dates):
            rr = hr + 1 + k
            ws.cell(row=rr, column=1, value=d).number_format = "m/d"
            ws.cell(row=rr, column=2, value=WD[d.weekday()])
            for j in range(len(loc_names)):
                col = get_column_letter(3 + j)
                f = tmpl.replace("{r}", str(rr)).replace("{c}$4", f"{col}${hr}")
                c = ws.cell(row=rr, column=3 + j, value="=" + f)
                c.number_format = fmtc
            ws.cell(row=rr, column=3 + len(loc_names),
                    value=f"=COUNTIFS('逐時預報'!$B:$B,$A{rr},'逐時預報'!$C:$C,C${hr})")
        _body(ws, hr + 1, hr + len(dates), 3 + len(loc_names))

    # ---------------- 趨勢圖 ----------------
    ws = wb["趨勢圖"]
    _title(ws, "趨勢圖", "上：各地每日預估雨量；中：未來 168 小時逐時降雨機率；下：歷次發布的 7 日總量變化")
    ds = wb["每日摘要"]
    ch = BarChart()
    ch.title, ch.y_axis.title, ch.height, ch.width = "每日預估雨量 (mm)", "mm", 8, 26
    data = Reference(ds, min_col=3, max_col=2 + len(loc_names), min_row=start, max_row=start + len(dates))
    ch.add_data(data, titles_from_data=True)
    ch.set_categories(Reference(ds, min_col=1, min_row=start + 1, max_row=start + len(dates)))
    ws.add_chart(ch, "A4")
    # 輔助表：逐時機率寬表（放在右側）
    col0 = 20
    ws.cell(row=3, column=col0, value="輔助資料：逐時降雨機率(%)").font = F_NOTE
    _hdr = ["時間"] + loc_names
    for j, h in enumerate(_hdr):
        c = ws.cell(row=4, column=col0 + j, value=h)
        c.font, c.fill = F_HEAD, FILL_HEAD
    times = sorted({h["time"] for h in rows})
    idx = {(h["time"], h["loc"]): h for h in rows}
    for k, t in enumerate(times):
        # 以文字作類別，避免圖表把時間當日期軸而把同一天的點疊在一起
        ws.cell(row=5 + k, column=col0, value=f"{t.month}/{t.day} {t:%H}時")
        for j, ln in enumerate(loc_names):
            ws.cell(row=5 + k, column=col0 + 1 + j, value=(idx.get((t, ln)) or {}).get("prob"))
    lc = LineChart()
    lc.title, lc.y_axis.title, lc.height, lc.width = "逐時降雨機率 (%)", "%", 8, 26
    lc.add_data(Reference(ws, min_col=col0 + 1, max_col=col0 + len(loc_names), min_row=4, max_row=4 + len(times)),
                titles_from_data=True)
    lc.set_categories(Reference(ws, min_col=col0, min_row=5, max_row=4 + len(times)))
    lc.y_axis.scaling.min, lc.y_axis.scaling.max = 0, 100
    for sr in lc.series:
        sr.smooth = False
        sr.graphicalProperties.line.width = 15000
    ws.add_chart(lc, "A21")
    # 歷次發布 7 日總量
    hist = ctx["history_trend"]      # [(run_time, {loc: total})]
    col1 = col0 + len(loc_names) + 2
    ws.cell(row=3, column=col1, value="輔助資料：歷次發布 7 日總量(mm)").font = F_NOTE
    for j, h in enumerate(["發布時間"] + loc_names):
        c = ws.cell(row=4, column=col1 + j, value=h)
        c.font, c.fill = F_HEAD, FILL_HEAD
    for k, (rt, tot) in enumerate(hist):
        ws.cell(row=5 + k, column=col1, value=f"{rt.month}/{rt.day} {rt:%H}時")
        for j, l in enumerate(locs):
            ws.cell(row=5 + k, column=col1 + 1 + j, value=tot.get(l.key))
    if len(hist) >= 2:
        hc = LineChart()
        hc.title, hc.y_axis.title, hc.height, hc.width = "歷次發布之 7 日總量 (mm)", "mm", 8, 26
        hc.add_data(Reference(ws, min_col=col1 + 1, max_col=col1 + len(locs), min_row=4, max_row=4 + len(hist)),
                    titles_from_data=True)
        hc.set_categories(Reference(ws, min_col=col1, min_row=5, max_row=4 + len(hist)))
        for sr in hc.series:
            sr.smooth = False
        ws.add_chart(hc, "A38")
    else:
        ws["A38"] = "歷次發布趨勢：累積 2 次以上成功發布後顯示。"
        ws["A38"].font = F_NOTE

    # ---------------- 模型比較 ----------------
    ws = wb["模型比較"]
    _title(ws, "模型比較：各模型每日預估雨量 (mm)", "空白 = 該模型在此地點／日期無資料。差距 = 最大 − 最小，反映模型間不確定性。")
    mdl = ctx["model_daily"]
    mnames = list(mdl)
    heads = ["日期", "地點"] + mnames + ["最小", "最大", "差距"]
    _header(ws, 4, heads, [11, 14] + [13] * len(mnames) + [9, 9, 9])
    rr = 5
    for d in dates:
        for l in locs:
            ws.cell(row=rr, column=1, value=d).number_format = "m/d"
            ws.cell(row=rr, column=2, value=l.name)
            vals = []
            for j, m in enumerate(mnames):
                v = mdl[m].get(l.key, {}).get(d)
                if v is not None and v["hours"] > 0:
                    ws.cell(row=rr, column=3 + j, value=round(v["mm"], 1)).number_format = "0.0"
            c0, c1 = get_column_letter(3), get_column_letter(2 + len(mnames))
            k = 3 + len(mnames)
            ws.cell(row=rr, column=k, value=f"=IF(COUNT({c0}{rr}:{c1}{rr})=0,\"\",MIN({c0}{rr}:{c1}{rr}))").number_format = "0.0"
            ws.cell(row=rr, column=k + 1, value=f"=IF(COUNT({c0}{rr}:{c1}{rr})=0,\"\",MAX({c0}{rr}:{c1}{rr}))").number_format = "0.0"
            ws.cell(row=rr, column=k + 2, value=f"=IF(COUNT({c0}{rr}:{c1}{rr})<2,\"\",MAX({c0}{rr}:{c1}{rr})-MIN({c0}{rr}:{c1}{rr}))").number_format = "0.0"
            rr += 1
    _body(ws, 5, rr - 1, len(heads))
    ws.freeze_panes = "C5"

    # ---------------- 預報歷史 ----------------
    ws = wb["預報歷史"]
    heads = ["發布時間", "版本", "狀態", "地點", "未來6小時(mm)", "今日剩餘(mm)", "未來24小時(mm)", "7日總量(mm)",
             "7日最高機率(%)", "最大日雨量日期", "最大日雨量(mm)"]
    _header(ws, 1, heads, [17, 7, 10, 14, 12, 12, 13, 12, 13, 14, 13])
    rr = 2
    for h in ctx["history_rows"]:
        for j, v in enumerate(h, 1):
            c = ws.cell(row=rr, column=j, value=v)
            if j == 1:
                c.number_format = "yyyy/mm/dd hh:mm"
            elif j == 10:
                c.number_format = "m/d"
            elif j >= 5:
                c.number_format = "0.0"
        rr += 1
    _body(ws, 2, rr - 1, len(heads))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(heads))}{max(rr - 1, 1)}"

    # ---------------- 實測配對 ----------------
    ws = wb["實測配對"]
    heads = ["地點", "雨量站", "距離(km)", "視窗開始", "視窗結束", "實測(mm)", "推算方式", "品質",
             "發布時間", "提前時數(h)", "提前分組", "模型", "預報(mm)", "視窗最高機率(%)", "誤差(預報−實測)"]
    _header(ws, 1, heads, [14, 16, 9, 16, 16, 9, 14, 12, 16, 10, 10, 16, 9, 12, 13])
    pr = ctx["pair_rows"]
    if not pr:
        ws["A2"] = ctx["pair_note"]
        ws["A2"].font = F_NOTE
    for i, p in enumerate(pr, 2):
        for j, v in enumerate(p, 1):
            ws.cell(row=i, column=j, value=v)
        for j in (4, 5, 9):
            ws.cell(row=i, column=j).number_format = "m/d hh:mm"
        ws.cell(row=i, column=15, value=f"=IF(OR(M{i}=\"\",F{i}=\"\"),\"\",M{i}-F{i})").number_format = "0.0"
    _body(ws, 2, len(pr) + 1, len(heads))
    ws.freeze_panes = "A2"
    if pr:
        ws.auto_filter.ref = f"A1:O{len(pr) + 1}"

    # ---------------- 驗證結果 ----------------
    ws = wb["驗證結果"]
    _title(ws, "驗證結果（依地點 × 預報提前時間）",
           "N = 配對數；MAE/偏差/RMSE 單位 mm（每個實測視窗）；POD/FAR/CSI 事件門檻 0.5 mm；Brier 以視窗內最高機率計。"
           "校正只在時間切分的獨立測試期確實改善（MAE ≥5% 且 bootstrap 95% 下界 >0）才啟用。")
    heads = ["地點", "提前時間", "模型", "N", "MAE", "偏差", "RMSE", "實測平均", "預報平均", "POD", "FAR", "CSI",
             "Brier", "校正係數", "訓練/測試", "校正狀態"]
    _header(ws, 4, heads, [14, 10, 16, 7, 8, 8, 8, 9, 9, 7, 7, 7, 8, 9, 11, 60])
    rr = 5
    calib = ctx["calib"]
    for v in ctx["verif"]:
        c = calib.get((v["loc"], v["bucket"], v["model"])) if v["model"] == BASE_MODEL else None
        vals = [v["loc_name"], v["bucket"], v["model"], v.get("n", 0)]
        for k in ("mae", "bias", "rmse", "obs_mean", "fc_mean", "pod", "far", "csi", "brier"):
            x = v.get(k)
            vals.append(round(x, 3) if isinstance(x, float) else x)
        vals += [c["factor"] if c else None, f"{c['n_train']}/{c['n_test']}" if c else None,
                 c["status"] if c else ("僅比較，不校正" if v["model"] != BASE_MODEL else "校正待驗證（尚無配對）")]
        for j, x in enumerate(vals, 1):
            ws.cell(row=rr, column=j, value=x)
        rr += 1
    _body(ws, 5, rr - 1, len(heads))
    ws.freeze_panes = "D5"

    # ---------------- 來源 ----------------
    ws = wb["來源"]
    _title(ws, "資料來源、方法與假設")
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 120
    rr = 3
    for k, v in ctx["sources"]:
        a = ws.cell(row=rr, column=1, value=k)
        a.font = Font(name=FONT, bold=True, size=10)
        b = ws.cell(row=rr, column=2, value=v)
        b.font, b.alignment = F_BODY, Alignment(wrap_text=True, vertical="top")
        rr += 1

    # ---------------- 版本紀錄 ----------------
    ws = wb["版本紀錄"]
    heads = ["版本", "發布時間", "狀態", "成功模型數", "Excel 備份檔", "說明"]
    _header(ws, 1, heads, [7, 17, 12, 10, 50, 80])
    for i, row in enumerate(ctx["version_rows"], 2):
        for j, v in enumerate(row, 1):
            c = ws.cell(row=i, column=j, value=v)
            if j == 2:
                c.number_format = "yyyy/mm/dd hh:mm"
    _body(ws, 2, len(ctx["version_rows"]) + 1, len(heads))
    ws.freeze_panes = "A2"

    wb.calculation.fullCalcOnLoad = True
    return wb


def backup_name(excel: Path, t: datetime) -> str:
    return f"{excel.stem}_週{WD[t.weekday()]}_{t:%H}00.xlsx"


def safe_write(wb: Workbook, excel: Path, tmp: Path, backup_dir: Path, now: datetime,
               expect_rows: int) -> dict:
    """成功才覆寫正式檔；失敗時原檔不動。回傳 {"ok", "backup", "error"}。"""
    tmp.parent.mkdir(parents=True, exist_ok=True)
    backup_dir.mkdir(parents=True, exist_ok=True)
    res = {"ok": False, "backup": None, "error": None}
    try:
        wb.save(tmp)
        chk = load_workbook(tmp, read_only=True)
        missing = [s for s in SHEETS if s not in chk.sheetnames]
        got = chk["逐時預報"].max_row - 1
        chk.close()
        if missing or got != expect_rows:
            raise RuntimeError(f"暫存檔驗證失敗：缺少工作表 {missing}，逐時列數 {got}/{expect_rows}")
    except Exception as e:     # noqa: BLE001
        res["error"] = f"寫入暫存檔失敗：{e}"
        return res
    try:
        if excel.exists():
            b = backup_dir / backup_name(excel, now)
            shutil.copyfile(excel, b)
            res["backup"] = str(b.relative_to(excel.parent))
        shutil.copyfile(tmp, excel)      # 內容覆寫（不需刪除權限）
        res["ok"] = True
    except Exception as e:     # noqa: BLE001
        res["error"] = f"覆寫正式檔失敗（檔案可能正被 Excel 開啟）：{e}；最新版本在 {tmp.name}"
        # 若覆寫中途失敗導致正式檔不完整，從剛才的備份還原
        if res["backup"]:
            try:
                load_workbook(excel, read_only=True).close()
            except Exception:   # noqa: BLE001
                try:
                    shutil.copyfile(excel.parent / res["backup"], excel)
                    res["error"] += "；已由備份還原原檔"
                except Exception as e2:   # noqa: BLE001
                    res["error"] += f"；還原失敗：{e2}"
    return res
