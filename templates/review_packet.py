#!/usr/bin/env python3
"""审查包（review packet）：把审查需要的一切压成一个文件，**只传路径**给审查方。

为什么：R0 的真实失败是——审查第 2 轮 `WinError 206`（命令行过长），第 1 轮 182s 超时且
模型自己在 worktree 里重建 diff、写了工作区外的 patch、用了 PowerShell 不认的 `&&`。
根因是"把源码/diff 塞进命令行/提示词"，而不是让审查方读一个受控的输入文件。

它做什么：
  1) 从桥账本读 contract/state/result，生成一个自包含的 `review-packet.md`：
     - 契约摘要（title / goal 截断 / completion_criteria / timeout / allowed_paths / artifacts）
     - 真实改动清单 + 每个文件的 sha256（来自 result.json 与磁盘复算）
     - **diff 正文**（`git diff` 输出，超过 `--max-diff-kb` 就只给 stat + 摘要）
     - 执行事实、既有审计/自检指针
     - **审查须知**：只读、PowerShell 用 `;` 不用 `&&`、临时文件只允许写 `--tmp-dir`、预算与 checkpoint 要求
  2) 输出包大小与 sha256；超过 `--max-packet-kb` 直接报错（拒绝把超大包塞给审查方）。

用法：
  python -B review_packet.py --store <store> --task <task_id> [--attempt <att>] \
      [--max-diff-kb 60] [--max-packet-kb 120] [--out <path>]
"""
import argparse
import hashlib
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
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as exc:  # noqa: BLE001
        return 127, "", f"{type(exc).__name__}: {exc}"


def load(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def latest_contract(task_dir):
    best = None
    for p in sorted(task_dir.glob("contract.r*.json")):
        best = p
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--attempt", default=None)
    ap.add_argument("--max-diff-kb", type=int, default=60)
    ap.add_argument("--max-packet-kb", type=int, default=120)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    store = pathlib.Path(args.store)
    task_dir = store / "tasks" / args.task
    if not task_dir.is_dir():
        print(json.dumps({"error": f"任务不存在：{task_dir}"}, ensure_ascii=False))
        return 2
    state = load(task_dir / "state.json") or {}
    attempt = args.attempt or state.get("current_attempt")
    att_dir = task_dir / "attempts" / attempt if attempt else None
    if not att_dir or not att_dir.is_dir():
        print(json.dumps({"error": f"attempt 不存在：{att_dir}"}, ensure_ascii=False))
        return 2
    contract = load(latest_contract(task_dir)) or {}
    result = load(att_dir / "result.json") or {}
    workspace = att_dir / "workspace"

    changes = result.get("changes") or []
    rows = []
    for ch in changes:
        rel = ch.get("path")
        if not rel:
            continue
        f = workspace / rel
        disk = sha256(f) if f.is_file() else "（worktree 中不存在）"
        rows.append(f"| `{rel}` | {ch.get('before_sha256') or '（新建）'} | {disk} |")

    code, diff, err = run(["git", "status", "--porcelain"], cwd=str(workspace))
    code2, diff_text, err2 = run(["git", "diff"], cwd=str(workspace))
    if not diff_text.strip():
        code3, nostaged, _ = run(["git", "diff", "--no-index", "--", "/dev/null", "/dev/null"])
        diff_text = "（git diff 为空：改动可能是未跟踪文件；以下为 `git status`）\n" + (diff or "")
    diff_kb = len(diff_text.encode("utf-8")) / 1024
    if diff_kb > args.max_diff_kb:
        diff_block = (f"（diff 共 {diff_kb:.1f} KB，超过 {args.max_diff_kb} KB 上限 → 只给统计；"
                      f"完整 diff 请自行在只读 worktree 上跑 `git -C <workspace> diff`）\n\n"
                      f"```\n{run(['git', 'diff', '--stat'], cwd=str(workspace))[1]}\n```")
    else:
        diff_block = f"```diff\n{diff_text}\n```"

    goal = (contract.get("goal") or "")
    goal_short = goal if len(goal) <= 3000 else goal[:3000] + "\n…（goal 过长已截断，完整内容见契约文件）"
    packet = f"""# 审查包（auto-generated，勿手改）

- 任务：`{args.task}`
- attempt：`{attempt}`
- store：`{store}`
- 契约：`{latest_contract(task_dir).name if latest_contract(task_dir) else '?'}`
- 生成时间：{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1 契约摘要

- 标题：{contract.get('title')}
- 超时：{contract.get('timeout_seconds')} 秒；允许路径：{contract.get('allowed_paths')}
- 产物：{contract.get('artifacts')}
- 完成判据：
""" + "\n".join(f"  - {c}" for c in (contract.get("completion_criteria") or [])) + f"""

### goal（截断版）

```
{goal_short}
```

## 2 真实改动与哈希

| 文件 | result 记录的 after_sha256 | worktree 磁盘复算 |
|---|---|---|
""" + ("\n".join(rows) if rows else "| （result.changes 为空） | | |") + f"""

## 3 diff

{diff_block}

## 4 执行事实

```json
{json.dumps({k: result.get(k) for k in ('exit_code', 'stop_reason', 'timed_out', 'violations',
                                        'missing_artifacts', 'native_error_count')}, ensure_ascii=False, indent=1)}
```

## 5 审查须知（必须遵守，违反的结论不接受）

1. **只读**：不要修改 worktree、不要 `git add/commit`、不要写仓库内任何文件。
2. **命令方言**：本机默认 shell 是 **PowerShell**，`&&` 不可用；请用 `;` 或分开执行。
3. **临时文件**：只允许写到 `{{TMP}}` 下你自己建的目录（`$env:TEMP\\review-<随机>`）；**禁止**写工作区外其他位置。
4. **不要重建 diff**：diff 已在上文；如果要复算，只用 `git -C <workspace> diff` 只读命令。
5. **部分结论要落盘**：每完成 3 条核对就追加写入 `review-partial.md`（放你的临时目录），超时也能保留半成品。
6. **预算**：本审查目标 ≤ {min(600, int(contract.get('timeout_seconds') or 600))} 秒；超过 2/3 预算时优先输出已有结论。
7. **结论格式**：`pass` / `fail` + 逐条核对（含行号）+ 未能验证项 + 独立性声明。

## 6 已知审计/自检指针

- 自检：见 attempt 目录 `stdout.log` 中的 selfcheck JSON（若有）
- 既有审计：同目录 `audit-*.md`（若有）
"""
    out = pathlib.Path(args.out) if args.out else (att_dir / "review-packet.md")
    data = packet.encode("utf-8")
    kb = len(data) / 1024
    if kb > args.max_packet_kb:
        # 二次压缩：把 diff 换成 stat
        stat = run(["git", "diff", "--stat"], cwd=str(workspace))[1]
        packet = packet.replace(diff_block, f"（包过大已降级为 stat）\n```\n{stat}\n```")
        data = packet.encode("utf-8")
        kb = len(data) / 1024
    out.write_bytes(data)
    print(json.dumps({"packet": str(out), "kb": round(kb, 1), "sha256": hashlib.sha256(data).hexdigest(),
                      "goal_chars": len(goal), "diff_kb": round(diff_kb, 1),
                      "over_limit": kb > args.max_packet_kb}, ensure_ascii=False, indent=1))
    return 0 if kb <= args.max_packet_kb else 1


if __name__ == "__main__":
    sys.exit(main())
