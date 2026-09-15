# Weatherboard — 台灣北部六地逐時降雨預測

自動更新的降雨看板：台北市、新北市板橋／中和／土城、新竹市、新竹縣竹北市。

網頁：<https://aaa89610.github.io/Weatherboard/>

## 架構

資料收集與判讀都由 Claude 做，GitHub 只負責把產出的 HTML 發布成網頁。

```
Claude Routine（每 2 小時，台灣時間 07–21）
  → 網頁搜尋收集各地雨情與特報
  → 跨來源比對、標出分歧、做出判讀
  → 寫成 report.html
  → git push main
       ↓
GitHub Actions  deploy.yml（report.html 等檔案變動才動）
  → 發布到 GitHub Pages
```

兩端都在雲端，不需要開著自己的電腦。GitHub 端沒有任何排程。

## 檔案

| 路徑 | 說明 |
| --- | --- |
| `index.html` | 產生出來的看板首頁（GitHub Pages 根目錄） |
| `template.html` | 版面樣板，`__DATA__` 會被換成當次資料 |
| `data.json` | 當次資料 |
| `history/YYYYMMDDTHHMM.json` | 每次執行的原始快照 |
| `report.html` | Claude 產生的判讀報告（每次更新覆蓋） |
| `build_board.py` | 直連氣象署端點的細粒度抓取程式，目前僅手動使用 |
| `.github/workflows/fetch.yml` | 手動觸發才跑，產生細粒度原始快照 |
| `.github/workflows/deploy.yml` | 檔案變動時部署到 Pages |

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
