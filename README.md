# Weatherboard — 台灣北部六地逐時降雨預測

自動更新的降雨看板：台北市、新北市板橋／中和／土城、新竹市、新竹縣竹北市。

網頁：<https://aaa89610.github.io/Weatherboard/>

## 架構

抓取、分析、產生報告都在 Claude session 內完成，GitHub 只負責部署。

```
Claude Routine（每 2 小時喚醒）
  → 抓各來源原始資料
  → 跨來源比對與判讀
  → 產生 index.html / data.json / history 快照
  → git push
       ↓
GitHub Actions（deploy.yml，收到 push 才動）
  → 發布到 GitHub Pages
```

GitHub 端沒有任何排程，也不執行 `build_board.py`。

## 檔案

| 路徑 | 說明 |
| --- | --- |
| `index.html` | 產生出來的看板首頁（GitHub Pages 根目錄） |
| `template.html` | 版面樣板，`__DATA__` 會被換成當次資料 |
| `data.json` | 當次資料 |
| `history/YYYYMMDDTHHMM.json` | 每次執行的原始快照 |
| `build_board.py` | 抓取與產生用的程式，由 Claude session 執行 |
| `.github/workflows/deploy.yml` | 收到 push 時部署到 Pages |

## 更新時間

每日台灣時間 07:00–21:00，每 2 小時一次（共 8 次）。

## 首次設定

Settings → Pages → Source 選 **GitHub Actions**（不是 Deploy from a branch）。

## 本機執行

```bash
pip install requests pillow
python build_board.py
```

會就地覆寫 `data.json`、`index.html` 並新增一筆 `history/` 快照。
需要連得到 `www.cwa.gov.tw`、`www.yr.no`、`www.meteoblue.com`。

## 資料來源

中央氣象署（鄉鎮逐時／一週預報、鄉鎮即時觀測、縣市 36 小時預報、特報、定量降水預報、雨量站）、
yr.no（MET Norway／ECMWF）、meteoblue。

所有數值均來自來源實測或實際預報，未經推估捏造；任一來源取得失敗會直接在看板上標示，
全部來源都失敗時不更新看板。
