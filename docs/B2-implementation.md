# B2 提示词去重复与缺标题任务辨识 · 实现说明

本文件只记录本次实际改动与真实运行结果。**这不是最终验收 PASS**：真实客户端/浏览器与用户真实路径验收仍未执行，整体状态为 `awaiting_review` + 机器验收 `BLOCKED`。

## 1. 实际复用的既有实现

- 复用已落地的 Cytoscape core（`web/vendor/cytoscape.min.js`）与内置布局：有边用 `breadthfirst`，无边用 `grid`；未加载任何布局扩展，未新增依赖、未联网、未走 CDN。
- 复用现有桥服务/轮询/CLI（`bridge.py`、`adapters.py`、`webui.py`）与 Python 标准库；未改 `run`／取消／认证／锁／原生适配器。
- `web/app.js` 的唯一定时器、选择联动、未知/空态判别等语义保持不动。
- 未复制 TrendRadar／BettaFish 或任何外部项目代码。

## 2. 本次修复

| 路径 | 改动 |
| --- | --- |
| `bridge.py` `prompt_for` | 完整 task JSON 只内联一次；删去 `goal`／`allowed_paths`／`completion_criteria`／`artifacts` 的逐字复述（改为在包装行注明"下列 JSON 是唯一契约来源"）。工作区改用 `attempt["worktree"]`（真实 attempt 工作区），基线用 `attempt["base_commit"]`；`directory` 参数是桥任务 store 目录，刻意不写进提示词。`timeout` 只来自契约字段，包装不重复。 |
| `bridge.py` `validate` + `parse_anchor` | 新增可选 `anchors` 校验：`相对路径:行[,行|起-止]`；拒绝格式错误、非正整数行、反向区间（起 > 止）、行号超出文件总行数，以及未列入 `input_refs` 的锚点文件（锚点文件须列入 `input_refs` 以随输入固定 hash）。旧契约无 `anchors` 继续兼容；`allowed_paths`/`artifacts` 子集校验保留。 |
| `schemas/task.schema.json` | 同步 `anchors` 的语义与格式（可选字符串数组，路径+正整数行/正序区间，须列 `input_refs`，越界/反向/非正整数拒绝，旧契约兼容）。 |
| `web/task-graph.js` | **缺 title 标签**：长 `task_id` 改用尾部并加省略标识（`…` + 末 27 字符），避免公共前缀把不同任务显示成同一标签；`title` 仍优先且图内限长（`LABEL_MAX=28`）。文本列表按钮新增 `title` 属性给出**完整 task_id**（点击详情原本已显示完整 id）。无任何解析边时，图注明确写"暂无依赖记录（依赖边仅来自 task.dependencies）"，不暗示边已存在或已实机覆盖。`grid`/`breadthfirst`/隐藏修复/搜索/状态语义保持不变。 |
| `tests/prompt_checks.py`（新增） | 三组定向离线检查，支持 `--limit 1–3`（执行前截断）。 |
| `docs/B2-implementation.md`（本文件，新增） | 实现与检查记录。 |
| `README.md` | 只补一节契约语义短说明。 |

未修改：`adapters.py`、`web/app.js`、`web/index.html`、`web/style.css`、`webui.py`、执行/接收逻辑、真实 store、`.git`、认证与全局配置。

## 3. 三组定向检查（真实执行记录）

授权范围：首次 `--limit 3` 一次、`node --check`、内存 `compile` 纯语法检查。均在本机离线执行；`model_requests: 0`，未启动持久服务、未联网、未跑全量、未自动重跑。

语法检查（在内存中 `compile`，不落盘；`node --check` 不执行脚本）：

```
PY_COMPILE_OK        # bridge.py, tests/prompt_checks.py
NODE_CHECK_OK        # web/task-graph.js
SCHEMA_JSON_OK
```

`tests/prompt_checks.py --limit 3`（退出码 0；输出原样）：

```json
{"check": "prompt_single_json_workspace_basecommit", "status": "PASS", "detail": {"contract_json_once": true, "contract_json_content_matches": true, "goal_not_repeated_outside_json": true, "workspace_from_attempt_worktree": true, "store_dir_not_used_as_workspace": true, "base_commit_inline": true, "legacy_contract_validates": true, "legacy_json_has_no_title": true, "legacy_prompt_single_json": true}}
{"check": "anchors_and_artifacts_boundaries", "status": "PASS", "detail": {"legal_anchor_accepted": true, "out_of_bounds_rejected": true, "reversed_range_rejected": true, "nonpositive_line_rejected": true, "bad_format_rejected": true, "unanchored_file_not_in_input_refs_rejected": true, "artifact_outside_allowed_paths_rejected": true, "artifact_inside_allowed_paths_accepted": true, "legacy_no_anchors_accepted": true}}
{"check": "titleless_id_tail_and_full_list_node", "status": "PASS", "detail": {"tails_match_real_node_labels": true, "tails_pairwise_distinct": true, "title_still_prioritized": true, "full_task_id_in_list": true, "tail_label_in_list": true, "node_labels": {"opencode-go-fullchain-docs-r3": "…encode-go-fullchain-docs-r3", "opencode-readme-update-20261015": "…code-readme-update-20261015", "ui-real-opencode-20261015-1238": "…real-opencode-20261015-1238", "titled-fixture": "B0 状态映射审查"}}}
{"limit": 3, "executed_checks": ["prompt_single_json_workspace_basecommit", "anchors_and_artifacts_boundaries", "titleless_id_tail_and_full_list_node"], "retained_directory": "…\\data\\prompt-check-1979b1e02c93", "model_requests": 0, "acceptance": "BLOCKED"}
```

检查覆盖边界：

- 组 1 为**结构化断言**：完整契约 JSON 在 prompt 中恰好出现一次且内容与 `validate` 后任务一致；除 JSON 行外的包装行等于固定模板（据此断言 `goal` 等字段不在 JSON 外重复，避免对任意短 goal 做 count 或长度上限误判）；工作区来自 `attempt.worktree` 且 store 目录未被当成工作区；旧契约（无 `title`/`anchors`/`opencode_mode`）可校验且 prompt 仍单次内联。
- 组 2 为 `bridge.validate` 的真实正/反例：合法锚点与产物被接受；越界、反向区间、非正整数、格式错误、锚点文件未列 `input_refs`、产物越出 `allowed_paths` 均被拒绝。
- 组 3 **用本机已有 Node 实际执行** `web/task-graph.js`：`vm` 载入组件、以最小伪 DOM/伪 Cytoscape 调 `mount`+`update`，真实运行 `taskLabel`/`renderList`/`renderNote`，读取真实节点标签与列表 HTML。核对三条历史缺 title 任务（`opencode-go-fullchain-docs-r3`、`opencode-readme-update-20261015`、`ui-real-opencode-20261015-1238`，来源 `docs/ui-restored.txt`）的尾部标签互不相同、各等于 `…`+末 27 字符、完整 task_id 在列表可得，且带 title 的任务仍显示 title。不是纯字符串出现断言。

保留现场（未清理）：`data/prompt-check-1979b1e02c93`（`data/` 已 gitignore）。

## 4. 未执行的验证与缺失项（如实列出）

- 未在真实浏览器/真实客户端核对新标签的视觉效果、列表 `title` 提示的可发现性，以及图注"暂无依赖记录"的实际呈现。
- 组 3 用伪 Cytoscape/伪 DOM 执行组件逻辑，验证的是标签与列表文本生成，**不是**真实 Cytoscape 渲染或真实浏览器 AX 树。
- 未运行 `tests/graph_checks.py`、`tests/manual_checks.py`（未获授权），未验证本次改动对既有图谱定向检查的联动影响。
- 三条历史缺 title ID 取自本工作区 `docs/ui-restored.txt` 的真实界面记录；未读取真实 store 复核其当前 title 字段。
- 未做真实锚点文件的端到端执行；未修改/删除任何桥 store、状态文件或人工验收证据；未提交、未推送、未切分支。

## 5. 结论

代码与三组定向离线检查在本机授权范围内真实通过（退出码 0，语法检查通过）。**运行成功 ≠ 最终验收 PASS**：真实浏览器/客户端与用户真实路径验收仍未执行，整体结论保持 `BLOCKED`，执行者不代填人工 accept。
