# Weatherboard — 台灣北部六地逐時降雨預測

自動更新的降雨看板：台北市、新北市板橋／中和／土城、新竹市、新竹縣竹北市。

網頁：<https://aaa89610.github.io/Weatherboard/>

## 架構

兩段式：GitHub 負責抓原始資料，判讀與產生報告由 Claude 做。

```
GitHub Actions  fetch.yml（每 2 小時，台灣時間 07–21）
  → python build_board.py --fetch-only
  → 只抓，不判讀
  → 原始快照寫進 history/<stamp>.json 並 push
       ↓  約 15 分鐘後
Claude Routine（每 2 小時，:20 觸發）
  → pull 拿到最新原始快照
  → 跨來源比對、挑出值得注意的時段、與上次快照比變化
  → 產生 data.json / index.html 並 push
       ↓
GitHub Actions  deploy.yml（看板檔案有變動才動）
  → 發布到 GitHub Pages
```

兩端都在雲端執行，不需要開著任何一台自己的電腦。

判讀之所以不放在 Actions，是因為它需要跨來源權衡而不是套閾值；
抓取之所以不放在 Claude 端，是因為 Claude session 的網路出口政策
擋住了氣象來源（見下方「已知限制」）。

## 檔案

| 路徑 | 說明 |
| --- | --- |
| `index.html` | 產生出來的看板首頁（GitHub Pages 根目錄） |
| `template.html` | 版面樣板，`__DATA__` 會被換成當次資料 |
| `data.json` | 當次資料 |
| `history/YYYYMMDDTHHMM.json` | 每次執行的原始快照 |
| `build_board.py` | 抓取與判讀，兩段共用（見下方執行模式） |
| `.github/workflows/fetch.yml` | 定時抓原始資料，寫進 `history/` |
| `.github/workflows/deploy.yml` | 看板有變動時部署到 Pages |

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

## 已知限制

Claude session 的網路出口是白名單制，對 `www.cwa.gov.tw`、`api.met.no`、
`www.meteoblue.com` 一律回 403，所以抓取只能放在 GitHub Actions 上跑
（runner 的網路不受限）。若日後放寬該白名單，`build_board.py` 不必改，
把判讀端的指令從 `--from-raw` 換成直接執行即可。

## 資料來源

中央氣象署（鄉鎮逐時／一週預報、鄉鎮即時觀測、縣市 36 小時預報、特報、定量降水預報、雨量站）、
yr.no（MET Norway／ECMWF）、meteoblue。

所有數值均來自來源實測或實際預報，未經推估捏造；任一來源取得失敗會直接在看板上標示，
全部來源都失敗時不更新看板。
