# 台灣北部逐時降雨預測與驗證 — 交接說明（給 Claude Code）

> 建議放在 repo 根目錄命名為 `CLAUDE.md`，Claude Code 會自動讀取。
> 最後更新：2026-09-13（台灣時間）

---

## 1. 任務規格（不可改動的部分）

| 項目 | 內容 |
|---|---|
| 地點 | 台北市（信義）、新北市板橋／中和／土城、新竹市（北區）、新竹縣竹北市。**不含**基隆、宜蘭、桃園 |
| 更新頻率 | 每日台灣時間 07:00–21:00，每 2 小時一次，共 8 次 |
| 預報範圍 | 未來 7 天（168 小時）逐時降雨機率與雨量 |
| 語言 | 一律繁體中文 |
| 硬性原則 | **不得捏造成功率、雨量或缺失資料**。取不到的來源就標示取不到，欄位留白 |

每次輸出必須含六段：
1. 接下來 2–6 小時降雨風險與建議帶傘時段
2. 今日剩餘預估雨量
3. 未來 7 天雨勢較明顯的日期
4. 預估雨量最高的地點／期間／毫米數
5. 與上次預報相比的變化
6. 資料更新時間、來源、第 5–7 天不確定性

---

## 2. 現行架構

兩條**互不依賴**的線：

**A. 網站（GitHub 背景作業）** — https://github.com/aaa89610/Weatherboard
```
build_board.py          抓 7 個來源 → 算 → 產生 data.json + index.html + history/<stamp>.json
template.html           看板樣板，用 __DATA__ 佔位注入 JSON
setup/update.yml        GitHub Actions 排程（尚未安裝到 .github/workflows/，見第 6 節）
data.json / index.html  當次結果；GitHub Pages 首頁
history/*.json          每次原始快照（驗證用）
```
Actions cron：`5 23,1,3,5,7,9,11,13 * * *`（UTC）＝台灣 07/09/11/13/15/17/19/21 時 05 分。
用內建 `GITHUB_TOKEN` commit，`permissions: contents: write`，不需要額外密鑰。

**B. 判讀（聊天）** — 每 2 小時讀回 GitHub 產出＋自行補抓特報與最新預報，寫六段中文分析。
程式算不出來的部分（模式下修、來源互相矛盾、要不要改行程）由這條線負責。

---

## 3. 資料來源與解析要點

全部無需 API key。CWA 網址一律加 `?T=<timestamp>` 避開快取。

| 來源 | 端點 | 解析重點 |
|---|---|---|
| 鄉鎮逐時（1/3 小時，3 天） | `/V8/C/W/Town/MOD/3hr/{TID}_3hr_m.html` | 去標籤＋收斂空白後 regex：`(\d\d/\d\d)\(.\) (\d\d):\d\d (\S+) 看更多 溫度 [\d\s]+ 降雨機率 (\d+|-)`。溫度是「29 84」兩個數字，不能用 `\S+` |
| 鄉鎮一週（7 天，白天/晚上） | `/V8/C/W/Town/MOD/Week/{TID}_Week_m.html` | 同上，溫度段改 `[\d~\s]+`；第 4 天以後 PoP 常為 `-` |
| 鄉鎮即時時雨量 | `/Data/js/GT/TableData_GT_T_{縣市碼}.js` | `GT_Time = {'C':'…'}`；`'{TID}':{…'Rain':'0.0'…}` |
| 縣市 36 小時 | `/Data/js/TableData_36hr_County_C.js` | `IssuedTime_36hr`；每縣市區塊內 TimeRange／PoP／Wx |
| 特報 | `/Data/js/warn/Warning_Content.js` | 中英各一份，只取 title 含中文者；內容過濾 `臺北|新北|新竹|北部|大臺北|北臺`。**「解除○○特報」也是一則特報**，別漏 |
| 天氣概況 | `/Data/js/fcst/W50_Data.js` | 各縣市 `'Content':[…]` 第一段 |
| 定量降水預報 QPF | `/Data/fcst_img/QPF_ChFcstPrecip_6_{06..48}.png` | 圖 1245×1500。像素校正：`x = -42887.6 + 360.55*lon`、`y = 9286.3 - 359.1*lat`（±3 km）。比對圖例 17 色求最近色，色距 >1500 視為無值。發布時間 05:30/11:30/17:30/23:30，`6_06` 起算為發布後 3 小時 |
| 雨量站（10 分鐘） | `/V8/C/P/Rainfall/MOD_10M/10Min_MOD.html?ID=40786` | 一次拿全台。以 `(站碼)` 定位，之後 11 個數值依序為 10分/1h/3h/6h/12h/24h/**本日**/…，`-` 表示 0 |
| yr.no（MET Norway／ECMWF） | `https://www.yr.no/api/v0/locations/{lat},{lon}/forecast` | 純 JSON：`update`、`dayIntervals[].precipitation.value`、`shortIntervals[]`（逐時） |
| meteoblue（多模式） | `https://www.meteoblue.com/en/weather/week/{lat}N{lon}E` | 以 `<time datetime="` 切塊，每塊找 `tab-precip[^>]*>` 與 `tab-predictability … title=`。**用 WebFetch 抓會回英吋，要 ×25.4**；直接 requests 抓則是 mm |

站碼：信義 C0AC7、四獸山 A1AG4、挹翠山莊 A1AC7、板橋 C0AJ8、中和 C0AG8、土城 C0AD4、國三S037K CAA05、新竹市東區 C0D66、竹北 46757。
山區參考站：鞍部 46691、擎天崗 A1AD1、內湖 C0A9F、汐止 C0AH0。

TID／縣市碼：台北信義 6300200/63、板橋 6500100/65、中和 6500300/65、土城 6501300/65、新竹市北區 1001802/10018、竹北 1000401/10004。

---

## 4. 環境限制（踩過的坑，別重蹈）

- **Open-Meteo 完全不可用**：本工作階段的 egress 政策擋掉 api.open-meteo.com（CONNECT 403），WebFetch 則因 robots 拒絕。原本以它為基準的 pipeline（`rain_pipeline/`）已寫好並通過離線測試，但一直沒能連線。**Claude Code 在你自己的機器上沒有這個限制，可以直接把 Open-Meteo 加回來當基準模式**，這是目前最值得做的升級。
- **雲端沙箱不能寫 GitHub**：git push 被代理擋（`not in this session's authorized repository set`），GitHub API 也被閘門攔截。Claude Code 在本機用 `gh` 或 git 就沒這問題。
- **Artifact 公開分享一定會釘選版本**，無法「公開＋永遠最新」；`db` 能力可即時更新但強制組織內部，不能公開。這是改用 GitHub Pages 的原因。
- **fine-grained PAT** 推 `.github/workflows/*` 需要 **Workflows: write**；開 Pages 需要 **Pages: write**（權限已補齊）。
- 每次 `device_bash`（若有用到本機橋接）是全新 shell、約 45 秒上限，且掛載資料夾內不能刪檔，git 無法在其中運作（lock 檔刪不掉）。

---

## 5. 尚未完成的工作（優先序）

1. **安裝 Actions 排程**：把 `setup/update.yml` 複製到 `.github/workflows/update.yml` 並 push；到 Settings → Pages 設 `main /(root)`。這一步做完網站就會自己活起來。
2. **首次執行驗錯**：`build_board.py` 的抓取邏輯只在瀏覽器端逐條驗證過對應格式，尚未在真實網路整跑過。第一次 Actions 執行後看 log 與 `data.json`，重點檢查 QPF 像素取樣、雨量站欄位對齊、meteoblue 單位。
3. **加回 Open-Meteo Best Match 當基準**，並保留現有三家做多模式比較（原始 pipeline 在 `rain_pipeline/`，含 net/store/verify/report/excel_writer 模組，可直接移植）。
4. **驗證與校正**（原始需求，目前狀態為「校正待驗證」）：
   - 用 `history/*.json` 的預報快照，事後與雨量站實測配對
   - **依地點 × 預報提前時間分別驗證**，滾動 90 天窗口，測試期至少 7 天
   - 只有在獨立驗證確實改善（MAE 下降）時才啟用校正；資料不足一律標「校正待驗證」
5. **Excel**：《台灣北部_7天逐時降雨預測.xlsx》尚未產出（原 pipeline 的 `excel_writer.py` 已寫好：逐時預報、逐日彙總、趨勢圖、來源、實測配對、驗證結果六個工作表；圖表要設 `smooth=False` 並用文字類別軸，否則會畫成迴圈）。更新失敗時必須保留原檔。

---

## 6. 交接後的建議做法

```bash
git clone https://github.com/aaa89610/Weatherboard.git && cd Weatherboard
pip install requests pillow
python build_board.py          # 本機就能整跑，會直接產生 data.json / index.html
mkdir -p .github/workflows && cp setup/update.yml .github/workflows/
git add -A && git commit -m "啟用自動更新" && git push
gh api -X POST repos/aaa89610/Weatherboard/pages -f 'source[branch]=main' -f 'source[path]=/'
```
之後每次改動用 `python build_board.py` 本機驗證再 push；Actions 失敗會在 repo 的 Actions 頁顯示。

檢查網站有沒有自動更新：`curl -s https://raw.githubusercontent.com/aaa89610/Weatherboard/main/data.json | jq .updated`

---

## 7. 目前這個聊天室還在跑的東西（要不要保留由你決定）

- 8 個 `send_later` 排程（每天 21:00 那次會自動排隔天八個），喚醒訊息指向 `UPDATE_PROCEDURE.md`
- Artifact 看板（artifact id `62b6ad9c-0687-49a1-a64c-ade6f4839350`），目前到 Version 14
- 原始快照：09/11 21:00 起共 14 筆，已在 repo 的 `history/` 內（09/13 之後的還沒推上去）

要停掉聊天室這條線，把那些排程刪掉即可；網站不受影響。
