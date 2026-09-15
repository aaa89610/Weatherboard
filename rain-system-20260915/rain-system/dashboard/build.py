"""把 data.json 注入 template.html，輸出可發布的看板 HTML。用法：python3 build.py"""
import json, pathlib
here = pathlib.Path(__file__).parent
data = json.loads((here / "data.json").read_text(encoding="utf-8"))
html = (here / "template.html").read_text(encoding="utf-8")
payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
out = html.replace("__DATA__", payload)
(here / "index.html").write_text(out, encoding="utf-8")
pub = pathlib.Path("/home/claude/rain_dashboard/北部六地雨情看板.html")
pub.parent.mkdir(parents=True, exist_ok=True)
pub.write_text(out, encoding="utf-8")
print("built", pub, len(out))
