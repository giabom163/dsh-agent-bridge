"""须用户手动或明确授权运行的离线辅助检查；不调用 DSH、OpenCode 或模型。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bridge


def expect_rejected(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("本应拒绝的操作被允许")


def fixture(home, name):
    case = home / ("r" if name == "roundtrip" else "t")
    repo = case / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "report.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "report.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Bridge Fixture",
                    "-c", "user.email=bridge-fixture@example.invalid", "commit", "-m", "fixture"],
                   check=True, capture_output=True)
    worker = case / "worker.py"
    worker.write_text("from pathlib import Path\nimport sys\nsys.stdin.read()\n"
                      "Path('report.txt').write_text('after\\n', encoding='utf-8')\n"
                      "print('{\"type\":\"final\",\"text\":\"fixture complete\"}')\n", encoding="utf-8")
    task = {"task_id": name, "repo": str(repo.resolve()), "executor": "dsh", "goal": "离线检查",
            "allowed_paths": ["report.txt"], "artifacts": ["report.txt"], "input_refs": ["report.txt"],
            "completion_criteria": ["文件改为 after"], "timeout_seconds": 30}
    contract = case / "task.json"
    bridge.atomic(contract, task)
    store = case / "store"
    original_build = bridge.adapters.build
    bridge.adapters.build = lambda task, prompt, config: ([sys.executable, str(worker)], prompt.encode("utf-8"))
    try:
        bridge.submit(store, contract)
        plan = bridge.plan(store, name, {})
        state = bridge.run(store, name, {}, plan["plan_sha256"], True, True)
    finally:
        bridge.adapters.build = original_build
    return repo, store, state


def paths(home):
    base = home.resolve()
    for value in ("../escape.txt", "C:/outside.txt", ".git/config", "nested/../../escape", "CON", "."):
        expect_rejected(lambda value=value: bridge.inside(base, value))


def roundtrip(home):
    repo, store, state = fixture(home, "roundtrip")
    assert state["status"] == "awaiting_review", state
    assert state["acceptance"] == "BLOCKED", state
    result = bridge.read(state["result_file"])
    assert result["exit_code"] == 0, result
    assert [x["path"] for x in result["changes"]] == ["report.txt"], result
    assert (repo / "report.txt").read_text(encoding="utf-8") == "before\n"
    worktree = Path(state["result_file"]).parent / "workspace"
    assert (worktree / "report.txt").read_text(encoding="utf-8") == "after\n"


def tamper(home):
    repo, store, state = fixture(home, "tamper")
    assert state["status"] == "awaiting_review", state
    path = Path(state["result_file"])
    result = bridge.read(path)
    result["attempt_id"] = "attempt-forged"
    bridge.atomic(path, result)
    evidence = home / "fixture-audit.txt"
    evidence.write_text("仅离线夹具证据，不是产品验收。\n", encoding="utf-8")
    expect_rejected(lambda: bridge.review(store, "tamper", "audit", evidence, None))
    current = bridge.load_task(bridge.task_dir(store, "tamper"))[1]
    assert current["status"] == "awaiting_review"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--only", nargs="+", choices=("path_rejection", "file_roundtrip", "tampered_result_rejection"))
    args = parser.parse_args()
    if not 1 <= args.limit <= 3:
        parser.error("--limit 必须为 1–3，首次使用 --limit 3")
    # 保留现场，但缩短 Windows Git worktree 的夹具路径。
    home = ROOT / "data" / ("mc-" + uuid.uuid4().hex[:12])
    home.mkdir(parents=True)
    records = []
    checks = [("path_rejection", paths), ("file_roundtrip", roundtrip), ("tampered_result_rejection", tamper)]
    if args.only:
        checks = [(name, check) for name, check in checks if name in args.only]
    for name, check in checks[:args.limit]:
        try:
            check(home)
            record = {"check": name, "status": "PASS"}
        except Exception as error:
            record = {"check": name, "status": "FAIL", "exception": type(error).__name__,
                      "message": bridge.scrub(str(error))}
        records.append(record)
        print(json.dumps(record, ensure_ascii=False))
    bridge.atomic(home / "checks.json", {"checks": records, "retained_directory": str(home),
                  "model_requests": 0, "product_acceptance": "BLOCKED"})
    print(json.dumps({"retained_directory": str(home), "product_acceptance": "BLOCKED"}, ensure_ascii=False))
    return 1 if any(x["status"] == "FAIL" for x in records) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
