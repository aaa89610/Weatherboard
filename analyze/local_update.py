#!/usr/bin/env python3
"""本機更新的固定步驟。判讀（改寫 report.json）夾在 prepare 與 publish 之間，
由 Claude 本機排程負責；這支只做不需要判斷的部分。

    .venv\\Scripts\\python.exe analyze\\local_update.py prepare
    .venv\\Scripts\\python.exe analyze\\local_update.py digest
    .venv\\Scripts\\python.exe analyze\\local_update.py check
    .venv\\Scripts\\python.exe analyze\\local_update.py publish -F <commit 訊息檔>

prepare  git pull → fetch_v2.py 抓取 → load.py --check
         結束碼 0：有新快照，要判讀；1：沒有新資料，跳過；2：pull 或抓取失敗
digest   印出 load.py 的跨時間摘要，並附上前 3 輪判讀紀錄（UTF-8，Windows 主控台不會亂碼）
check    查核 report.json：兩張表逐格對照最新快照、星期、判讀條數、HTML 實體、render 結果
         結束碼 0：通過；1：有錯誤（逐項列出）
publish  render.py → 本機 commit report.json / report.html → push 到 GitHub（觸發 Pages 部署）
         結束碼 0：完成或沒有變更；2：render 或 commit 失敗；
         3：push 失敗（commit 留在本機，下次一起推）

報告本機也看得到（report.html）；每一版報告與判讀紀錄（commit 訊息）都在 git 歷史裡，
下一輪判讀靠 `git log` 延續判準。data/ 與 history/ 只存在本機磁碟（.gitignore），不推上 GitHub。
commit 一律用 Weatherboard Bot 的 noreply 身分，不帶出本機的 git 帳號與信箱。
"""
import argparse, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SITE = ['report.json', 'report.html']
BOT = ['-c', 'user.name=Weatherboard Bot', '-c', 'user.email=aaa89610@users.noreply.github.com']

# 子程序一律 UTF-8；git 憑證缺失時立刻失敗，不要在排程裡卡在登入視窗
ENV = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
           GCM_INTERACTIVE='never', GIT_TERMINAL_PROMPT='0')


def run(args):
    print('$', ' '.join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, env=ENV).returncode


def git(*args):
    return run(['git', *args])


def prepare():
    if git('pull', '--rebase', '--autostash', 'origin', 'main'):
        print('git pull 失敗，本次不更新。')
        return 2
    if run([PY, os.path.join('analyze', 'fetch_v2.py')]):
        print('抓取失敗（一站都沒抓到），本次不更新。')
        return 2
    return run([PY, os.path.join('analyze', 'load.py'), '--check'])


def digest():
    rc = run([PY, os.path.join('analyze', 'load.py')])
    # 前幾輪的判讀紀錄（判準、待辦）在 commit 訊息裡，一併印出，
    # 排程就不必自己 cd 進來跑 git——那會觸發每次都要人工確認的安全詢問
    print('\n── 前 3 輪判讀紀錄（git log）──', flush=True)
    git('--no-pager', 'log', '-3', '--format=%n=== %h %ad%n%B', '--date=format:%Y-%m-%d %H:%M',
        '--grep=^判讀 [0-9]')
    return rc


LOC_COLS = [('台北市',), ('板橋區', '中和區'), ('土城區', '樹林區'), ('新竹市', '竹北市')]
TEMP_COLS = ['台北市', '板橋區', '新竹市']          # 新北四區以板橋為代表；新竹與竹北合併一欄


def _round(x):
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(x)).quantize(Decimal('1'), ROUND_HALF_UP))


def check():
    """查核 report.json 與最新快照是否一致。每次判讀後必跑，免得排程自己臨時寫檢查程式。

    錯誤（結束碼 1）：source_stamp、兩張表逐格數值、星期、判讀條數、HTML 實體、render 結果。
    提醒（不算錯）：上一版報告的時刻仍出現在內文——若是刻意對照可以保留。
    """
    import datetime as dt, glob, json, re
    sys.path.insert(0, os.path.join(ROOT, 'analyze'))
    import render

    snaps = sorted(glob.glob(os.path.join(ROOT, 'data', 'v2', '2*.json')))
    snap = json.load(open(snaps[-1], encoding='utf-8'))
    rep = json.load(open(os.path.join(ROOT, 'report.json'), encoding='utf-8'))
    yr = snap['forecasts']['yr']
    errs, warns = [], []
    wd = '一二三四五六日'
    strip = lambda c: re.sub(r'</?b>', '', c).strip()
    mm = lambda v: '0' if v == 0 else f'{v:.1f}'

    if rep.get('source_stamp') != snap['stamp']:
        errs.append(f"source_stamp 是 {rep.get('source_stamp')}，最新快照是 {snap['stamp']}")

    def date_ok(label, where):
        md, w = label.split()
        d = dt.date(int(snap['stamp'][:4]), int(md[:2]), int(md[3:]))
        if wd[d.weekday()] != w:
            errs.append(f'{where} {md} 星期應為「{wd[d.weekday()]}」，寫成「{w}」')
        return md

    for row in rep.get('outlook', {}).get('rows', []):
        md = date_ok(row[0], '雨量表')
        try:
            exp = [' / '.join(mm(yr['by_loc'][l][md]) for l in grp) for grp in LOC_COLS]
        except KeyError:
            errs.append(f'雨量表 {md}：快照裡沒有這一天'); continue
        got = [strip(c) for c in row[1:5]]
        if exp != got:
            errs.append(f'雨量表 {md}：應為 {exp}，寫成 {got}')

    t = yr.get('temp_c', {})
    for row in rep.get('outlook_extra', {}).get('rows', []):
        md = date_ok(row[0], '氣溫表')
        try:
            exp = [f"{_round(t[l][md]['min'])} – {_round(t[l][md]['max'])}" for l in TEMP_COLS]
        except KeyError:
            errs.append(f'氣溫表 {md}：快照裡沒有這一天'); continue
        got = [strip(c) for c in row[1:4]]
        if exp != got:
            errs.append(f'氣溫表 {md}：應為 {exp}，寫成 {got}')

    n = len(rep.get('findings', []))
    if not 3 <= n <= 5:
        errs.append(f'判讀 {n} 條，應為 3–5 條')
    for f in rep.get('findings', []):
        if not f.get('call'):
            errs.append(f"判讀「{f.get('title', '')}」沒有 call（卡片主文）")
    if 'terrain' in rep:
        errs.append('report.json 不要放 terrain 欄位')

    text = json.dumps(rep, ensure_ascii=False)
    ents = sorted(set(re.findall(r'&[a-zA-Z#0-9]+;', text)))
    if ents:
        errs.append(f'內文有 HTML 實體 {ents}，請改成中文字')

    try:
        prev = json.loads(subprocess.run(['git', 'show', 'HEAD:report.json'], cwd=ROOT,
                                         capture_output=True, env=ENV).stdout.decode('utf-8'))
        pst = prev.get('source_stamp', '')
        old_times = {pst[11:16]} | set(re.findall(r'\d\d:\d\d', ' '.join(map(str, prev.get('chips', [])))))
        for tm in sorted(x for x in old_times if x):
            for m in re.finditer(re.escape(tm), text):
                warns.append(f'上一版的時刻 {tm} 仍出現：…{text[max(0, m.start() - 25):m.end() + 15]}…')
    except Exception as e:                                   # noqa: BLE001
        warns.append(f'讀不到上一版報告，跳過舊時刻掃描（{type(e).__name__}）')

    html = render.render(rep)
    preview = os.path.join(os.environ.get('TEMP', ROOT), 'weatherboard_preview.html')
    open(preview, 'w', encoding='utf-8').write(html)
    if html.count('<table') != 2:
        errs.append(f"render 後表格 {html.count('<table')} 張，應為 2 張")
    if '&lt;' in html:
        errs.append('render 後出現被跳脫的標記（只接受 <b> <br> <m>）')

    counts = {k: html.count(v) for k, v in
              (('表格', '<table'), ('特報', 'class="alert'), ('詳細說明', 'class="more"'), ('過舊橫幅', '資料非即時'))}
    rows = (len(rep.get('outlook', {}).get('rows', [])), len(rep.get('outlook_extra', {}).get('rows', [])))
    print(f"快照 {os.path.basename(snaps[-1])}｜判讀 {n} 條｜雨量表 {rows[0]} 列｜氣溫表 {rows[1]} 列"
          f"｜render：" + '、'.join(f'{k} {v}' for k, v in counts.items()) + f"｜預覽 {preview}")
    for w in warns:
        print('提醒：', w)
    for e in errs:
        print('錯誤：', e)
    print('查核通過' if not errs else f'查核未通過：{len(errs)} 項錯誤，改完再跑一次')
    return 0 if not errs else 1


def publish(message, message_file):
    if run([PY, os.path.join('analyze', 'render.py'), 'report.json', 'report.html']):
        print('render.py 失敗，不 commit。')
        return 2
    git('add', '--', *SITE)
    if git('diff', '--cached', '--quiet') == 0:
        print('report 沒有變更，不 commit。')
    else:
        msg = ['-F', message_file] if message_file else ['-m', message]
        if git(*BOT, 'commit', *msg):
            return 2
    # 沒有新 commit 也要推：上一輪 push 失敗留在本機的 commit 會在這裡補推
    for _ in range(2):
        if git('push', 'origin', 'main') == 0:
            return 0
        git('pull', '--rebase', 'origin', 'main')
    print('push 失敗：commit 已留在本機，下次 publish 會一起推上去。'
          '若是憑證問題，請在終端機手動執行一次 git push 完成 GitHub 登入。')
    return 3


if __name__ == '__main__':
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('prepare')
    sub.add_parser('digest')
    sub.add_parser('check')
    p = sub.add_parser('publish')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('-m', dest='message')
    g.add_argument('-F', dest='message_file')
    a = ap.parse_args()
    if a.cmd == 'prepare':
        sys.exit(prepare())
    if a.cmd == 'digest':
        sys.exit(digest())
    if a.cmd == 'check':
        sys.exit(check())
    sys.exit(publish(a.message, a.message_file))
