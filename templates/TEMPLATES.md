# 桥任务模板与自检骨架（契约模板库 · v1）

> 目的：把**首次通过率**从本轮实测的 ~42% 提上去。做法只有两条——
> ① 契约模板化（别再每次手写、别再漏掉硬性要求）；
> ② **交付前自检**（把已知失败模式在交付前拦掉，而不是等独立审查来抓）。

## 1 选模板（按任务类型）

| 类型 | 模板 | 典型超时 | 自检命令 | 真实调用/凭据归谁 |
|---|---|---|---|---|
| 给采集器加平台端点 | `contract-add-endpoint.json` | **900 s** | `--kind endpoint` | 平台请求：agent 可少量真跑（间隔 ≥30 s）；**不做写动作** |
| 改 HTTP 模型适配器 | `contract-modify-adapter.json` | **600 s** | `--kind adapter` | **凭据归主线程**（agent 无 key，别让它猜） |
| 新增离线标注器 | `contract-add-annotator.json` | **900 s** | `--kind annotator` | 同上：真实模型调用由主线程补 |
| 只改文档/规则 | `contract-docs-only.json` | **300 s** | `--kind docs` | 不需要 |

**超时按类型设**，不要一律 900：本轮三次 900 s 超时里，两次是"范围小但被强行塞了大证据跑"。

## 2 用法

1. 复制模板 → 替换 `{{...}}` 占位符（`SELFCHECK` 填 `templates/selfcheck.py` 的**绝对路径**）；
2. `submit` → `plan`（基线与输入哈希）→ `run`；
3. agent 在 worktree 内**先跑自检**，`verdict=pass` 才允许交付，并把完整 JSON 贴进交付说明；
4. 我再做只读审查（或派独立模型），然后 `review --decision audit --verdict …` → `accept`/`reject`；
5. 通过后并入仓库。

## 3 自检脚本 `selfcheck.py`（离线、0 网络、只读）

```bash
python -B <templates>/selfcheck.py --kind endpoint \
  --worktree . --allow tools/,docs/ \
  --artifacts tools/collect_opencli.py,docs/S1-collector.md
```

通用检查（所有 kind）：① 改动路径 ⊆ `--allow`；② `--artifacts` 全部存在；③ 无密钥/令牌字面量；④ Python 文件 AST 可解析。
类型检查：
- `endpoint`：未知端点被拒、疑似写动作被拒、`--limit 0` 报错、**dry-run 不建库**（三例全部走 argparse 白名单，0 上游请求）；
- `adapter`：裸模型 id（无 provider 前缀）、`reasoning_effort`、三必备头、错误保留、引用对齐、无密钥；
- `annotator`：只读打开（`mode=ro`/immutable）、无 records 写操作、有枚举降级、有 dry-run、无密钥；
- `docs`：只改 `docs/`。

**它不能替代真实运行验收**——只替代"我逐项读代码"那一步。

## 4 上下文纪律（省钱的真正杠杆）

按本轮实测：我每步上下文约 **646K token**（cache-read 641K），单步 0.0264 元（官方空闲价）→ **步数和上下文就是钱**。

| 纪律 | 具体做法 |
|---|---|
| 读得少 | 大文件只读片段（`offset/limit`）、先 `grep` 定位再读；不整篇读日志/报告 |
| 探索外派 | "读一堆文件得结论"的活 → 子代理（它只回摘要）；本轮已用 4 次 |
| 结论落文件 | 长分析写 `output/`，回复只给结论 + 链接；不复述上一轮内容 |
| 阶段即压缩 | 每完成一个阶段就压缩一次，别等自动阈值 |
| 证据精简 | 审查只给 `diff + 契约要点`，不给全文 |
| 一次多步 | 能一个命令做完的别拆成多轮（每轮都要重付上下文） |

## 5 已知坑（模板里已内置提醒）

1. **契约写错责任边界**：让 agent 做需要凭据的证据 → 它必然 BLOCKED（S3-B 实例）→ 模板里已写"凭据归主线程"。
2. **超时一刀切**：改一函数的活给 600 s 足够；"新增端点 + 三份证据"要 900 s。
3. **行尾/BOM**：`.gitattributes eol=lf` 的仓库里，用 Python 写文件会把 `\n` 变成 `\r\n`，导致桥的输入哈希与 worktree 不一致 → 一律用 `write_bytes` 并显式 LF；JSON 契约文件不得带 BOM。
4. **独立审查要用另一个模型**，并要求它**自己重跑**而不是读我的结论；审查指令里写死"最多 N 次上游请求、间隔 ≥30 s"。
5. **打回必须带理由**，且写账；我自己的输出过滤器曾把打回的错误吞掉——**改账本状态的命令一律看完整输出**。
