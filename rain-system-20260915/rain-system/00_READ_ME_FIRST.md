# 台灣北部逐時降雨預測與驗證 — 完整備份

匯出時間：2026-09-15 11:xx（台灣時間）
來源：Claude 雲端工作階段 `/mnt/user-data/outputs/rain/`

## 這包是什麼

整套系統的全部檔案。**金鑰不在裡面**（見最後一節）。

## 目錄

| 路徑 | 內容 |
|---|---|
| `UPDATE_PROCEDURE.md` | **核心**。每次定時更新照這份跑。含 7 地環域站群、三組 API 呼叫、空間分析步驟、報告六段格式 |
| `HANDOVER.md` | 給 Claude Code 的交接文件（2026-09-13 版，部分內容已被 UPDATE_PROCEDURE 取代） |
| `spatial/stations.json` | 47 個北部雨量站：站碼、名稱、座標、地形分類 |
| `spatial/spatial.py` | 空間分析模組。四個純函式：`envelope` `summarize` `terrain_split` `track` |
| `data/v2/` | **新格式**快照（schema 固定）＋ `tl_ensemble.json` 時間落後集合累積檔 |
| `data/multisource/` | 舊格式快照（09/11–09/15，schema 不一致，只能人工看） |
| `dashboard/` | 看板：`data.json`（資料）＋`template.html`（樣板）＋`build.py`（組裝） |
| `rain_pipeline/` | 早期以 Open-Meteo 為基準的管線，因連線受限未啟用。含 `excel_writer.py`（六工作表的 xlsx 產生器），本機可直接跑 |
| `setup/update.yml` | GitHub Actions 排程樣板（尚未安裝到 repo） |
| `config/`、`tests/` | 早期設定與測試 |

## 怎麼用 spatial 模組

```python
import sys; sys.path.insert(0, 'spatial')
import spatial as sp

obs = {'C0AJ80': {'p10':0.0, 'p1h':0.0, 'now':0.0}, ...}   # 取不到的站不要放，別填 0

for l in sp.LOC:
    print(l, sp.verdict(sp.summarize(obs, l)))              # 環域判定
print(sp.terrain_split(obs, box=(24.80,25.25,121.30,121.70)))  # 地形分離
print(sp.track(obs))                                        # 雨帶移動（會自我守門）
```

`track()` 在雨區縮小超過 40% 時會回 `confidence: "unusable"` 並拒絕給方向——這是刻意的，
那種情況下的質心位移是消散造成的假訊號。

## 目前的驗證紀錄（3 筆，不足以啟用任何校正）

| 日期 | 預報 | 實際 | 判定 |
|---|---|---|---|
| 09/13 白天 | 30%，判定不會下 | 0 mm | 正確 |
| 09/14 白天 | 30%，判定不會下 | 0 mm | 正確 |
| 09/14 夜–09/15 晨 | 台北平地約 13 mm，官方發大雨特報 | 平地 **0.0 mm**，雨全落在山區 | **失敗** |

狀態一律標「校正待驗證」。**不得據此做任何數值校正。**

## 已知缺口

- 雷達回波、最新 QPF 數值：都是圖檔，雲端讀不到，需瀏覽器
- 真正的集合預報：Open-Meteo 被 robots 擋、ECMWF 開放資料被 egress 擋。
  目前用「時間落後集合」代替（同一目標日、不同發布時刻的預報值當成員）
- 新竹縣站網：湖口、新豐、關西、芎林、寶山、北埔、峨眉 **無測站**
- 3–12 小時的高解析模式：完全沒有來源

## 金鑰（刻意不包含）

原本在 `.cwa/key`（氣象署開放資料）與 `.gh/token`（GitHub PAT）。
要在本機重建：

```bash
mkdir -p .cwa .gh
printf '%s' '你的氣象署金鑰' > .cwa/key   && chmod 600 .cwa/key
printf '%s' '你的GitHub token' > .gh/token && chmod 600 .gh/token
```

氣象署金鑰申請：https://opendata.cwa.gov.tw/user/authkey
