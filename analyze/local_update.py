#!/usr/bin/env python3
"""本機更新的固定步驟。判讀（改寫 report.json）夾在 prepare 與 publish 之間，
由 Claude 本機排程負責；這支只做不需要判斷的部分。

    .venv\\Scripts\\python.exe analyze\\local_update.py prepare
    .venv\\Scripts\\python.exe analyze\\local_update.py digest
    .venv\\Scripts\\python.exe analyze\\local_update.py publish -F <commit 訊息檔>

prepare  git pull → fetch_v2.py 抓取 → load.py --check
         結束碼 0：有新快照，要判讀；1：沒有新資料，跳過；2：pull 或抓取失敗
digest   印出 load.py 的跨時間摘要，並附上前 3 輪判讀紀錄（UTF-8，Windows 主控台不會亂碼）
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
    p = sub.add_parser('publish')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('-m', dest='message')
    g.add_argument('-F', dest='message_file')
    a = ap.parse_args()
    if a.cmd == 'prepare':
        sys.exit(prepare())
    if a.cmd == 'digest':
        sys.exit(digest())
    sys.exit(publish(a.message, a.message_file))
