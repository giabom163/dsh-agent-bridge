#!/usr/bin/env python3
"""离线夹具（record / serve / check / list）：让"没有凭据、没有网络、平台挂了"时也能真验证。

为什么需要：本轮 S3-B 因为没有模型凭据只能写 BLOCKED；S1-B 因为 Chrome 被关被迫取消。
把一次真实响应录下来，之后任何任务都可以对着**本地夹具服务器**跑完整的真实调用路径。

用法：
  # 1) 录一条（会发 1 次真实请求；key 从 ~/.dsh/.credentials.yaml 读）
  python -B fixture.py record --name chat-basic --model deepseek-v4.1-flash --prompt "只输出 JSON"
  # 2) 起本地夹具服务（0 外网请求）
  python -B fixture.py serve --port 8799
  # 3) 校验 / 列出
  python -B fixture.py check --name chat-basic
  python -B fixture.py list

客户端怎么用：把模型端点指向 `http://127.0.0.1:8799/v1/chat/completions` 即可
（产品侧需要支持端点覆盖，例如读 `OPENCODE_GO_V1_ENDPOINT`；没这个开关时夹具帮不上真实调用路径）。
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent
FIX = ROOT / "fixtures"
ZEN = "https://opencode.ai/zen/go/v1/chat/completions"


def key():
    p = pathlib.Path.home() / ".dsh" / ".credentials.yaml"
    if not p.is_file():
        return None
    m = re.search(r"OPENCODE_GO_V1_API_KEY\s*:\s*[\"']?([^\s\"']+)",
                  p.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def body_of(name, model, prompt):
    return {"model": model, "reasoning_effort": "none", "temperature": 0, "max_tokens": 64,
            "messages": [{"role": "user", "content": prompt}]}


def sig(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def cmd_record(args):
    k = key()
    if not k:
        print(json.dumps({"error": "没有 OPENCODE_GO_V1_API_KEY，无法录制"}, ensure_ascii=False))
        return 2
    body = body_of(args.name, args.model, args.prompt)
    headers = {"content-type": "application/json", "authorization": "Bearer " + k,
               "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"),
               "accept": "application/json", "x-opencode-session": "fixture-record"}
    req = urllib.request.Request(args.endpoint, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, ensure_ascii=False))
        return 1
    FIX.mkdir(parents=True, exist_ok=True)
    data = {"name": args.name, "sig": sig(body), "recorded_at": datetime.now(timezone.utc).isoformat(),
            "request": {"model": body["model"], "messages": body["messages"]},
            "http_status": status, "response_raw": raw}
    (FIX / f"{args.name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"ok": True, "name": args.name, "sig": data["sig"], "http": status,
                      "bytes": len(raw)}, ensure_ascii=False))
    return 0


def cmd_list(args):
    FIX.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(FIX.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        items.append({"name": d.get("name"), "sig": d.get("sig"), "http": d.get("http_status"),
                      "recorded_at": d.get("recorded_at"), "bytes": len(d.get("response_raw") or "")})
    print(json.dumps({"fixtures": items, "dir": str(FIX)}, ensure_ascii=False, indent=1))
    return 0


def cmd_check(args):
    p = FIX / f"{args.name}.json"
    problems = []
    if not p.is_file():
        problems.append(f"夹具不存在：{p}")
    else:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            raw = d.get("response_raw") or ""
            json.loads(raw)                      # 必须是合法 JSON
            if not (d.get("request") or {}).get("model"):
                problems.append("请求里的 model 缺失")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"内容不合法：{exc}")
    print(json.dumps({"name": args.name, "ok": not problems, "problems": problems}, ensure_ascii=False, indent=1))
    return 0 if not problems else 1


class Handler(BaseHTTPRequestHandler):
    fixtures = {}
    allow_single_fallback = False

    def log_message(self, *a):  # 静音
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except Exception:  # noqa: BLE001
            body = {}
        want = sig(body) if body else None
        hit = Handler.fixtures.get(want)
        # 默认**不**兜底：请求对不上就必须 404，否则会掩盖"请求体写错"（本会话踩过同类坑）。
        if not hit and Handler.allow_single_fallback and len(Handler.fixtures) == 1:
            hit = next(iter(Handler.fixtures.values()))
        if not hit:
            self.send_response(404)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "没有匹配的夹具", "sig": want}},
                                        ensure_ascii=False).encode())
            return
        data = hit["data"]
        payload = data["response_raw"].encode()
        self.send_response(data.get("http_status", 200))
        self.send_header("content-type", "application/json")
        self.send_header("x-fixture", data["name"])
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        log = FIX / "replays.jsonl"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "fixture": data["name"],
                                 "sig": want, "bytes": len(payload)}, ensure_ascii=False) + "\n")


def cmd_serve(args):
    FIX.mkdir(parents=True, exist_ok=True)
    for p in sorted(FIX.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        Handler.fixtures[d.get("sig")] = {"data": d}
    if not Handler.fixtures:
        print(json.dumps({"error": "fixtures/ 里没有录制，先跑 record"}, ensure_ascii=False))
        return 1
    Handler.allow_single_fallback = args.allow_single_fallback
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"serving": f"http://127.0.0.1:{args.port}/v1/chat/completions",
                      "fixtures": len(Handler.fixtures), "external_requests": 0}, ensure_ascii=False))
    sys.stdout.flush()
    srv.serve_forever()
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--name", required=True)
    r.add_argument("--model", default="deepseek-v4.1-flash")
    r.add_argument("--prompt", default='只输出一个 JSON：{"ok":true}')
    r.add_argument("--endpoint", default=ZEN)
    l = sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("--name", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8799)
    s.add_argument("--allow-single-fallback", action="store_true",
                   help="只剩一条夹具时，对不上的请求也用它兜底（默认关闭，便于发现请求体写错）")
    args = ap.parse_args()
    return {"record": cmd_record, "list": cmd_list, "check": cmd_check, "serve": cmd_serve}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
