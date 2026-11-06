# 雲端排程任務的執行步驟

這份是 claude.ai 雲端排程任務「Weatherboard 雲端判讀」每次執行的完整步驟。
排程任務的 prompt 只寫「照 analyze/CLOUD_TASK.md 執行」，流程改這份檔案即可，不必回 UI 改任務。

**每次觸發都是全新 session，沒有上一輪的記憶。** 跨輪延續全部靠 git 歷史：
報告存在 `report.json` 的歷史裡，判準、守門判定、待辦存在每次 commit 的訊息裡。

## 前提（排程任務的設定）

排程任務必須在 claude.ai 的設定裡**附上 repository `aaa89610/Weatherboard`**
（編輯任務 → Advanced settings → Repository）。沒附上的話，session 自己 `git clone` 讀得到，
但 push 會被 git proxy 擋（403），判讀做完也發布不了。

## 步驟

1. 裝套件：

       python3 -m pip install -q requests pillow

   **用 `python3 -m pip`，不要用 `pip`**——雲端映像的 `pip` 綁的是另一個 Python，
   裝完 `python3` 仍然 `import requests` 失敗。

2. 抓取並判斷有沒有新資料：

       python3 analyze/local_update.py prepare

   最後一行印出結束碼：
   - `0` 有新快照 → 繼續
   - `1` 沒有新資料 → **立刻結束**，回報一句即可，不改任何檔案
   - `2` pull 或抓取失敗 → 回報錯誤後結束，**不要編造資料**

   log 的「來源」若是 `scrape` 而非 `opendata-api`，代表 `CWA_KEY` 沒讀到或 API 失敗，
   仍可運作但觀測時刻只能以區間表示，報告裡要據實寫。

3. 讀摘要：

       python3 analyze/local_update.py digest

   然後用 **Read 工具**讀 `/tmp/weatherboard_digest.txt` 全文（約 50 KB，分段讀）。
   內容是本次快照的跨時間摘要，加上**前 3 輪判讀紀錄**（commit 訊息全文）。

4. 判讀，改寫 `report.json`：
   - `source_stamp` 設成本次快照的 `stamp`
   - 結構照現有 `report.json`，兩張表都要更新（見下方「報告內容」）

5. 查核：

       python3 analyze/local_update.py check

   結束碼 `1` 就照列出的錯誤改，改到 `0` 為止。「提醒」不算錯，但要逐條看過。

6. 寫 commit 訊息到暫存檔，然後發布：

       python3 analyze/local_update.py publish -F /tmp/weatherboard_commit.txt

   `publish` 會 render、commit `report.json` / `report.html`、**push 到 main**（觸發 Pages 部署）。
   **不要推到 `claude/` 開頭的分支**——Pages 只從 main 發布，推到別的分支等於沒更新。

## 雲端與本機的差異（重要）

`data/` 不推上 GitHub（`.gitignore`），所以雲端每次只有**本次抓的這一筆快照**，
`digest` 會顯示「v2 快照 1 筆」。這是正常的。

- 上一輪的數字（yr 逐日雨量、氣溫、測站值、氣象署逐時）**一律從 digest 裡的判讀紀錄取**，
  不要假設手邊有舊快照
- 因此 **commit 訊息就是下一輪唯一的記憶**。訊息要照前幾輪的格式寫完整：
  第一行摘要、判讀重點，以及「待辦（下一輪 …）」區塊——
  下一輪要比對的具體數字、邊界值、要追蹤的變化都寫進去，下一輪才接得上

## 報告內容

這是**降雨看板**，氣溫是固定內容。只放跟「七地會不會下雨、下多少、多熱」直接相關的。

兩張表都要每次更新：
- `outlook` — 未來逐日雨量（yr.no，mm），台北／板橋中和／土城樹林／新竹竹北
- `outlook_extra` — 未來逐日氣溫（`forecasts.yr.temp_c`），台北市／新北四區／新竹竹北

**不寫進報告**（`render.py` 也會擋）：
- 強風、長浪、高溫特報——即使涵蓋本區
- 不涵蓋本區的特報（`areas_ours` 為空）
- `terrain` 欄位
- 方法論：守門逐項觸發與否、`track()` 為何不可判讀、缺測影響哪項統計——寫進 commit 訊息

三道守門照樣套用，只是不寫出來：
- 代表站 0 但環域有雨 → 實測欄位用環域值，寫成「局部有雨」
- `terrain_split` 判「完全分離」或「≥3 倍」→ 平地的模式預報值當上限
- `track` 回 `unusable` 或 `none` → 不提任何降雨移動方向

容易搞錯的：
- 翻斗式雨量計解析度 0.5 mm，「站報 0」不等於「沒下雨」
- 「0 / N」是 N 站確認無雨；查無資料是另一回事
- 特報同一天內會改版，範圍會擴大也會縮小，以最新一則為準

## 鐵則

只寫實際取得的數值。取不到標「未取得」，**不以鄰區數值代填、不內插、不編造**。
缺測站直接排除，不以 0 補。
