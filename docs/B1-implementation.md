# B1 桥只读任务协同图 · 实现说明

本文件只记录本次实际改动与真实运行结果。**这不是最终验收 PASS**：未做真实浏览器/实机核对，主线程实机验收仍未执行。当前状态语义上相当于 `awaiting_review` + 机器验收 `BLOCKED`。

## 1. 实际修改的文件

| 路径 | 改动 |
| --- | --- |
| `web/task-graph.js`（新增） | 只读协同图组件：真实任务节点、仅按 `task.dependencies` 连边、内置 `breadthfirst` 布局、点击节点打开真实详情、空图/缺失依赖/未知状态可见、可访问文本列表；自身不发网络请求。 |
| `web/vendor/cytoscape.min.js`（新增） | 固定版本 Cytoscape core（3.34.3，MIT）。 |
| `web/vendor/cytoscape-LICENSE`（新增） | 随 core 保存的上游 MIT 许可证原文。 |
| `web/vendor/NOTICE.md`（新增） | 记录来源、版本、URL、校验值与许可证信息。 |
| `web/index.html` | 按 CSP 以本地脚本加载 `vendor/cytoscape.min.js`、`task-graph.js`、`app.js`；新增图容器、文本列表、连接/断线显示 id。 |
| `web/app.js` | 复用唯一 5 秒刷新器并接入图更新；搜索与图同步过滤；节点/表/图选中联动；断线保留数据并显示旧时间、停止图动画；10 状态与 3 验收值映射共用、未知原值保留、null 模型显示“未记录”。 |
| `web/style.css` | 仅新增图、状态、断连与窄屏样式。 |
| `webui.py` | 为新增静态资源增加**逐项显式白名单**路由；把实际加载的 `web/task-graph.js`、`web/vendor/cytoscape.min.js` 纳入 `loaded_sha256`；更新 build 标识为 `shared-session-graph-20261015`。CSP 与 API 未改。 |
| `tests/graph_checks.py`（新增） | 三组定向离线检查，支持 `--limit 1–3`。 |
| `docs/B1-implementation.md`（本文件，新增） | 实现与检查记录。 |

未修改：`bridge.py`、`adapters.py`、`schemas/task.schema.json`、认证、原 store、执行/接收逻辑。`git status` 的改动集仅为上表内路径。

`git diff --stat`（已跟踪文件）：
```
 web/app.js     | 68 ++++++++++++++++++++++++++++++++++++++++++++++++++++------
 web/index.html | 16 +++++++++++++-
 web/style.css  |  2 ++
 webui.py       | 18 ++++++++++++++--
 4 files changed, 94 insertions(+), 10 deletions(-)
```

## 2. 状态与验收（中文完整文字，独立显示）

图节点、表格、详情共用同一映射（`web/task-graph.js` 导出，`web/app.js` 复用）。10 个任务状态按契约完整文字：

`ready 待规划` / `prepared 空会话待确认` / `running 执行中` / `awaiting_review 待审查` / `awaiting_user 待用户验收` / `accepted 已接收` / `rework 返修待规划` / `failed 失败` / `cancelled 已取消` / `stop_unconfirmed 停止未确认`。

- 未知状态保留原值，显示为 `未知（原值）`，不折叠成已知状态。
- `cancel_requested` 保留为独立过程标签 `取消中（过程标签）`，不挤占 10 状态。
- 3 个验收值 `PASS 通过` / `FAIL 失败` / `BLOCKED 阻塞` **独立于任务状态**显示（详情“验收（独立）”）；缺失/未知显示 `未知（未记录）` / `未知（原值）`，不默认 PASS。
- 模型为 null/缺省时显示“未记录”，非空值照实显示。

## 3. 图与刷新、断线

- 边**只**来自 `task.dependencies`；被引用但不在 `GET /api/tasks` 返回列表中的依赖，在图注显示“缺失依赖”，且不伪造其节点或状态。
- 布局为 Cytoscape 内置 `breadthfirst`，不加载任何布局扩展，不使用 CDN。
- 复用 `web/app.js` 中原有唯一的 `setInterval(()=>refresh(),5000)`；图组件内无任何定时器（`task-graph.js` 不含 `setInterval`）。
- 刷新失败时：状态置为断连，顶部连接标签与图区显示“已断连 · 最后成功刷新 <旧时间>”，图容器加 `graph-stale` 并以 `cy.stop()` 停止动画；保留已有数据，但不把旧数据当新鲜。
- 不触发 `native-status`，不发送模型请求。

## 4. 固定依赖下载（两次，间隔 ≥20 秒）

- 第 1 次：`GET https://registry.npmjs.org/cytoscape`（HTTP 200，2026-10-15T12:52:06Z–12:52:07Z UTC），`dist-tags.latest = 3.34.3`。
- 第 2 次：`GET https://registry.npmjs.org/cytoscape/-/cytoscape-3.34.3.tgz`（HTTP 200，2026-10-15T12:52:31Z–12:52:32Z UTC），与第 1 次间隔 24.4 秒。
- 仅此两次外部请求，无其他外部探测，未走 CDN。

本地实算校验值（与 `web/vendor/NOTICE.md` 一致，已回读核对）：

| 文件 | 字节 | SHA-256 |
| --- | --- | --- |
| `web/vendor/cytoscape.min.js` | 435503 | `5f3b5b529546d5af1fc5628590af033b74511a5b6f789f5f4682845863228b91` |
| `web/vendor/cytoscape-LICENSE` | 1082 | `eb319c6e6f233607f71e8e2f450391751883cfc0eeb3ca7ef574c13d1d9c2203` |
| 上游 tarball `cytoscape-3.34.3.tgz` | 1378263 | `5d9e479216ed58a5f1ac639e746fd7d9770c4393f8c355dd133abc90bcc9ff3f` |

限制：受“两次下载”约束，未在 metadata 响应中留存并回读 npm 发布的 `dist.integrity` 做逐字节比对。

## 5. 静态路由与 CSP

`webui.py` `do_GET` 中新增的路由均为逐项显式白名单，绝不按请求路径拼接文件：

`/task-graph.js`（text/javascript）、`/vendor/cytoscape.min.js`（text/javascript）、`/vendor/cytoscape-LICENSE`（text/plain）、`/vendor/NOTICE.md`（text/markdown）。

CSP 未削弱，仍为：`default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:`。`/api/*` 与写入逻辑未改。

`/api/runtime` 的 `loaded_sha256` 现包含 `web/ui` 四个原文件 + `web/task-graph.js` + `web/vendor/cytoscape.min.js`（实际加载字节 SHA-256），build 标识为 `shared-session-graph-20261015`。

## 6. 定向检查（真实执行记录）

命令与结果（真实执行；首次 `--limit 3` 后，因修正图节点状态样式类做了一次复核运行，共两次，未跑全量、未自动重试）：

```
& <python> -B tests\graph_checks.py --limit 3
EXIT_CODE=0        # 两次均 0
```

三组输出（原样）：

```json
{"check": "status_acceptance_unknown_null", "status": "PASS", "detail": {"status_labels_10": true, "unknown_kept": true, "null_model_kept": true, "raw_values_preserved": true, "explicit_model_kept": true}}
{"check": "dependency_selection_disconnect", "status": "PASS", "detail": {"dependency_edge_beta": true, "missing_dependency_seen": true, "edges_from_dependencies_only": true, "single_5s_poller": true, "graph_has_no_poller": true, "disconnect_stops_animation": true, "node_click_wired": true}}
{"check": "static_routes_and_ui_compat", "status": "PASS", "detail": {"runtime_ok": true, "loaded_hashes_match": true, "build_updated": true, "whitelist_routes": true, "csp_self_only": true, "original_ui_present": true, "no_cdn_reference": true, "traversal_rejected": true, "traversal_codes": [404, 404, 404]}}
```

保留夹具（未清理）：`data\graph-check-1ff376c1e18e`（首次）、`data\graph-check-d5e78cd7908a`（复核），两次均 `model_requests: 0`、`acceptance: BLOCKED`。检查在进程内起停服务，未持久启动、未发模型请求、未触发 `native-status`。

检查覆盖边界说明：

- 组 1 为**接口原值保真**（真实 GET 夹具）＋**前端映射文字静态断言**，未执行浏览器 JS。
- 组 2 为**接口依赖值**＋ `web/app.js`/`web/task-graph.js` 的静态断言（唯一轮询、缺失依赖、断线处理、点击联动）；断线视觉为静态确认，非浏览器实测。
- 组 3 为真实 HTTP 路由/哈希/CSP/穿越探测（原始请求行，避免客户端归一化），原界面元素存在性为页面静态断言。

## 7. 未执行的验证与缺失项（如实列出）

- 未在真实浏览器/主线程环境实机核对：图渲染、节点点击打开详情、搜索与图同步的视觉效果、窄屏布局、断线时图动画停止的可视表现、Cytoscape 加载失败时的报错与表格可用性。
- 未提供不含 Cytoscape 的降级演示；组件缺失时报错路径仅做了代码与静态断言，未在浏览器实测。
- 未提供真实、获准的任务数据来核对 10 状态/3 验收值；检查使用自建夹具，不等同实机验收证据。
- 组 1/组 2 含静态断言成分，不等同端到端行为验证。
- 未做 npm 发布 `dist.integrity` 逐字节比对（受下载次数约束）。
- 未修改/未删除任何桥 store、状态文件或人工验收证据；未提交、未推送。

## 8. 结论

代码与三组定向检查在本机离线范围内真实通过（退出码 0）。**运行成功 ≠ 最终验收 PASS**；主线程实机验收（尤其真实数据的状态/验收映射、断线可视表现、CSP 无控制台报错）尚未执行，最终验收结论仍为 `BLOCKED`。
