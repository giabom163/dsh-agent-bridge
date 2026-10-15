"""Loopback-only browser console for the local Agent Bridge."""
import argparse
import base64
import json
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 部署目录里 bridge 只存在于 agent-bridge.pyz 内；Python 可直接从 zip 导入。
ARCHIVE = ROOT / "agent-bridge.pyz"
if ARCHIVE.is_file() and str(ARCHIVE) not in sys.path:
    sys.path.insert(0, str(ARCHIVE))

import bridge

WEB_ROOT = ROOT / "web"
MAX_BODY = 1024 * 1024


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address, store, config):
        super().__init__(address, BridgeHandler)
        self.store = Path(store).resolve()
        self.config = config
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        # 固定启动时加载的字节，磁盘之后变化不会冒充已热加载。
        loaded = {module.__name__: bridge.digest(module.__loader__.get_data(module.__file__))
                  for module in (bridge, bridge.adapters)}
        loaded.update({name: bridge.digest((ROOT / name).read_bytes())
                       for name in ("webui.py", "web/app.js", "web/index.html", "web/style.css")})
        self.runtime = {"pid": __import__("os").getpid(), "started_at": bridge.now(), "store": str(self.store),
                        "loaded_sha256": loaded, "bridge_module": bridge.__file__,
                        "build": "shared-session-20261015"}


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "AgentBridgeUI/1.0"

    def log_message(self, fmt, *args):
        # Avoid writing task content, query strings, or local paths into access logs.
        return

    def _send(self, status, value, content_type="application/json; charset=utf-8"):
        if isinstance(value, bytes):
            body = value
        else:
            body = bridge.scrub(json.dumps(value, ensure_ascii=False)).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status, message):
        self._send(status, {"error": bridge.scrub(str(message))})

    def _body(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Content-Length 非法")
        if size < 1 or size > MAX_BODY:
            raise ValueError("请求体为空或超过 1 MiB")
        try:
            value = json.loads(self.rfile.read(size))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("请求体必须是 UTF-8 JSON")
        if not isinstance(value, dict):
            raise ValueError("JSON 顶层必须为对象")
        return value

    def _safe_task_id(self, value):
        task_id = unquote(value)
        if not bridge.ID.fullmatch(task_id):
            raise ValueError("任务编号非法")
        return task_id

    def _task_data(self, task_id):
        directory = bridge.task_dir(self.server.store, task_id)
        task, state = bridge.load_task(directory)
        current = state.get("current_attempt")
        result = None
        native = attempt_info = observation = None
        activity = []
        if current:
            attempt = directory / "attempts" / current
            result_path = attempt / "result.json"
            attempt_info = bridge.read(attempt / "attempt.json")
            if (attempt / "native-session.json").is_file():
                native = bridge.read(attempt / "native-session.json")
            if (attempt / "native-observation.json").is_file():
                observation = bridge.read(attempt / "native-observation.json")
            if result_path.is_file():
                result = bridge.read(result_path)
            log = attempt / "stdout.log"
            if log.is_file():
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 65536))
                    lines = stream.read(65536).decode("utf-8", "replace").splitlines()
                for line in lines:
                    try:
                        item = json.loads(line)
                        part = item.get("part") or {}
                        if item.get("type") in ("text", "tool_use", "error", "step_finish"):
                            activity.append({"type": item.get("type"), "tool": part.get("tool"),
                                             "status": (part.get("state") or {}).get("status"),
                                             "text": str(part.get("text") or item.get("error") or "")[-4000:]})
                    except (ValueError, AttributeError, TypeError):
                        continue
        with self.server.jobs_lock:
            job = self.server.jobs.get(task_id)
        return {"task": task, "state": state, "result": result, "job": job,
                "native": native, "native_observation": observation, "attempt": attempt_info, "activity": activity[-12:]}

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            if path == "/api/runtime":
                return self._send(200, self.server.runtime)
            if path == "/":
                page = (WEB_ROOT / "index.html").read_bytes()
                return self._send(200, page, "text/html; charset=utf-8")
            if path == "/app.js":
                page = (WEB_ROOT / "app.js").read_bytes()
                return self._send(200, page, "text/javascript; charset=utf-8")
            if path == "/style.css":
                page = (WEB_ROOT / "style.css").read_bytes()
                return self._send(200, page, "text/css; charset=utf-8")
            if path == "/api/tasks":
                tasks_dir = self.server.store / "tasks"
                rows = []
                if tasks_dir.is_dir():
                    for entry in sorted(tasks_dir.iterdir(), key=lambda p: p.name):
                        if not bridge.ID.fullmatch(entry.name) or entry.is_symlink():
                            continue
                        try:
                            data = self._task_data(entry.name)
                            rows.append({"task_id": entry.name, "task": data["task"],
                                         "state": data["state"], "job": data["job"]})
                        except (OSError, ValueError, KeyError, TypeError):
                            continue
                return self._send(200, {"tasks": rows})
            match = re.fullmatch(r"/api/tasks/([^/]+)", path)
            if match:
                return self._send(200, self._task_data(self._safe_task_id(match.group(1))))
            return self._error(404, "接口不存在")
        except FileNotFoundError:
            return self._error(404, "任务或界面文件不存在")
        except (ValueError, OSError, KeyError, TypeError) as error:
            return self._error(400, error)

    def _check_origin(self):
        expected_host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host", "").lower() != expected_host.lower():
            raise PermissionError("仅允许通过本机 127.0.0.1 地址操作")
        origin = self.headers.get("Origin")
        if origin != f"http://{expected_host}":
            raise PermissionError("写入操作必须来自本地控制台页面")

    def _save_evidence(self, directory, label, item):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError(f"缺少 {label} 证据文件")
        name = Path(item["name"]).name
        if not name or len(name) > 120:
            raise ValueError(f"{label} 证据文件名非法")
        try:
            content = base64.b64decode(item.get("content_base64", ""), validate=True)
        except (ValueError, TypeError):
            raise ValueError(f"{label} 证据文件编码非法")
        if not content or len(content) > 256 * 1024:
            raise ValueError(f"{label} 证据文件为空或超过 256 KiB")
        target_dir = directory / "web-evidence"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{label}-{uuid.uuid4().hex[:12]}-{name}"
        with target.open("xb") as stream:
            stream.write(content)
        return target

    def do_POST(self):
        try:
            self._check_origin()
            body = self._body()
            path = urlsplit(self.path).path
            if path == "/api/tasks":
                task = bridge.validate(body.get("contract"))
                submissions = self.server.store / "web-submissions"
                submissions.mkdir(parents=True, exist_ok=True)
                source = submissions / f"{task['task_id']}-{uuid.uuid4().hex[:12]}.json"
                bridge.atomic(source, task)
                return self._send(201, bridge.submit(self.server.store, source))
            match = re.fullmatch(r"/api/tasks/([^/]+)/(plan|prepare|run|native-status|cancel|revise|review)", path)
            if not match:
                return self._error(404, "接口不存在")
            task_id, action = self._safe_task_id(match.group(1)), match.group(2)
            if action == "plan":
                return self._send(200, bridge.plan(self.server.store, task_id, self.server.config))
            if action == "native-status":
                return self._send(200, bridge.native_status(self.server.store, task_id, self.server.config))
            if action in ("prepare", "run"):
                plan_hash = body.get("plan_sha256")
                if not isinstance(plan_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
                    raise ValueError("需要有效的计划 SHA-256")
                if body.get("approve_start") is not True or body.get("ack_unmetered") is not True:
                    raise PermissionError("启动须在界面明确批准计划及未实证预算限制")
                task, _ = bridge.load_task(bridge.task_dir(self.server.store, task_id))
                visible = body.get("confirm_visible") is True
                if action == "run" and bridge.adapters.shared(task) and not visible:
                    raise PermissionError("先在真实 OpenCode 客户端找到空会话，再确认可见并发送提示词")
                with self.server.jobs_lock:
                    active = [key for key, value in self.server.jobs.items() if value.get("running")]
                    if active:
                        raise ValueError("已有前端任务运行中；请等待结束或核对状态")
                    self.server.jobs[task_id] = {"running": True, "started_at": bridge.now()}

                def execute():
                    try:
                        result = bridge.run(self.server.store, task_id, self.server.config,
                                            plan_hash, True, True, action == "prepare", visible)
                        job = {"running": False, "finished_at": bridge.now(), "result": result}
                    except Exception as error:
                        job = {"running": False, "finished_at": bridge.now(),
                               "error": bridge.scrub(str(error)), "acceptance": "BLOCKED"}
                    with self.server.jobs_lock:
                        self.server.jobs[task_id] = job

                threading.Thread(target=execute, name="agent-bridge-run", daemon=True).start()
                return self._send(202, {"task_id": task_id, "running": True,
                                        "note": "执行器已由前端批准启动；额度、原生重试与请求数无法由桥硬限制"})
            if action == "cancel":
                if body.get("approve_cancel") is not True:
                    raise PermissionError("结束任务进程树须在界面明确批准")
                return self._send(202, bridge.cancel(self.server.store, task_id,
                                                    body.get("attempt_id"), True))
            if action == "revise":
                task = bridge.validate(body.get("contract"))
                submissions = self.server.store / "web-submissions"
                submissions.mkdir(parents=True, exist_ok=True)
                source = submissions / f"{task_id}-rev{uuid.uuid4().hex[:12]}.json"
                bridge.atomic(source, task)
                return self._send(200, bridge.revise(self.server.store, task_id, source))
            if action == "review":
                directory = bridge.task_dir(self.server.store, task_id)
                decision = body.get("decision")
                if decision not in ("audit", "accept"):
                    raise ValueError("decision 只支持 audit / accept")
                audit = self._save_evidence(directory, "audit", body.get("audit_evidence"))
                user = None
                if decision == "accept":
                    user = self._save_evidence(directory, "user", body.get("user_evidence"))
                return self._send(200, bridge.review(self.server.store, task_id, decision, audit, user))
            return self._error(404, "接口不存在")
        except PermissionError as error:
            return self._error(403, error)
        except FileExistsError as error:
            return self._error(409, error)
        except (ValueError, OSError, KeyError, TypeError) as error:
            return self._error(400, error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--store", type=Path, default=ROOT / "data")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.limit <= 3:
        parser.error("--limit 必须为 1–3")
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1–65535")
    config = bridge.read(args.config) if args.config else {}
    server = BridgeHTTPServer((args.host, args.port), args.store, config)
    print(json.dumps({"url": f"http://{args.host}:{args.port}/", "store": str(server.store),
                      "model_requests": 0, "acceptance": "BLOCKED",
                      "security": "loopback only; mutating requests require same-origin browser"}, ensure_ascii=False),
          flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
