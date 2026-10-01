#!/usr/bin/env python3
"""本機更新的固定步驟。判讀（改寫 report.json）夾在 prepare 與 publish 之間，
由 Claude 本機排程負責；這支只做不需要判斷的部分。全部在本機完成，不連 GitHub。

    .venv\\Scripts\\python.exe analyze\\local_update.py prepare
    .venv\\Scripts\\python.exe analyze\\local_update.py digest
    .venv\\Scripts\\python.exe analyze\\local_update.py publish -F <commit 訊息檔>

prepare  fetch_v2.py 抓取 → load.py --check
         結束碼 0：有新快照，要判讀；1：沒有新資料，跳過；2：抓取失敗
digest   印出 load.py 的跨時間摘要（UTF-8，Windows 主控台不會亂碼）
publish  render.py 產生 report.html → 在本機 git commit report.json / report.html
         結束碼 0：完成或沒有變更；2：render 或 commit 失敗

報告直接用瀏覽器開 report.html。每一版報告與判讀紀錄（commit 訊息）都留在本機 git，
下一輪判讀靠 `git log` 延續判準。data/ 與 history/ 直接存在本機磁碟，不進 git。
"""
import argparse, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SITE = ['report.json', 'report.html']
BOT = ['-c', 'user.name=Weatherboard Bot', '-c', 'user.email=weatherboard@localhost']

# 子程序一律 UTF-8
ENV = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')


def run(args):
    print('$', ' '.join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, env=ENV).returncode


def git(*args):
    return run(['git', *args])


def prepare():
    if run([PY, os.path.join('analyze', 'fetch_v2.py')]):
        print('抓取失敗（一站都沒抓到），本次不更新。')
        return 2
    return run([PY, os.path.join('analyze', 'load.py'), '--check'])


def digest():
    return run([PY, os.path.join('analyze', 'load.py')])


def publish(message, message_file):
    if run([PY, os.path.join('analyze', 'render.py'), 'report.json', 'report.html']):
        print('render.py 失敗，不 commit。')
        return 2
    git('add', '--', *SITE)
    if git('diff', '--cached', '--quiet') == 0:
        print('report 沒有變更，不 commit。')
        return 0
    msg = ['-F', message_file] if message_file else ['-m', message]
    if git(*BOT, 'commit', *msg):
        return 2
    print(f"報告已更新：{os.path.join(ROOT, 'report.html')}")
    return 0


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
