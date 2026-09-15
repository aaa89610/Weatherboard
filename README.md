# Weatherboard — 台灣北部六地逐時降雨預測

自動更新的降雨看板：台北市、新北市板橋／中和／土城、新竹市、新竹縣竹北市。

網頁：<https://aaa89610.github.io/Weatherboard/>

## 架構

raw data 落進 `data/`，Claude 讀整個資料夾做空間分析與判讀，產生 HTML 報告覆蓋 Pages 檔案。

```
抓取（runner，網路不受限）
  → data/v2/<stamp>.json      固定 schema：rain-snapshot/2
       ↓
Claude Routine（每 2 小時）
  → analyze/load.py           讀 data/ 全部內容，整理跨時間摘要
  → spatial/spatial.py        環域 / 地形分離 / 雨帶追蹤
  → 判讀（人／模型做，不寫成閾值）
  → report.json → analyze/render.py → report.html
  → git push main
       ↓
GitHub Actions  deploy.yml
  → 發布到 GitHub Pages
```

判讀與版型分離：`report.json` 只放判讀結果，CSS 與結構固定在 `analyze/render.py`，
每次更新不必重寫版面。

## 目錄

| 路徑 | 說明 |
| --- | --- |
| `data/v2/` | 固定 schema 快照，可跨時間比較 |
| `data/raw/` | 舊格式快照 22 筆（09/11–09/15），每筆 schema 不同，僅供淺層參考 |
| `spatial/` | 47 站表與空間分析模組（純函式：envelope／summarize／terrain_split／track） |
| `analyze/load.py` | 讀 `data/` 全部內容，輸出跨時間摘要 |
| `analyze/render.py` | `report.json` → `report.html` |
| `report.json` | 本次判讀結果 |
| `report.html` | 部署到 Pages 的報告 |
| `rain-system-20260915/` | 前一代系統完整備份，含 `UPDATE_PROCEDURE.md` |

## 空間分析的三道守門

| 函式 | 守門條件 |
| --- | --- |
| `summarize` / `verdict` | 代表站 0 但環域有雨時，必須寫成「局部有雨、站點漏接」，不可寫 0 |
| `terrain_split` | 判定「完全分離」或「≥3 倍」時，平地預報值視為**上限**而非期望值 |
| `track` | 雨區縮小超過 40% 時回 `unusable`，拒絕給移動方向 |

第二道的由來：09/14 夜間模式給台北平地約 13 mm、官方發大雨特報，實際平地 0.0 mm，雨全落在山區。

## 更新時間

每日台灣時間 07:00–21:00，每 2 小時一次（共 8 次）。

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
