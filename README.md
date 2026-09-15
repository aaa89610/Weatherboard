# Weatherboard — 台灣北部六地逐時降雨預測

自動更新的降雨看板：台北市、新北市板橋／中和／土城、新竹市、新竹縣竹北市。

網頁：<https://aaa89610.github.io/Weatherboard/>

## 檔案

| 路徑 | 說明 |
| --- | --- |
| `index.html` | 產生出來的看板首頁（GitHub Pages 根目錄） |
| `template.html` | 版面樣板，`__DATA__` 會被換成當次資料 |
| `data.json` | 當次資料 |
| `history/YYYYMMDDTHHMM.json` | 每次執行的原始快照 |
| `build_board.py` | 抓資料並產生上面三者 |
| `.github/workflows/update.yml` | 定時執行與部署 |

## 自動更新

`.github/workflows/update.yml` 由 GitHub Actions 排程觸發，每次執行會：

1. 跑 `build_board.py` 抓各來源資料，重新產生 `data.json`、`index.html` 與 `history/` 快照
2. 有變動就 commit 並推回本分支
3. 把整個目錄部署到 GitHub Pages

更新時間：每日台灣時間 07:00–21:00，每 2 小時一次（共 8 次）。
GitHub 的排程是盡力而為，尖峰時段可能延遲數分鐘到數十分鐘。

不需要任何 API key 或 secret，所有來源都是公開頁面。

想立刻更新一次：Actions → 「更新降雨看板」 → Run workflow。

## 首次設定

Settings → Pages → Source 選 **GitHub Actions**（不是 Deploy from a branch），
workflow 裡的部署步驟才會生效。

## 本機測試

```bash
pip install requests pillow
python build_board.py
```

會就地覆寫 `data.json`、`index.html` 並新增一筆 `history/` 快照。

## 資料來源

中央氣象署（鄉鎮逐時／一週預報、鄉鎮即時觀測、縣市 36 小時預報、特報、定量降水預報、雨量站）、
yr.no（MET Norway／ECMWF）、meteoblue。

所有數值均來自來源實測或實際預報，未經推估捏造；任一來源取得失敗會直接在看板上標示。
