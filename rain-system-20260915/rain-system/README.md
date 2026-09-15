# 台灣北部 7 天逐時降雨預測與驗證

每天 07:00–21:00 每兩小時執行一次，更新《台灣北部_7天逐時降雨預測.xlsx》並產生繁體中文分析（reports/latest.md）。

## 資料夾結構
| 路徑 | 用途 |
|---|---|
| 台灣北部_7天逐時降雨預測.xlsx | 主檔（10 個工作表） |
| rain_pipeline/ | 程式（模組化：資料源、儲存、驗證、報告、Excel 各自獨立） |
| config/settings.json | 氣象署授權碼、地點覆寫 |
| data/rain.sqlite | 每次原始預報、實測快照、配對、校正狀態（歷史真實來源） |
| backup/ | Excel 舊版（星期×時段輪替，最多 56 份） |
| reports/ | 每次文字分析（latest.md 為最新） |
| logs/run_log.jsonl | 每次執行紀錄 |
| tests/ | 離線測試（合成資料，只驗證程式邏輯） |

## 模組
- `src_openmeteo.py`：Best Match 基準＋8 個比較模型、模型初始化時間、previous-runs 回測介面
- `src_cwa.py`：氣象署 O-A0002-001 雨量站、O-A0058-003 雷達圖
- `store.py`：SQLite 歷史庫（不刪檔的 PERSIST 日誌模式）
- `verify.py`：實測視窗推算、配對、分地點×提前時間驗證、校正獨立驗證閘門
- `report.py`：逐時表、每日摘要、文字分析
- `excel_writer.py`：暫存檔驗證 → 備份 → 覆寫；失敗保留原檔
- `run.py`：主流程

## 執行
```
python3 -m rain_pipeline.run --root .
```
結束碼：0 成功；2 預報下載失敗（Excel 不動）；3 Excel 寫入失敗（原檔保留）。

## 需要放行的網域
api.open-meteo.com、previous-runs-api.open-meteo.com、opendata.cwa.gov.tw（雷達圖檔若在其他網域，依執行紀錄補上）

## 校正啟用規則
每地點×提前分組各自評估；依日期切分前 70% 訓練、後 30% 獨立測試。需訓練 ≥60、測試 ≥30 筆、測試期 ≥7 天、有雨視窗 ≥10，
且測試期 MAE 改善 ≥5%、依日 bootstrap 95% 下界 >0 才啟用。否則 Excel 顯示「校正待驗證」／「未啟用」並使用原始 Best Match。

## 排程方式（檔案放在聊天室）
檔案不放在電腦資料夾時，每次排程若開新對話就會遺失歷史紀錄。因此採「同一個對話自我喚醒」：
- 工作資料夾放在 `/mnt/user-data/outputs/rain/`（隨對話保存）
- 用 send_later 在 07/09/11/13/15/17/19/21 時喚醒同一個對話；每次執行後立刻排定下一個時段，並檢查未來 24 小時的時段都已排定
- 每次：執行 `python3 -m rain_pipeline.run --root /mnt/user-data/outputs/rain` → 以繁體中文回覆 reports/latest.md 內容 → 傳送最新 Excel
- 結束碼 2（下載失敗）時不更新 Excel，只回報原因
