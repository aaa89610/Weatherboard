# Weatherboard — 台灣北部六地逐時降雨預測

自動更新的降雨看板：台北市、新北市板橋／中和／土城、新竹市、新竹縣竹北市。

網頁：<https://aaa89610.github.io/Weatherboard/>

## 架構

抓取、空間分析、判讀、產生報告都在 Claude session 內完成，GitHub 只負責部署。

```
Claude Routine（每日四次，台灣時間 07:00、11:00、16:00、21:00）
  → analyze/fetch_v2.py    抓 47 站與預報，跑空間分析，寫 data/v2/<stamp>.json
  → analyze/load.py        讀 data/ 全部內容，跨時間比對
  → 判讀（人／模型做，不寫成閾值）
  → report.json → analyze/render.py → report.html
  → git push main
       ↓
GitHub Actions  deploy.yml
  → 發布到 GitHub Pages
```

`.github/workflows/fetch.yml` 保留但**不排程**，僅供備援手動觸發。

2026-09-21 之前抓取跑在 Actions 上，因為當時 Claude session 的網路白名單擋住氣象署。
白名單放寬後兩段合併，少一個跨平台交接，也不再受 GitHub 排程掉 tick 影響
（實測 6 天只跑 20 次，設定為 48 次）。

## 目錄

| 路徑 | 說明 |
| --- | --- |
| `data/v2/` | 固定 schema 快照，可跨時間比較 |
| `analyze/fetch_v2.py` | 在 Actions 上抓測站與預報、跑空間分析、寫 v2 快照 |
| `data/raw/` | 舊格式快照 22 筆（09/11–09/15），每筆 schema 不同，僅供淺層參考 |
| `spatial/` | 47 站表與空間分析模組（純函式：envelope／summarize／terrain_split／track） |
| `analyze/load.py` | 讀 `data/` 全部內容，輸出跨時間摘要 |
| `analyze/render.py` | `report.json` → `report.html` |
| `report.json` | 本次判讀結果 |
| `report.html` | 部署到 Pages 的報告 |
| `rain-system-20260915/` | 前一代系統完整備份，含 `UPDATE_PROCEDURE.md` |

## 快照的 parser 版本

`meta.parser` 記錄快照是哪一版抓取器產生的：

| parser | 行為 |
| --- | --- |
| 1 | 回報 0 的測站被整站丟棄，覆蓋率與地形統計失真，**不可採信** |
| 2 | 回報 0 的測站收進 `obs`，覆蓋率恢復意義 |
| 3 | 觀測時刻多樣式比對（失敗留 `time_probe`）；特報不再用內容關鍵字過濾，全部保留 |
| 4 | `time_probe` 加入頁首與中文時間樣候選；特報改標 `areas_ours` / `areas_near` 兩份清單 |
| 5 | 確認該頁不提供觀測時刻，改以 `fetched_at` ± `time_bound_min` 表達時間界限 |
| 6 | 優先走開放資料 API（欄位有名稱、附 `ObsTime`），失敗自動退回爬網頁 |

parser 2 起，**回報 0 的測站也會收進 `obs`**。

氣象署頁面用 `-` 表示 0，parser 1 誤把它當成「沒回報」而整站丟棄，後果是
環域覆蓋率永遠顯示 N/N、`terrain_split` 的平地中位數只由濕站算出而低估地形分離，
且「查無資料」與「確認沒下雨」無法區分。

`20260915T2037` 到 `20260916T1050` 這 4 筆是 parser 1 產生的，
覆蓋率與地形統計偏高，判讀時不要採信這兩項；測站數值本身仍是實測值。

## 氣象署金鑰

抓取優先走開放資料 API `O-A0002-001`，需要金鑰。金鑰存成 GitHub Actions secret
`CWA_KEY`，程式只從環境變數讀，**絕不寫進檔案**——這個 repo 是公開的。

設定位置：Settings → Secrets and variables → Actions → New repository secret，
名稱 `CWA_KEY`。

沒有設 secret 也能運作：`fetch_v2.py` 會自動退回爬網頁，只是少了精確 `ObsTime`，
且欄位語意得靠位置推斷。`meta.source` 記錄該次實際走哪條路
（`opendata-api` 或 `scrape`），API 失敗時 `meta.api_error` 記錄原因，
錯誤訊息中的金鑰會被遮成 `<KEY>`。

API 路徑另外會排除氣象署的缺測哨兵（負值如 -998），不與「回報 0」混為一談。

申請：<https://opendata.cwa.gov.tw/user/authkey>

## 更新條件：有新資料才更新

判讀端的觸發條件是「**有沒有新快照**」，不是「資料夠不夠新」。

`python3 analyze/load.py --check` 比對 `report.json` 的 `source_stamp` 與最新快照：
有新資料回結束碼 0，沒有回 1。判讀端先跑這個，沒有新資料就立刻結束，不做分析。

會這樣設計是因為上游排程不穩定：`fetch.yml` 設定每日 8 次，
2026-09-15 至 09-21 實測只跑了 20 次（約 3.3 次／日），間隔 3.4–11.6 小時，
全部 success —— GitHub 直接略過多數排程觸發，不是失敗。

原先以「資料超過 180 分鐘就不要更新」當阻斷條件，結果判讀端每次醒來都放棄，
報告連續五天沒更新。**資料舊不是不更新的理由，是要標示的事實**：
`analyze/render.py` 在 `source_stamp` 超過 3 小時時會自動於頁首插入警示橫幅，
不依賴判讀者記得寫。

## 觀測時刻

雨量頁（`10Min_MOD.html`）是純資料片段，**沒有表頭也沒有任何時間字串**
（2026-09-16 以 H:MM、中文時間、8–14 位數字串三路探針確認）。

因此 `obs.time` 為 `None`，改用兩個欄位表達界限：

- `fetched_at`：抓取時刻
- `time_bound_min`：10 —— 該頁每 10 分鐘更新，實際觀測時刻落在 `[fetched_at − 10 分, fetched_at]`

報告要寫成區間，不可寫成精確時刻。要取得精確的 `ObsTime`，得改走氣象署
開放資料 API `O-A0002-001`（需金鑰），該端點欄位有名稱，也不必靠欄位位置推斷。

欄位對應（2026-09-16 驗證）：`(站碼)` 之後是 `縣市|鄉鎮`，再 11 個數值，
依序為 `10分|1h|3h|6h|12h|24h|本日|…`，`-` 表示 0。

## 報告放什麼、不放什麼

版型層（`analyze/render.py`）硬性過濾，不靠判讀端記得：

| 項目 | 規則 |
| --- | --- |
| 特報 | 只渲染 `areas_ours` **非空**（實際涵蓋七地）**且**標題含「雨」或「颱風」的 |
| 強風、長浪、高溫 | 一律不渲染，即使涵蓋本區 —— 這是降雨看板 |
| 空間分析（terrain）區塊 | 整個不渲染 |
| 資料過舊橫幅 | 帶 `always` 旗標，不受上述過濾 |

起因：連續三輪把「明確不涵蓋本區」的強風與長浪特報寫進報告，佔掉最大版面卻不影響
任何決定；全區無雨時 terrain 區塊也只是在解釋「沒事發生」。

判讀文字同樣不寫方法論：三道守門的逐項觸發狀況、缺測對哪一項統計有影響、
`track()` 為何不可判讀——這些是內部規則，寫進 commit message，不進報告。
地形分離**真的觸發**時（完全分離或 ≥3 倍），由判讀端寫成一條 finding，而非固定區塊。

## 特報的地區判定

特報記 `areas_ours`（本報告七地所屬行政區）與 `areas_near`（桃園、苗栗、基隆、宜蘭）兩份清單，
不用單一布林值。

起因：2026-09-16 的陸上強風特報列了桃園市與苗栗縣，**但沒有列新竹**——
夾在兩者中間的新竹不在範圍內。單一布林值會因為命中「桃園」而標成「與本區相關」，
把「鄰近縣市有特報」誤當成「本區有特報」。

`areas_ours` 空而 `areas_near` 有值時，報告不可寫成本區有特報。

## 空間分析的三道守門

| 函式 | 守門條件 |
| --- | --- |
| `summarize` / `verdict` | 代表站 0 但環域有雨時，必須寫成「局部有雨、站點漏接」，不可寫 0 |
| `terrain_split` | 判定「完全分離」或「≥3 倍」時，平地預報值視為**上限**而非期望值 |
| `track` | 雨區縮小超過 40% 時回 `unusable`，拒絕給移動方向 |

第二道的由來：09/14 夜間模式給台北平地約 13 mm、官方發大雨特報，實際平地 0.0 mm，雨全落在山區。

## 更新時間

每日台灣時間 **07:00、11:00、16:00、21:00**，共四次。
cron 以 UTC 表示為 `0 23,3,8,13 * * *`（台灣時間減 8 小時，07:00 落在前一日 23:00 UTC）。

夜間 21:00 到隔日 07:00 之間沒有觀測覆蓋，報告不得宣稱跨夜無雨。

## 首次設定

Settings → Pages → Source 選 **GitHub Actions**（不是 Deploy from a branch）。

## build_board.py 的三種執行模式

```bash
pip install requests pillow

python build_board.py --fetch-only              # 只抓，寫 history/<stamp>.json（Actions 用）
python build_board.py --from-raw history/X.json # 只判讀，不重抓，產生 data.json / index.html
python build_board.py                           # 抓＋判讀一次做完（本機手動跑用）
```

`--fetch-only` 在所有來源都失敗時回非 0 並且不寫快照，不會產生空檔。
`--from-raw` 不會再寫一筆 history，因為快照已經存在。
前兩種以外的模式需要連得到 `www.cwa.gov.tw`、`www.yr.no`、`www.meteoblue.com`。

## 已知限制：資料粒度

Claude session 的網路出口是白名單制，對 `www.cwa.gov.tw`、`api.met.no`、
`www.meteoblue.com` 一律回 403，直接抓官方端點行不通。網頁搜尋不受此限，
所以收集改走搜尋——代價是**粒度只到日尺度**，拿不到逐時 PoP、QPF、雨量站這些資料。

`report.html` 對取不到的欄位一律標「未取得」，不以鄰區數值或內插填補。

要恢復逐時解析度有兩條路：放寬上述白名單後 Claude 就能直接抓；
或到 Actions 手動跑一次 `fetch.yml`，它在 runner 上執行、網路不受限。

## 資料來源

中央氣象署（鄉鎮逐時／一週預報、鄉鎮即時觀測、縣市 36 小時預報、特報、定量降水預報、雨量站）、
yr.no（MET Norway／ECMWF）、meteoblue。

所有數值均來自來源實測或實際預報，未經推估捏造；任一來源取得失敗會直接在看板上標示，
全部來源都失敗時不更新看板。
