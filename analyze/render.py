#!/usr/bin/env python3
"""把判讀結果（dict）渲染成 HTML 報告。

版型固定在這裡，內容由 report.json 提供 —— 判讀者只需產生 JSON，
不必每次重寫 CSS。純函式：render(report) -> str。
"""
import json, os, sys, html

CSS = """
:root{--bg:#080b12;--panel:#0e1420;--panel-2:#131b2a;--line:#1e2a3d;--ink:#dbe5f2;
 --dim:#7d8da5;--faint:#556377;--cyan:#35e0d8;--amber:#ffb636;--red:#ff5a6e;
 --green:#4ade80;--violet:#a78bfa;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.65;
 font-family:system-ui,-apple-system,"Noto Sans TC","Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
 background:radial-gradient(900px 500px at 12% -10%,rgba(53,224,216,.10),transparent 60%),
 radial-gradient(700px 400px at 95% 0%,rgba(167,139,250,.08),transparent 60%)}
.wrap{position:relative;z-index:1;max-width:1040px;margin:0 auto;padding:0 16px 72px}
header{padding-block:40px 24px;border-bottom:1px solid var(--line)}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.22em;color:var(--cyan);
 text-transform:uppercase;margin:0 0 10px;display:flex;align-items:center;gap:9px}
.eyebrow::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--cyan);box-shadow:0 0 12px var(--cyan)}
h1{margin:0;font-size:clamp(25px,4.6vw,38px);letter-spacing:-.02em;font-weight:650}
.sub{color:var(--dim);margin:10px 0 0;font-size:14.5px}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}
.chip{font-family:var(--mono);font-size:11.5px;color:var(--dim);border:1px solid var(--line);
 background:var(--panel);border-radius:999px;padding:5px 12px}
.chip b{color:var(--ink);font-weight:600}
h2{font-size:12px;font-family:var(--mono);letter-spacing:.2em;text-transform:uppercase;
 color:var(--faint);margin:44px 0 16px;padding-bottom:9px;border-bottom:1px solid var(--line)}
.alert{margin-top:14px;border:1px solid rgba(255,90,110,.42);border-left:3px solid var(--red);
 background:linear-gradient(90deg,rgba(255,90,110,.11),rgba(255,90,110,.02));border-radius:10px;padding:16px 18px}
.alert.amber{border-color:rgba(255,182,54,.42);border-left-color:var(--amber);
 background:linear-gradient(90deg,rgba(255,182,54,.10),rgba(255,182,54,.02))}
.alert .tag{font-family:var(--mono);font-size:11px;letter-spacing:.16em;color:var(--red);text-transform:uppercase;font-weight:700}
.alert.amber .tag{color:var(--amber)}
.alert h3{margin:7px 0 6px;font-size:17px}
.alert p{margin:0;color:var(--dim);font-size:14px}
.banner{margin-top:14px;border-radius:10px;padding:16px 18px;border:1px solid rgba(167,139,250,.4);
 border-left:3px solid var(--violet);background:linear-gradient(90deg,rgba(167,139,250,.10),rgba(167,139,250,.02))}
.banner .tag{font-family:var(--mono);font-size:11px;letter-spacing:.16em;color:var(--violet);text-transform:uppercase;font-weight:700}
.banner h3{margin:7px 0 8px;font-size:17px}
.banner p{margin:0 0 8px;color:var(--dim);font-size:14px}
.banner p:last-child{margin:0}
.nums{display:flex;flex-wrap:wrap;gap:20px;margin:12px 0;font-family:var(--mono)}
.nums div{font-size:12px;color:var(--faint)}
.nums b{display:block;font-size:21px;color:var(--ink);font-weight:600;margin-top:2px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(232px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:15px 16px;position:relative;overflow:hidden}
.card::after{content:"";position:absolute;inset:0 auto 0 0;width:2px;background:var(--rk,var(--faint))}
.card h3{margin:0;font-size:16.5px;font-weight:620}
.card .where{font-size:11.5px;color:var(--faint);font-family:var(--mono);margin-top:2px}
.pop{font-family:var(--mono);font-size:29px;font-weight:600;margin:12px 0 2px;color:var(--rk,var(--ink));letter-spacing:-.02em}
.pop small{font-size:13px;color:var(--faint);font-weight:400;margin-left:3px}
.card dl{margin:11px 0 0;padding-top:11px;border-top:1px solid var(--line);
 display:grid;grid-template-columns:auto 1fr;gap:5px 12px;font-size:13px}
.card dt{color:var(--faint);font-family:var(--mono);font-size:11.5px}
.card dd{margin:0;text-align:right;color:var(--ink)}
.card .src{margin-top:10px;font-family:var(--mono);font-size:10.5px;color:var(--faint);word-break:break-word}
.card .src.warn{color:var(--amber)}
.conflict{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:16px 18px;
 margin-bottom:11px;border-left:3px solid var(--amber)}
.conflict h3{margin:0 0 9px;font-size:15.5px;display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.verdict{font-family:var(--mono);font-size:10.5px;letter-spacing:.11em;text-transform:uppercase;
 padding:3px 9px;border-radius:4px;font-weight:700;white-space:nowrap}
.v-real{background:rgba(255,90,110,.16);color:var(--red)}
.v-scale{background:rgba(255,182,54,.16);color:var(--amber)}
.v-ok{background:rgba(74,222,128,.14);color:var(--green)}
.conflict p{margin:0 0 9px;color:var(--dim);font-size:14px}
.conflict p:last-child{margin-bottom:0}
.conflict .call{color:var(--ink);border-top:1px dashed var(--line);padding-top:9px;margin-top:11px}
.conflict .call b{color:var(--cyan);font-family:var(--mono);font-size:11.5px;letter-spacing:.1em;
 text-transform:uppercase;display:block;margin-bottom:3px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13.5px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:11px;background:var(--panel)}
th,td{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-family:var(--mono);font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;
 color:var(--faint);font-weight:600;background:var(--panel-2)}
tbody tr:last-child td{border-bottom:none}
td.g{color:var(--dim);white-space:normal;min-width:210px}
.note{background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--violet);
 border-radius:11px;padding:16px 18px;color:var(--dim);font-size:13.5px}
.note b{color:var(--ink)}
.note ul{margin:9px 0 0;padding-left:19px}
.note li{margin-bottom:6px}
.note li:last-child{margin-bottom:0}
footer{margin-top:52px;padding-top:20px;border-top:1px solid var(--line);
 color:var(--faint);font-size:12px;font-family:var(--mono);line-height:1.8}
a{color:var(--cyan);text-decoration:none;border-bottom:1px solid rgba(53,224,216,.3)}
a:hover{border-bottom-color:var(--cyan)}
.m{font-family:var(--mono)}
@media(max-width:560px){.grid{grid-template-columns:1fr}}
"""

def e(s):
    return html.escape(str(s), quote=False) if s is not None else ''

# 判讀文字要能強調關鍵字與換行，但不接受任意 HTML：先整段跳脫，再放行白名單。
_ALLOW = {'&lt;b&gt;': '<b>', '&lt;/b&gt;': '</b>', '&lt;br&gt;': '<br>',
          '&lt;m&gt;': '<span class="m">', '&lt;/m&gt;': '</span>'}

def _rich(s):
    out = e(s)
    for k, v in _ALLOW.items():
        out = out.replace(k, v)
    return out

def render(r):
    P = []
    P.append('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">')
    P.append('<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">')
    P.append(f'<title>{e(r["title"])}</title><style>{CSS}</style></head><body><div class="wrap">')

    P.append(f'<header><p class="eyebrow">{e(r.get("eyebrow","判讀報告"))}</p>')
    P.append(f'<h1>{e(r["title"])}</h1><p class="sub">{_rich(r.get("subtitle",""))}</p><div class="meta">')
    for k, v in r.get('chips', []):
        P.append(f'<span class="chip">{e(k)} <b>{e(v)}</b></span>')
    P.append('</div></header>')

    for a in r.get('alerts', []):
        cls = 'alert amber' if a.get('level') == 'amber' else 'alert'
        P.append(f'<div class="{cls}"><span class="tag">{e(a["tag"])}</span>'
                 f'<h3>{e(a["title"])}</h3><p>{_rich(a["body"])}</p></div>')

    if r.get('terrain'):
        t = r['terrain']
        P.append(f'<div class="banner"><span class="tag">{e(t["tag"])}</span><h3>{e(t["title"])}</h3>')
        P.append('<div class="nums">')
        for lbl, val in t['nums']:
            P.append(f'<div>{e(lbl)}<b>{e(val)}</b></div>')
        P.append('</div>')
        for p in t['paras']:
            P.append(f'<p>{_rich(p)}</p>')
        P.append('</div>')

    if r.get('locations'):
        P.append(f'<h2>{e(r.get("loc_heading","各地實測"))}</h2><div class="grid">')
        for c in r['locations']:
            P.append(f'<div class="card" style="--rk:var(--{e(c.get("rank","faint"))})">')
            P.append(f'<h3>{e(c["name"])}</h3><div class="where">{e(c.get("where",""))}</div>')
            P.append(f'<div class="pop">{_rich(c["value"])}</div><dl>')
            for k, v in c.get('rows', []):
                P.append(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>')
            P.append('</dl>')
            if c.get('src'):
                w = ' warn' if c.get('src_warn') else ''
                P.append(f'<div class="src{w}">{_rich(c["src"])}</div>')
            P.append('</div>')
        P.append('</div>')

    if r.get('findings'):
        P.append(f'<h2>{e(r.get("find_heading","判讀"))}</h2>')
        for f in r['findings']:
            P.append(f'<div class="conflict"><h3>{e(f["title"])} '
                     f'<span class="verdict {e(f.get("cls","v-scale"))}">{e(f["verdict"])}</span></h3>')
            for p in f.get('paras', []):
                P.append(f'<p>{_rich(p)}</p>')
            if f.get('call'):
                P.append(f'<p class="call"><b>判讀</b>{_rich(f["call"])}</p>')
            P.append('</div>')

    if r.get('outlook'):
        P.append(f'<h2>{e(r.get("out_heading","後續展望"))}</h2><div class="scroll"><table><thead><tr>')
        for h in r['outlook']['cols']:
            P.append(f'<th>{e(h)}</th>')
        P.append('</tr></thead><tbody>')
        for row in r['outlook']['rows']:
            cells = []
            for i, c in enumerate(row):
                cls = ' class="g"' if i == len(row) - 1 else ''
                cells.append(f'<td{cls}>{_rich(c)}</td>')
            P.append('<tr>' + ''.join(cells) + '</tr>')
        P.append('</tbody></table></div>')

    if r.get('method'):
        P.append(f'<h2>{e(r.get("method_heading","資料來源與方法"))}</h2><div class="note">')
        P.append(f'{_rich(r["method"]["lead"])}<ul>')
        for li in r['method']['items']:
            P.append(f'<li>{_rich(li)}</li>')
        P.append('</ul></div>')

    P.append(f'<footer>{_rich(r.get("footer",""))}</footer></div></body></html>')
    return '\n'.join(P)


if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else 'report.json'
    out = sys.argv[2] if len(sys.argv) > 2 else 'report.html'
    rep = json.load(open(src, encoding='utf-8'))
    open(out, 'w', encoding='utf-8').write(render(rep))
    print(f'{out} ← {src}  ({os.path.getsize(out)} bytes)')
