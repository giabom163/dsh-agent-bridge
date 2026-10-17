#!/usr/bin/env python3
"""桥 store 清理（prune）：删掉失败/取消/已被取代的 attempt 的 worktree，回收磁盘。

默认 **dry-run**（只报告），`--apply` 才真删。安全的做法：
  - 只动 `attempts/<att>/workspace`（git worktree），不动 result.json / 证据；
  - 只删「任务状态 ≠ accepted」或「不是当前 attempt」的；
  - 删除前先 `git worktree remove --force`（让仓库的 worktree 记录一起清掉）；
  - 被保留的一律列出来，说明原因。

用法：python -B prune_stores.py --store <store> [--store <store2> ...] [--apply]
"""
import argparse
import json
import pathlib
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def run(cmd, cwd=None, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 127, "", f"{type(exc).__name__}: {exc}"


def dir_size(path):
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", action="append", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    plan, keep = [], []
    for store in args.store:
        st = pathlib.Path(store)
        for state_path in sorted(st.glob(r"tasks\*\state.json")) if "\\" in str(st) else sorted(st.glob("tasks/*/state.json")):
            task_dir = state_path.parent
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            status = state.get("status")
            current = state.get("current_attempt")
            for att_dir in sorted(task_dir.glob(r"attempts\*")):
                ws = att_dir / "workspace"
                if not ws.is_dir():
                    continue
                reason = None
                if status in ("failed", "cancelled", "rework", "awaiting_review", "awaiting_user", "accepted"):
                    # accepted/awaiting 的**当前** attempt 保留（证据还在用）
                    if att_dir.name == current and status in ("accepted", "awaiting_review", "awaiting_user", "rework"):
                        reason = "当前 attempt，保留"
                if reason:
                    keep.append({"store": st.name, "task": task_dir.name, "attempt": att_dir.name,
                                 "reason": reason})
                    continue
                plan.append({"store": st.name, "task": task_dir.name, "attempt": att_dir.name,
                             "path": str(ws), "bytes": dir_size(ws), "task_status": status})

    total = sum(p["bytes"] for p in plan)
    result = {"dry_run": not args.apply, "would_remove": len(plan), "would_free_mb": round(total / 1048576, 2),
              "items": plan, "kept": keep}
    if args.apply:
        removed = 0
        for item in plan:
            parent_repo = None
            gitfile = pathlib.Path(item["path"]).parent / ".git"
            if gitfile.is_file():
                txt = gitfile.read_text(encoding="utf-8", errors="replace")
                for line in txt.splitlines():
                    if line.startswith("gitdir:"):
                        gd = line.split(":", 1)[1].strip()
                        parent_repo = pathlib.Path(gd).parents[1] if "worktrees" in gd else None
            if parent_repo:
                run(["git", "-C", str(parent_repo), "worktree", "remove", "--force", item["path"]])
            try:
                import shutil
                if pathlib.Path(item["path"]).exists():
                    shutil.rmtree(item["path"], ignore_errors=True)
                removed += 1
            except Exception:  # noqa: BLE001
                pass
        result["removed"] = removed
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
