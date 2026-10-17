#!/usr/bin/env python3
"""舆情总览（dashboard）：一页看全所有桥账本 + 产品库 + 最近报告，并能一键启动各 store 的控制台。

为什么需要：桥的控制台一次只能看一个 store；S1/S3/S4/S5 各自独立，用固定端口很难记。
这个页面把**所有 store** 汇总到一页，并给出每个 store 的"打开控制台"按钮（未启动就自动起）。

用法：
  python -B dashboard.py [--port 8770] [--config <json>]
配置：默认读同目录 dashboard.config.json；不存在则自动扫描生成。

只读：只读取 state.json / attempt.json / result.json / 产品库（mode=ro）/ 报告目录，不修改任何东西。
"""
import argparse
import glob
import html
import json
import pathlib
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = HERE / "dashboard.config.json"
PY = sys.executable
WEBUI = pathlib.Path(r"C:\Users\Lenovo\Documents\Codex\2026-10-14\seeker-agent-agent-agent\outputs\agent-bridge-installed\webui.py")

DEFAULT_STORES = [
    {"key": "s1", "label": "S1 采集", "path": r"D:\DSH\output\2026-10-16\2026-10-16-18-03-28\_s1\store", "console_port": 8768},
    {"key": "s3", "label": "S3 相关性/证据", "path": r"D:\DSH\output\2026-10-16\2026-10-16-18-03-28\_s3\store", "console_port": 8769},
    {"key": "s4", "label": "S4 事件聚类", "path": r"D:\DSH\output\2026-10-16\2026-10-16-18-03-28\_s4\store", "console_port": 8771},
    {"key": "s5", "label": "S5 立场标注", "path": r"D:\DSH\output\2026-10-16\2026-10-16-18-03-28\_s5\store", "console_port": 8772},
    {"key": "e2e", "label": "E2E 桥验收", "path": r"D:\DSH\output\2026-10-16\2026-10-16-18-03-28\_e2e\store", "console_port": 8765},
    {"key": "bridge", "label": "桥真实账本", "path": r"C:\Users\Lenovo\Documents\Codex\bridge-work\data", "console_port": 8766},
]
DEFAULT_REPORTS = r"D:\DSH\output\2026-10-16\2026-10-16-18-03-28"
DEFAULT_DB = r"C:\Users\Lenovo\Documents\Codex\2026-10-15\c-users-lenovo-documents-codex-handoffs\outputs\sentiment-monitor\sentiment.db"


def load_config():
    if not CONFIG.is_file():
        cfg = {"port": 8770, "reports_dir": DEFAULT_REPORTS, "db": DEFAULT_DB, "stores": DEFAULT_STORES}
        CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        return cfg
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"port": 8770, "reports_dir": DEFAULT_REPORTS, "db": DEFAULT_DB, "stores": DEFAULT_STORES}


def port_open(port):
    import socket
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def read_json(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def store_tasks(store_path):
    out = []
    for sp in sorted(pathlib.Path(store_path).glob("tasks/*/state.json")):
        st = read_json(sp) or {}
        task_dir = sp.parent
        attempt = st.get("current_attempt")
        started = finished = None
        cost = None
        if attempt:
            ad = task_dir / "attempts" / attempt
            a = read_json(ad / "attempt.json") or {}
            r = read_json(ad / "result.json") or {}
            started, finished = a.get("started_at"), r.get("finished_at")
            cost = (r.get("native_cost") or {}).get("cost")
        out.append({"id": task_dir.name, "status": st.get("status"), "acceptance": st.get("acceptance"),
                    "revision": st.get("revision"),
                    "product_review": (st.get("product_review") or {}).get("verdict"),
                    "human": (st.get("human_accept") or {}).get("decision"),
                    "attempt": attempt, "started": started, "finished": finished, "cost": cost})
    return out


def db_stats(db):
    p = pathlib.Path(db)
    if not p.is_file():
        return {"present": False}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        total = con.execute("SELECT COUNT(*) c FROM records").fetchone()["c"]
        feeds = {r["name"]: r["n"] for r in con.execute(
            "SELECT f.name, COUNT(*) n FROM records r JOIN feeds f ON f.id=r.feed_id GROUP BY f.name")}
        con.close()
        return {"present": True, "records": total, "feeds": feeds, "bytes": p.stat().st_size,
                "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))}
    except Exception as exc:  # noqa: BLE001
        return {"present": True, "error": str(exc)[:120]}


def build_state(cfg):
    stores = []
    for s in cfg.get("stores", []):
        tasks = store_tasks(s["path"]) if pathlib.Path(s["path"]).is_dir() else []
        stores.append({**s, "tasks": tasks, "running_console": port_open(s.get("console_port") or 0)})
    reports = []
    rd = pathlib.Path(cfg.get("reports_dir") or "")
    if rd.is_dir():
        for f in sorted(rd.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:14]:
            reports.append({"name": f.name, "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))})
    return {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "port": cfg.get("port"),
            "stores": stores, "db": db_stats(cfg.get("db") or ""), "reports": reports}


def launch_console(entry):
    port = entry.get("console_port")
    if not port or port_open(port):
        return port
    cmd = [PY, "-B", str(WEBUI), "--limit", "3", "--store", entry["path"], "--port", str(port)]
    if entry.get("reports_dir"):
        cmd += ["--reports", entry["reports_dir"]]
    subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if port_open(port):
            return port
        time.sleep(0.25)
    return port


def render(state):
    e = html.escape
    db = state["db"]
    rows = []
    for s in state["stores"]:
        badge = ("运行中 :%s" % s["console_port"]) if s["running_console"] else ("未启动（可一键启动）")
        link = (f'<a class="btn" href="http://127.0.0.1:{s["console_port"]}/" target="_blank">打开控制台</a>'
                if s["running_console"] else
                f'<a class="btn" href="/launch/{e(s["key"])}">启动控制台</a>')
        trs = "".join(
            f"<tr><td class='mono'>{e(t['id'])}</td><td>{e(str(t['status']))}</td>"
            f"<td>{e(str(t['acceptance']))}</td><td>{e(str(t['product_review']))}</td>"
            f"<td>{e(str(t['human']))}</td><td class='mono'>{e(str(t['started'] or '')[:19])}</td>"
            f"<td class='mono'>{e(str(t['finished'] or '')[:19])}</td></tr>"
            for t in s["tasks"]) or "<tr><td colspan='7' class='dim'>（该 store 暂无任务）</td></tr>"
        rows.append(f"""<section><h2>{e(s['label'])} <span class="pill">{badge}</span></h2>
<p class="mono dim">{e(s['path'])}</p>{link}
<table><thead><tr><th>任务</th><th>状态</th><th>接收</th><th>产品意见</th><th>人工</th><th>开始</th><th>结束</th></tr></thead>
<tbody>{trs}</tbody></table></section>""")
    dbline = (f"<b>{db.get('records')}</b> 条记录 / {len(db.get('feeds') or {})} 个来源 / "
              f"{db.get('bytes')} B（{db.get('mtime')}）" if db.get("present") else "产品库不存在")
    feedline = "、".join(f"{e(k)} {v}" for k, v in (db.get("feeds") or {}).items())
    reps = "".join(f"<li><span class='mono dim'>{e(r['mtime'])}</span> {e(r['name'])}</li>" for r in state["reports"])
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="20"><title>舆情总览</title>
<style>
body{{font:14px/1.55 "Segoe UI",system-ui,sans-serif;margin:0;padding:24px;background:#0f1115;color:#e6e6e6}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:22px 0 6px}}
.mono{{font-family:Consolas,monospace}} .dim{{color:#8b93a1}}
table{{border-collapse:collapse;width:100%;margin-top:8px;font-size:13px}}
th,td{{border-bottom:1px solid #242a35;padding:5px 8px;text-align:left}}
th{{color:#9aa4b2;font-weight:600}} tr:hover td{{background:#161b24}}
.pill{{font-size:11px;padding:2px 8px;border-radius:10px;background:#1f2633;color:#9fb3d1;margin-left:8px}}
.btn{{display:inline-block;margin:6px 8px 2px 0;padding:5px 12px;border-radius:6px;background:#1d4ed8;color:#fff;text-decoration:none;font-size:13px}}
.btn:hover{{background:#2563eb}} .card{{background:#141821;border:1px solid #242a35;border-radius:10px;padding:14px 16px;margin-top:14px}}
ul{{margin:6px 0;padding-left:18px}} a{{color:#7cb0ff}}
</style></head><body>
<h1>舆情系统总览</h1><p class="dim">更新于 {e(state['at'])} ｜ 每 20 秒自动刷新 ｜ 只读汇总（不修改任何账本）</p>
<div class="card"><b>产品库</b>：{dbline}<br><span class="dim">{feedline}</span></div>
{''.join(rows)}
<div class="card"><b>最近的报告</b><ul>{reps}</ul></div>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    cfg = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, render(build_state(Handler.cfg)))
        elif self.path == "/api/state":
            self._send(200, json.dumps(build_state(Handler.cfg), ensure_ascii=False, indent=1),
                       "application/json; charset=utf-8")
        elif self.path.startswith("/launch/"):
            key = self.path.split("/launch/", 1)[1].strip("/")
            entry = next((s for s in Handler.cfg.get("stores", []) if s["key"] == key), None)
            if not entry:
                self._send(404, "未知 store")
                return
            port = launch_console(entry)
            self.send_response(302)
            self.send_header("location", f"http://127.0.0.1:{port}/")
            self.end_headers()
        else:
            self._send(404, "not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    global CONFIG
    if args.config:
        CONFIG = pathlib.Path(args.config)
    cfg = load_config()
    port = args.port or cfg.get("port", 8770)
    Handler.cfg = cfg
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"dashboard": f"http://127.0.0.1:{port}/", "stores": [s["key"] for s in cfg.get("stores", [])],
                      "db": cfg.get("db")}, ensure_ascii=False))
    sys.stdout.flush()
    srv.serve_forever()


if __name__ == "__main__":
    main()
