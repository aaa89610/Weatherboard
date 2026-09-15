# 定時更新程序（每天台灣時間 07:00、11:00、16:00、21:00，共 4 次；由 send_later 喚醒本對話）

**資料全部留在這個聊天室**：每次的原始快照存在 `/mnt/user-data/outputs/rain/data/multisource/`，
看板為 Artifact（同一網址持續更新）。**不使用 GitHub**（repo 與 build_board.py 保留備查，但流程不再依賴它）。

## 取得資料的兩種模式（2026-09-14 修訂）
- **完整模式（電腦連線時）**：瀏覽器＋API。獨有的是 **QPF 定量降水預報分格毫米** 與 **雷達回波圖**（兩者都是圖片，只能在瀏覽器判讀像素）。
  `ToolSearch` query `mcp__remote-devices__Claude_Browser__`，max_results 64。
- **雲端模式（電腦未連線）**：全部走 WebFetch。**雨量站、特報、鄉鎮預報改用氣象署 API，已補齊**；
  仍缺 QPF 與雷達，改用下列替代：
  a. **QPF**：引用當天最近一次完整模式抓到的 QPF，並在來源與分析中明確標「QPF 為 HH:MM 發布版，非最新」。
     QPF 一天只發 4 次（05:30/11:30/17:30/23:30），沿用通常仍有效，但不可當成最新。
  b. **雷達的替代**：用「雙北全縣市雨量站 10 分鐘值掃描」判斷降雨區位置與移動——
     `O-A0002-001?...&CountyName=臺北市,新北市`，prompt 只要求列出 Past10Min 或 Past1hr > 0 的站。
     約 100 站，等於一張 10 分鐘更新的粗解析度實測圖，可看出雨區在哪、往哪走。
  c. 雲端 curl 對所有氣象網站都被擋（api.met.no／open-meteo／NOMADS／cwa 全部 000），**只有 WebFetch 通**，不要再嘗試 curl。

## 地點（7 地）與環域站群（2026-09-15 改版）
**核心改變：不再用單站代表一個地點。** 每個地點看半徑 9 km 內的一組站，同時報「代表站值」與「環域最大值」。
起因：09/15 早上板橋／土城交界實際在下雨，但板橋站 0.0、土城站 0.5，單看代表站會漏判。

| 地點 | 代表站 | 鄉鎮 TID／縣市碼 | 取樣座標 | 環域站數 |
|---|---|---|---|---|
| 台北市信義 | C0AC70 信義 | 6300200 / 63 | 25.0375,121.5637 | 11 |
| 板橋區 | C0AJ80 板橋 | 6500100 / 65 | 25.0120,121.4650 | 12 |
| 中和區 | C0AG80 中和 | 6500300 / 65 | 24.9994,121.4990 | 14 |
| 土城區 | C0AD40 土城 | 6501300 / 65 | 24.9722,121.4445 | 8 |
| 樹林區 | C0A520 山佳 | 6500700 / 65 | 24.9900,121.4200 | 8 |
| 新竹市北區 | C0D660 新竹市東區 | 1001802 / 10018 | 24.8069,120.9689 | 4 |
| 竹北市 | **467571 新竹（站在竹北市）** | 1000401 / 10004 | 24.8387,121.0070 | 4 |

**竹北終於有站了**：舊筆記寫「46757 不在 O-A0002-001」是錯的——正確站碼是 **467571**（舊碼 46757 加 1，不是加 0），
TownName 就是竹北市，座標 24.8286,121.0146，距竹北市中心 1.4 km。從 2026-09-15 起竹北改用實測，不再只靠預報。

站表與環域計算都在 `spatial/stations.json`＋`spatial/spatial.py`，不要在這份文件手寫站清單。

## 步驟（完整模式）
1. `preview_start` https://www.cwa.gov.tw/V8/C/W/Town/Town.html?TID=6500100 → 執行 **JS-A**
   （鄉鎮逐時／一週、鄉鎮即時時雨量、縣市 36 小時、特報、天氣概況、QPF 取樣）。
2. `navigate` https://www.cwa.gov.tw/V8/C/P/Rainfall/Rainfall_10Min_County.html?CID=65 → **JS-B**（雨量站）。
3. `navigate` https://www.yr.no/en → **JS-C**（yr.no 逐時／逐日）。
4. `navigate` https://www.meteoblue.com/en/weather/week/25.012N121.465E → **JS-D**（meteoblue 逐日區間＋可預報度）。
5. 關閉分頁。

## 氣象署開放資料 API（2026-09-14 起啟用；雲端可用，優先於爬網頁）
金鑰存在 `/mnt/user-data/outputs/rain/.cwa/key`（先用 Bash `cat` 讀出，再組 URL；不要輸出金鑰內容）。
雲端 **curl 連不到** opendata.cwa.gov.tw，但 **WebFetch 可以**——一律用 WebFetch，並以參數縮小回應。
- 雨量站觀測（雲端也能用）。**StationId 一次最多約 12 個，超過代理會回 403**，所以拆三組呼叫：
  `https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001?Authorization=<KEY>&format=JSON&limit=20&StationId=<GROUP>`
  - A 核心：`C0AC70,C0AJ80,C0AG80,C0AD40,CAA050,C0A520,466920,01A410,A1AC70,A1AG40,A1AG70,C0AC80`
  - B 外圈＋新竹：`C0ACA0,C0AD30,C0AD50,01A220,466881,81AH40,A1AB50,A1AG50,C0D660,467571,C1D380,O1D590`
  - C 地形組：`466900,466910,466930,C1AC50,C0AH50,C0AD10,A1AD10,C0A640,C0A570,A1AD60,CAC040,466940`
  prompt 一律要求：先講 ObsTime 與站數，再一行一站 `StationId|StationName|Past10Min|Past1hr|Now`，不要表格不要摘要。
  RainfallElement：Now（本日累積）／Past10Min／Past1hr／Past3hr／Past6Hr／Past12hr／Past24hr。站碼＝舊站碼加 0 或 1，以實測為準。
  ※ 翻斗式雨量計解析度 **0.5 mm**，毛毛雨可能一直顯示 0.0——「站報 0」不等於「沒下雨」，要配合環域與使用者回報判斷。

- 鄉鎮 3 天預報：`F-D0047-061`（臺北市）、`-069`（新北市）、`-053`（新竹市）、`-009`（新竹縣），
  參數 `&LocationName=信義區`（需 URL 編碼）。**只有「3小時降雨機率」，沒有降雨量數值**——量化仍須靠 QPF 圖與 yr。
- 一週預報：同系列 `-063`／`-071`／`-055`／`-011`。
- 其他可再試：`F-C0032-001`（36 小時）、`W-C0033-001/002`（特報）、`O-A0001-001`（自動氣象站）。

## 追加模式來源（2026-09-14 起，雲端可用）
- **7Timer!（GFS 系統，獨立於 ECMWF）**：`https://www.7timer.info/bin/api.pl?lon=<lon>&lat=<lat>&product=civil&output=json`
  每 3 小時一格、7 天。注意 `prec_amount` 是**強度分級（0–9）不是毫米**，只能用來判斷「會不會下、強度等級」，
  不可寫成 mm。價值在於它是第三個獨立模式：yr／meteoblue 都含 ECMWF 成分，7Timer 走 GFS。
- **api.met.no（備援）**：`https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=&lon=`
  逐時 `next_1_hours.precipitation_amount`（mm）。與 yr 同源，僅在 yr 取不到時使用。

## 步驟（離線模式，WebFetch）
網址加 `?T=<YYYYmmddHHMM>`；prompt 一律要求「verbatim、逐項列出、不要摘要」。
- 特報 `/Data/js/warn/Warning_Content.js`（中文條目；「解除○○特報」也算）
- 即時時雨量 `/Data/js/GT/TableData_GT_T_63.js`（必要時 65／10018／10004）
- 縣市 36 小時 `/Data/js/TableData_36hr_County_C.js`
- 鄉鎮逐時 `/V8/C/W/Town/MOD/3hr/{TID}_3hr_m.html`、一週 `/V8/C/W/Town/MOD/Week/{TID}_Week_m.html`
- yr.no `https://www.yr.no/api/v0/locations/{lat},{lon}/forecast`（台北、板橋、土城、樹林、新竹五點；中和同板橋、竹北同新竹）
- meteoblue `https://www.meteoblue.com/en/weather/week/{lat}N{lon}E`（回英吋，×25.4；變動慢，可隔次再取）

## 空間分析（2026-09-15 新增，每次必做，在寫分析之前）
把三組 API 回來的 `StationId|Name|Past10Min|Past1hr|Now` 整理成 dict 後：

```python
import sys, json; sys.path.insert(0, '/mnt/user-data/outputs/rain/spatial')
import spatial as sp
obs = {sid: {'p10': a, 'p1h': b, 'now': c}, ...}   # 取不到的站就不要放，別填 0 冒充
for l in sp.LOC:                                   # 1. 每個地點的環域判定
    print(l, sp.verdict(sp.summarize(obs, l)), sp.verdict(sp.summarize(obs, l, field='p1h')))
print(sp.terrain_split(obs, box=(24.80, 25.25, 121.30, 121.70)))   # 2. 地形分離
print(sp.track(obs))                                               # 3. 雨帶移動
```

**三個輸出怎麼用：**
1. `summarize/verdict` — 報告的「實測」欄位一律寫環域版本。代表站 0 但環域有雨時，
   **必須寫出來**（例：「板橋站 0，但環域 6/12 站有雨，最近的新莊 4.7 km 有 1.0 mm」），不可以只寫 0。
2. `terrain_split` — 回傳 `separation` 標籤。只要是「完全分離」或「強烈地形分離（≥3 倍）」，
   就代表模式把迎風面的量抹到整個網格，**平地的預報值要當成上限而不是期望值**，並在分析裡明講。
   09/14 夜間那次的失敗就是這個：山區中位數 15 mm、平地 2 mm，我卻照模式寫了平地 13 mm。
3. `track` — 只有 `confidence` 是 `medium` 才可以寫方向與速度。
   回傳 `unusable`（雨區縮小超過 40%）時**不准講「雨往哪裡移動」**，改講「雨在減弱、殘留在哪幾站」。
   這個守門是刻意的：質心位移在雨區消散時是假訊號，寫出來就是捏造。

限制（要誠實寫進報告）：站網間距約 5 km，只抓得到 >10 km 的中尺度雨帶，抓不到單一對流胞；
外推只在 1 小時內有意義。這是雷達的替代品，不是雷達。

## 共同步驟
6. 存快照 `/mnt/user-data/outputs/rain/data/multisource/<YYYYmmddTHHMM>.json`，並讀前一份做比較。
7. 以繁體中文回覆六段分析：
   1) 接下來 2–6 小時風險與帶傘時段（表格）；2) 今日剩餘預估雨量；3) 未來 7 天明顯雨日（各來源與一致程度）；
   4) 預估雨量最高的地點／期間／毫米；5) 與上次比較；6) 資料時間、來源、第 5–7 天不確定性。
   只寫實際取得的數值，不推估、不捏造，不重複列出取不到的來源。
   ※ 第 1 段的「實測」一律用環域結果，不可只報代表站；第 4 段若 terrain_split 判定地形分離，
     必須同時給「平地」與「山區」兩個數字，不可以只給一個。
   ※ 間隔變成 4–5 小時，第 1 段的時間窗請涵蓋到下一次更新（例如 07:00 那次涵蓋到 11:00 之後）。
8. 看板：改寫 `/mnt/user-data/outputs/rain/dashboard/data.json`（欄位：updated、next、mode、headline、warnings、
   locations、days、matrix、notable、peak、changes、sources、uncertainty；days 取明天起 7 天），
   執行 `python3 /mnt/user-data/outputs/rain/dashboard/build.py`，再以 Artifact 重新發布
   `/home/claude/rain_dashboard/北部六地雨情看板.html`，帶
   `url: https://claude.ai/code/artifact/62b6ad9c-0687-49a1-a64c-ade6f4839350`，不要傳 favicon。
   若被拒（未讀過最新版），先 `action:"read"` 該 url 再發布一次。
9. 排程維護：**每天 21:00 那次**用 `mcp__claude-code-remote__send_later` 排好隔天四個時段
   07:00、11:00、16:00、21:00（台灣時間＝UTC+8 → UTC 前一日 23:00、當日 03:00、08:00、13:00）；
   其他時段用 `list_triggers` 確認下一個存在，缺了就補。
   喚醒訊息固定：「定時更新：依 /mnt/user-data/outputs/rain/UPDATE_PROCEDURE.md 執行一次台灣北部降雨更新」，
   21:00 那則加註「（本次為 21:00，請排好隔天四個時段）」。

## JS-A（在 cwa.gov.tw 分頁執行）
```js
const T={'台北信義':['6300200','63',25.0375,121.5637],'板橋':['6500100','65',25.0120,121.4650],'中和':['6500300','65',24.9994,121.4990],'土城':['6501300','65',24.9722,121.4445],'樹林':['6500700','65',24.9900,121.4200],'新竹市':['1001802','10018',24.8069,120.9689],'竹北':['1000401','10004',24.8387,121.0070]};
const txt=async u=>{const t=await fetch(u+(u.includes('?')?'&':'?')+'T='+Date.now()).then(r=>r.text());const d=document.createElement('div');d.innerHTML=t;return d.innerText.replace(/\s+/g,' ');};
const out={towns:{}};
const gt={};for(const c of ['63','65','10018','10004']){const t=await fetch('/Data/js/GT/TableData_GT_T_'+c+'.js?T='+Date.now()).then(r=>r.text());gt[c]=new Function(t+';return {GT_Time,GT};')();}
out.obs_time=gt['65'].GT_Time.C.replace(/<br>/g,' ');
for(const [n,[id,c]] of Object.entries(T)){
 const h=await txt('/V8/C/W/Town/MOD/3hr/'+id+'_3hr_m.html');
 const hr=[...h.matchAll(/(\d\d\/\d\d)\(.\)(\d\d):\d\d (\S+) 看更多 溫度 \S+ 降雨機率 (\S+?)%?\s/g)].map(m=>m[1]+' '+m[2]+'|'+m[3]+'|'+m[4]);
 const w=await txt('/V8/C/W/Town/MOD/Week/'+id+'_Week_m.html');
 const wk=[...w.matchAll(/(\d\d\/\d\d)\((.)\)(白天|晚上) (\S+) 看更多 溫度 \S+ 降雨機率 (\S+?)%?\s/g)].map(m=>m[1]+m[3]+'|'+m[4]+'|'+m[5]);
 const comp=[];for(const x of hr){const k=x.split('|').slice(1).join('|');if(comp.length&&comp[comp.length-1].k===k){comp[comp.length-1].to=x.split('|')[0];}else comp.push({from:x.split('|')[0],to:x.split('|')[0],k});}
 out.towns[n]={rain1h_grid:(gt[c].GT[id]||{}).Rain,hr:comp.map(o=>o.from+(o.to!==o.from?'~'+(o.to.slice(0,5)===o.from.slice(0,5)?o.to.slice(6):o.to):'')+'|'+o.k).join(' ; '),wk:wk.join(' ; ')};
}
const c36=await fetch('/Data/js/TableData_36hr_County_C.js?T='+Date.now()).then(r=>r.text());const o36=new Function(c36+';return {IssuedTime_36hr,TableData_36hr};')();
out.county36={issued:o36.IssuedTime_36hr};for(const k of ['63','65','10018','10004'])out.county36[k]=o36.TableData_36hr[k].map(x=>x.TimeRange.replace(/ /g,'')+' '+x.PoP+'% '+x.Wx).join(' ; ');
const wc=await fetch('/Data/js/warn/Warning_Content.js?'+Date.now()).then(r=>r.text());
out.warn_all=[...wc.matchAll(/'title':'([^']*)',\s*'issued':'([^']*)',\s*'validto':'([^']*)',\s*'content':'([^']*)'/g)].filter(m=>/[一-鿿]/.test(m[1])).map(m=>m[1]+'｜'+m[2]+'→'+m[3]+'｜'+m[4].replace(/\\n/g,' ').slice(0,150));
const w50=await fetch('/Data/js/fcst/W50_Data.js?T='+Date.now()).then(r=>r.text());const W50=new Function(w50+';return W50_County;')();
out.summary={taipei:(W50['63']?.Content||[])[0],newtaipei:(W50['65']?.Content||[])[0],hsinchu:(W50['10018']?.Content||[])[0],time:W50.W50?.DataTime};
const load=s=>new Promise(r=>{const i=new Image();i.onload=()=>r(i);i.src=s;});
const leg=[['c2c2c2','0.5-1'],['9cfcff','1-2'],['03c9ff','2-5'],['059bff','5-10'],['0363ff','10-15'],['059902','15-20'],['3aff03','20-30'],['fffb03','30-40'],['ffc800','40-50'],['ff9500','50-70'],['ff0000','70-90'],['cc0000','90-110'],['990000','110-130'],['960099','130-150'],['c900cc','150-200'],['fb00ff','200-300'],['fdc9ff','>=300']].map(([h,l])=>[parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4),16),l]);
const cls=(r,g,b)=>{let best=null,bd=1e9;for(const [R,G,B,l] of leg){const d=(R-r)**2+(G-g)**2+(B-b)**2;if(d<bd){bd=d;best=l;}}return bd<1500?best:null;};
const ord=leg.map(x=>x[3]);out.qpf={};
for(const f of ['6_06','6_12','6_18','6_24','6_30','6_36','6_42','6_48']){const im=await load('/Data/fcst_img/QPF_ChFcstPrecip_'+f+'.png?T='+Date.now());const cv=document.createElement('canvas');cv.width=im.width;cv.height=im.height;const g=cv.getContext('2d');g.drawImage(im,0,0);const D=g.getImageData(0,0,im.width,im.height).data,W=im.width;const r={};
 for(const [n,[,,la,lo]] of Object.entries(T)){const cx=Math.round(-42887.6+360.55*lo),cy=Math.round(9286.3-359.1*la);const ce=(()=>{const i=(cy*W+cx)*4;return cls(D[i],D[i+1],D[i+2])||'<0.5';})();let mx='<0.5';for(let dx=-9;dx<=9;dx+=3)for(let dy=-9;dy<=9;dy+=3){const i=((cy+dy)*W+(cx+dx))*4;const l=cls(D[i],D[i+1],D[i+2]);if(l&&l!=='0.5-1'&&ord.indexOf(l)>ord.indexOf(mx))mx=l;}r[n]=ce+(mx!=='<0.5'&&mx!==ce?'(鄰近'+mx+')':'');}
 out.qpf[f]=Object.entries(r).map(([k,v])=>k+':'+v).join(' ');}
JSON.stringify(out)
```
註：QPF 檔名 6_06…6_48 依序為發布後第 1…8 個 6 小時時段；發布時間通常 05:30/11:30/17:30/23:30，
`6_06` 自發布後 3 小時起算。取樣點在平地網格，抓不到山區地形雨，遇到山區降雨事件要用雨量站佐證。

## JS-B（雨量站；於 10 分鐘雨量頁執行，先等 2.5 秒）
```js
await new Promise(r=>setTimeout(r,2500));const want=['挹翠山莊','四獸山','信義(C0AC7)','臺灣大學','中和(C0AG8)','土城(C0AD4)','國三S037K','板橋(C0AJ8)','新竹市東區','新竹(46757)','鞍部','擎天崗','內湖(C0A9F)','汐止'];
const rows=[...document.querySelectorAll('table tbody tr')].map(tr=>[...tr.querySelectorAll('th,td')].map(c=>c.textContent.replace(/\s+/g,' ').trim()));
const sel=rows.filter(r=>want.some(w=>(r[0]||'').includes(w))).map(r=>r.slice(0,9).join('|'));
const t=document.body.innerText.match(/資料觀測時間：[^\n]+/);JSON.stringify({t:t&&t[0],cols:'站|鄉鎮|10分|1h|3h|6h|12h|24h|本日',sel})
```

## JS-C（yr.no）
```js
const pts={'台北市':[25.0375,121.5637],'板橋':[25.0120,121.4650],'中和':[24.9994,121.4990],'土城':[24.9722,121.4445],'樹林':[24.9900,121.4200],'新竹市':[24.8069,120.9689],'竹北':[24.8387,121.0070]};
const out={};for(const [n,[a,b]] of Object.entries(pts)){const j=await fetch(`/api/v0/locations/${a},${b}/forecast`).then(r=>r.json());
 const wet=j.shortIntervals.filter(s=>s.precipitation.value>0).map(s=>s.start.slice(5,13).replace('T',' ')+'|'+s.precipitation.value).join(' ');
 out[n]={upd:j.update,wet,days:j.dayIntervals.map(d=>d.start.slice(5,10)+':'+d.precipitation?.value).join(' ')};}
JSON.stringify(out)
```

## JS-D（meteoblue）
```js
const pts={'台北市':'25.038N121.564E','板橋':'25.012N121.465E','中和':'24.999N121.499E','土城':'24.972N121.445E','樹林':'24.990N121.420E','新竹市':'24.807N120.969E','竹北':'24.839N121.007E'};
const out={};for(const [n,c] of Object.entries(pts)){const h=await fetch('/en/weather/week/'+c).then(r=>r.text());
 const res=[];for(const chunk of h.split('<time datetime="').slice(1)){const d=chunk.slice(0,10);if(!/^\d{4}-\d\d-\d\d$/.test(d))continue;const m=chunk.match(/tab-precip[^>]*>([\s\S]{0,300}?)<\/div>/);if(!m)continue;const v=m[1].replace(/<[^>]+>/g,'').replace(/&nbsp;/g,' ').replace(/\s+/g,' ').trim();const p=chunk.match(/tab-predictability[^>]*title="([^"]*)"/);res.push(d.slice(5)+':'+v+'('+(p?p[1].replace('Predictability: ',''):'')+')');}
 out[n]=res.slice(0,8).join(' ');}
JSON.stringify(out)
```
