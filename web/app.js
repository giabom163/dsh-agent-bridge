const $ = (id) => document.getElementById(id);
const state = { tasks: [], selected: null, plans: new Map(), action: null, editTask: null, connected: true, hasLoadedTasks: false, lastSuccessAt: null, graph: null };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
function prettyTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString("zh-CN", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false});
}
const FALLBACK_STATUS = {ready:"待规划",prepared:"空会话待确认",running:"执行中",awaiting_review:"待审查",awaiting_user:"待用户验收",accepted:"已接收",rework:"返修待规划",failed:"失败",cancelled:"已取消",stop_unconfirmed:"停止未确认",cancel_requested:"取消中"};
function labelStatus(value) {
  if (window.BridgeTaskGraph) return window.BridgeTaskGraph.statusLabel(value);
  if (value === null || value === undefined || value === "") return "未知";
  return FALLBACK_STATUS[value] || `未知（${value}）`;
}
function labelAcceptance(value) {
  if (window.BridgeTaskGraph) return window.BridgeTaskGraph.acceptanceLabel(value);
  if (value === null || value === undefined || value === "") return "未知（未记录）";
  return ({PASS:"通过",FAIL:"失败",BLOCKED:"阻塞"})[value] || `未知（${value}）`;
}
function labelModel(value) {
  if (window.BridgeTaskGraph) return window.BridgeTaskGraph.modelLabel(value);
  return value === null || value === undefined || value === "" ? "未记录" : String(value);
}
function toast(message, error = false) {
  const item = $("toast"); item.textContent = message; item.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => item.className = "toast", 3400);
}
async function api(path, options = {}) {
  const response = await fetch(path, {cache:"no-store", ...options, headers:{"Content-Type":"application/json", ...(options.headers || {})}});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
async function refresh(keep = true) {
  try {
    const data = await api("/api/tasks"); state.tasks = data.tasks || [];
    state.connected = true; state.hasLoadedTasks = true; state.lastSuccessAt = new Date().toISOString();
    $("taskCount").textContent = state.tasks.length;
    renderMetrics(); renderRows();
    if (state.selected && keep && state.tasks.some(x => x.task_id === state.selected)) await selectTask(state.selected);
    else if (!state.selected) $("detailPanel").innerHTML = placeholder();
    renderGraph();
  } catch (error) {
    // 保留已有数据，但区分“从未成功加载”与“已有数据后断线”：不把未知当成空。
    state.connected = false;
    $("taskCount").textContent = state.hasLoadedTasks ? state.tasks.length : "—";
    renderMetrics(); renderRows();
    renderGraph();
    toast(error.message, true);
  }
}
function renderGraph() {
  updateConnection();
  if (!state.graph) return;
  state.graph.update(state.tasks, state.hasLoadedTasks);
  state.graph.setFilter($("searchInput").value);
  if (state.selected) state.graph.select(state.selected);
  state.graph.setConnection(state.connected, state.lastSuccessAt);
}
function updateConnection() {
  const el = $("connectionState"); if (!el) return;
  const time = state.lastSuccessAt ? new Date(state.lastSuccessAt).toLocaleTimeString("zh-CN", {hour12:false}) : "尚未成功";
  el.classList.toggle("dropped", !state.connected);
  el.innerHTML = `<i></i> ${state.connected ? "本地连接" : `已断连 · 最后成功 ${esc(time)}`}`;
  el.title = `最后成功刷新 ${time}`;
}
function initGraph() {
  const errorEl = $("graphError");
  if (!window.BridgeTaskGraph) {
    errorEl.hidden = false;
    errorEl.textContent = "协同图组件 /task-graph.js 未加载；任务表与详情仍可使用，不做假图降级。";
    return null;
  }
  try {
    const graph = window.BridgeTaskGraph.mount({graphId:"taskGraph", listId:"graphList", statusId:"graphStatus",
      noteId:"graphNote", emptyId:"graphEmpty", errorId:"graphError", onSelect:(id) => selectTask(id)});
    if (!graph.available && graph.error) toast(graph.error, true);
    return graph.available ? graph : null;
  } catch (error) {
    errorEl.hidden = false;
    errorEl.textContent = `协同图初始化失败：${error.message}`;
    return null;
  }
}
function renderMetrics() {
  if (!state.hasLoadedTasks) {
    // 从未成功读取任务：计数未知，显示“—”而不是 0，避免把未知当成空。
    const unknown = [["任务总数","—","尚未成功读取","◫"],["正在执行","—","尚未成功读取","↗"],["等待审查","—","尚未成功读取","◇"],["验收阻塞","—","尚未成功读取","! "]];
    $("metrics").innerHTML = unknown.map(([title,value,sub,icon]) => `<article class="metric"><div class="metric-top"><span>${title}</span><span class="metric-icon">${icon}</span></div><div class="metric-value">${value}</div><div class="metric-sub">${sub}</div></article>`).join("");
    return;
  }
  const counts = {all:state.tasks.length,active:0,review:0,blocked:0};
  for (const row of state.tasks) {
    if (["running","cancel_requested"].includes(row.state.status)) counts.active++;
    if (["awaiting_review","awaiting_user"].includes(row.state.status)) counts.review++;
    if (row.state.acceptance === "BLOCKED") counts.blocked++;
  }
  const metrics = [["任务总数",counts.all,"本地任务记录","◫"],["正在执行",counts.active,"桥持有的执行任务","↗"],["等待审查",counts.review,"需要人工查看","◇"],["验收阻塞",counts.blocked,"证据不足或待操作","! "]];
  $("metrics").innerHTML = metrics.map(([title,value,sub,icon]) => `<article class="metric"><div class="metric-top"><span>${title}</span><span class="metric-icon">${icon}</span></div><div class="metric-value">${value}</div><div class="metric-sub">${sub}</div></article>`).join("");
}
function renderRows() {
  const query = $("searchInput").value.trim().toLowerCase();
  const rows = state.tasks.filter(x => `${x.task_id} ${x.task.goal}`.toLowerCase().includes(query));
  // 表格空态与图、文本列表遵循同一判别：从未成功加载 ≠ 成功加载且确为空。
  const unknown = !state.hasLoadedTasks;
  $("emptyState").classList.toggle("visible", state.tasks.length === 0);
  $("emptyTitle").textContent = unknown ? "无法读取任务" : "还没有任务";
  $("emptyHint").textContent = unknown ? "尚未成功加载任务列表；无法确认任务是否为空。请等待重试或检查本机连接。" : "创建任务契约后，可在这里规划、执行和审查。";
  $("emptyNewButton").hidden = unknown;
  $("taskRows").innerHTML = rows.map(row => `<tr class="task-row ${state.selected === row.task_id ? "selected" : ""}" data-id="${esc(row.task_id)}"><td><div class="task-title">${esc(row.task.title || row.task.goal)}</div><div class="task-id">${esc(row.task_id)} · r${esc(row.state.revision)}</div></td><td><span class="executor">${esc(row.task.executor)}</span></td><td><span class="badge ${esc(row.state.status)}">${esc(labelStatus(row.state.status))}</span></td><td class="update-time">${esc(prettyTime(row.state.finished_at || row.state.started_at || row.state.created_at))}</td><td class="row-open">›</td></tr>`).join("");
  document.querySelectorAll(".task-row").forEach(el => el.addEventListener("click", () => selectTask(el.dataset.id)));
}
function placeholder() { return `<div class="detail-placeholder"><div class="placeholder-art"><i></i><i></i><i></i></div><strong>选择一个任务</strong><span>计划、执行结果和审查记录会显示在这里。</span></div>`; }
function actionButtons(data) {
  const s = data.state.status, id = data.task.task_id;
  const planButton = ["ready","rework","prepared"].includes(s) ? `<button class="primary-button small-button" data-action="plan">生成计划</button>` : "";
  const shared = data.task.opencode_mode === "shared";
  const prepareButton = shared && ["ready","rework"].includes(s) && state.plans.has(id) ? `<button class="primary-button small-button" data-action="prepare">创建可见空会话</button>` : "";
  const runButton = ["ready","rework","prepared"].includes(s) && (!shared || s === "prepared") && state.plans.has(id) ? `<button class="primary-button small-button" data-action="run">发送提示词执行</button>` : "";
  const cancelButton = s === "running" && data.state.current_attempt ? `<button class="danger-button small-button" data-action="cancel">请求取消</button>` : "";
  const auditButton = s === "awaiting_review" ? `<button class="primary-button small-button" data-action="audit">提交只读审查</button>` : "";
  const acceptButton = s === "awaiting_user" ? `<button class="primary-button small-button" data-action="accept">附证据并接收</button>` : "";
  const reviseButton = !["running","prepared","stop_unconfirmed","accepted"].includes(s) ? `<button class="secondary-button small-button" data-action="revise">修订契约</button>` : "";
  const nativeButton = data.native ? `<button class="secondary-button small-button" data-action="native-status">回读原生状态</button>` : "";
  return planButton + prepareButton + runButton + nativeButton + cancelButton + auditButton + acceptButton + reviseButton;
}
async function selectTask(id) {
  state.selected = id; renderRows();
  if (state.graph) state.graph.select(id);
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(id)}`); renderDetail(data);
  } catch (error) { toast(error.message, true); }
}
function renderDetail(data) {
  const task = data.task, s = data.state, plan = state.plans.get(task.task_id);
  const result = data.result;
  const n = data.native;
  const nativeSection = n ? `<div class="detail-section"><h3>OpenCode 原生会话</h3><div class="detail-text">标题：${esc(n.title)}
会话 ID：${esc(n.session_id)}
服务：${esc(n.server)}
工作区：${esc(n.directory)}
模型：${esc(n.model)}
可见性：${esc(n.visibility)}
提示词：${n.prompt_sent ? "已交给 CLI，原生接纳以事件为准" : "尚未发送"}
最近事件：${esc(n.last_event || "空会话")} ${esc(prettyTime(n.last_event_at))}
原生停稳：${n.stop_confirmed === true ? "已确认" : n.stop_confirmed === false ? "未确认" : "尚未回收"}</div><p class="detail-subtle">在连接同一服务的 OpenCode 中打开上述工作区，按标题或会话 ID 查找。桥不更改 Console 工作区连接；客户端若连接另一服务，需要先配对。</p></div>` : "";
  const warnings = result?.native_warnings || n?.warnings || [];
  const warningSection = warnings.length ? `<div class="detail-section"><h3>原生工具警告</h3><div class="detail-text">${esc(warnings.map(x=>`${x.tool || x.stage}: ${x.message}`).join("\n"))}</div></div>` : "";
  const activity = data.activity?.length ? `<div class="detail-section"><h3>最近执行输出</h3><div class="detail-text">${esc(data.activity.map(x=>[x.type,x.tool,x.status,x.text].filter(Boolean).join(" · ")).join("\n\n"))}</div></div>` : "";
  const effects = plan ? `<div class="detail-section"><h3>执行计划 · ${esc(plan.plan_sha256.slice(0,12))}…</h3><div class="detail-text">${esc(plan.effects.join("\n"))}</div><div class="detail-subtle" style="margin-top:6px">${esc(plan.limitations.join("\n"))}</div></div>` : "";
  // 执行事实（A 轴）与可审准入（B 轴）分开显示：二者都不再依赖 result 是否存在，
  // 否则只读审查结论与"执行失败"都会无处显示（分账契约 §5.4）。
  const facts = (result && result.execution_facts) || s.execution_facts || null;
  const gate = (result && result.review_gate) || s.review_gate || null;
  const factsLine = facts ? [
    `退出码：${esc(String(facts.exit_code))}`,
    `停止原因：${esc(facts.stop_reason || "无")}`,
    `原生停稳：${facts.stop_confirmed === true ? "已确认" : facts.stop_confirmed === false ? "未确认" : "未记录"}`,
    `原生错误：${esc(String(facts.native_error_count))}`,
    `超时：${facts.timed_out ? "是" : "否"}`,
  ].join("\n") : "";
  const resultSection = (result || facts) ? `<div class="detail-section"><h3>执行事实 · ${esc(labelStatus(s.status))}</h3><div class="detail-text">${factsLine ? factsLine + "\n" : ""}变更文件：${esc(((result && result.changes) || []).map(x=>x.path).join(", ") || "无")}${result && result.native_errors && result.native_errors.length ? `\n原生错误明细：${esc(result.native_errors.map(x=>x.message || JSON.stringify(x)).join("; "))}` : ""}</div></div>` : "";
  const gateSection = gate ? `<div class="detail-section"><h3>可审准入 · ${gate.reviewable ? "可审查" : "不可审查"}</h3><div class="detail-text">reviewable：${gate.reviewable ? "true" : "false"}\n原因：${esc(gate.reason || "无")}</div><p class="detail-subtle">${gate.reviewable ? "可进入只读审查；这不等于已通过，更不等于可接收。" : "该产物今天没有只读审查入口；按规则不得重派或接收。"}</p></div>` : "";
  const softReview = s.product_review, softAccept = s.human_accept;
  const reviewSection = (softReview || softAccept) ? `<div class="detail-section"><h3>产品意见 / 人工接收</h3><div class="detail-text">产品意见：${esc(softReview ? (softReview.verdict || "未记录") : "未记录")}${softReview ? `\n审查证据 SHA：${esc(String(softReview.evidence_sha256 || "").slice(0, 24))}` : ""}\n人工接收：${esc(softAccept ? (softAccept.decision || "未记录") : "未记录")}${softAccept ? `\n接收时间：${esc(prettyTime(softAccept.at))}` : ""}</div></div>` : "";
  // 快捷操作与命令：把「打开目录」「常用 CLI」并进控制台，省掉额外的快捷方式/命令行窗口。
  const paths = data.paths || {};
  const openButtons = [["worktree", "打开工作区"], ["attempt", "打开尝试目录"], ["task", "打开任务目录"],
                       ["evidence", "打开证据目录"], ["store", "打开 store"], ["reports", "打开报告目录"]]
    .filter(([scope]) => paths[scope])
    .map(([scope, label]) => `<button class="secondary-button small-button" data-open="${scope}">${label}</button>`).join("");
  const commandRows = (data.commands || []).map(item => `<div class="cmd-row"><span class="cmd-label">${esc(item.label)}</span><code>${esc(item.command)}</code><button class="secondary-button small-button" data-copy="1">复制</button></div>`).join("");
  const toolsSection = `<div class="detail-section"><h3>快捷操作与命令</h3>${openButtons ? `<div class="detail-actions">${openButtons}</div>` : ""}${commandRows ? `<div class="cmd-list">${commandRows}</div>` : ""}<p class="detail-subtle">「打开目录」由控制台在本机执行（只允许 store 内目录，或启动时用 --reports 配置的目录）；命令可直接复制到 PowerShell 执行。</p></div>`;
  const observation = data.native_observation ? `<div class="detail-section"><h3>最近原生回读</h3><div class="detail-text">${esc(prettyTime(data.native_observation.time))}\n原生 outcome：${esc(data.native_observation.session?.outcome || "尚无结果")}\n原生 idle 时间：${esc(data.native_observation.session?.time?.idle || "尚无记录")}\n${esc(data.native_observation.note)}</div></div>` : "";
  const job = data.job?.running ? `<div class="detail-section"><h3>桥任务</h3><div class="detail-text">执行器正在运行。刷新可读取最新状态。</div></div>` : data.job?.error ? `<div class="detail-section"><h3>操作失败 · BLOCKED</h3><div class="detail-text">${esc(data.job.error)}</div></div>` : "";
  $("detailPanel").innerHTML = `<div class="detail-head"><div><h2>${esc(task.title || task.goal)}</h2><p>${esc(task.task_id)} · revision ${esc(s.revision)}</p></div><button class="icon-button detail-close" id="detailClose" title="关闭">×</button></div>
    <div class="detail-meta"><div class="meta-box"><span>状态</span><b><span class="badge ${esc(s.status)}">${esc(labelStatus(s.status))}</span></b></div><div class="meta-box"><span>执行器 · 模型</span><b>${esc(task.executor)} · ${esc(labelModel(task.model))}</b></div><div class="meta-box"><span>验收（独立）</span><b>${esc(labelAcceptance(s.acceptance))}</b></div><div class="meta-box"><span>产品意见</span><b>${esc(s.product_review?.verdict || "未记录")}</b></div><div class="meta-box"><span>人工接收</span><b>${esc(s.human_accept?.decision || "未记录")}</b></div><div class="meta-box"><span>最后更新</span><b>${esc(prettyTime(s.finished_at || s.started_at || s.created_at))}</b></div></div>
    <div class="detail-section"><h3>任务目标</h3><div class="detail-text">${esc(task.goal)}</div></div>
    <div class="detail-section"><h3>允许修改</h3><div class="detail-text">${esc((task.allowed_paths || []).join("\n"))}</div></div>
    <div class="detail-actions">${actionButtons(data)}</div><div class="detail-subtle">详情为 state.current_attempt 的当前尝试，不是完整历史。启动会新增 worktree 并运行新执行器，可能调用模型；桥未实证原生请求数量和预算限制。</div>${nativeSection}${observation}${effects}${job}${warningSection}${activity}${facts || result ? gateSection : ""}${reviewSection}${toolsSection}${resultSection}`;
  $("detailClose").addEventListener("click", () => {state.selected=null; renderRows(); $("detailPanel").innerHTML=placeholder();});
  document.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => handleAction(button.dataset.action, data)));
  document.querySelectorAll("[data-open]").forEach(button => button.addEventListener("click", () => openFolder(data.task.task_id, button.dataset.open)));
  document.querySelectorAll("[data-copy]").forEach(button => button.addEventListener("click", async () => {
    const code = button.closest(".cmd-row")?.querySelector("code");
    try { await navigator.clipboard.writeText(code ? code.textContent : ""); toast("命令已复制到剪贴板。"); }
    catch (error) { toast("复制失败，请手动选中命令文本。", true); }
  }));
}
async function openFolder(taskId, scope) {
  try {
    const data = await api("/api/open", {method: "POST", body: JSON.stringify({task_id: taskId, scope})});
    toast(`已在本机文件管理器打开：${data.opened}`);
  } catch (error) { toast(error.message, true); }
}
async function handleAction(action, data) {
  if (action === "native-status") {
    try { await api(`/api/tasks/${data.task.task_id}/native-status`, {method:"POST",body:"{}"}); await selectTask(data.task.task_id); toast("原生状态已回读；没有发送模型提示词。"); }
    catch (error) { toast(error.message,true); }
    return;
  }
  if (action === "plan") {
    try { const plan = await api(`/api/tasks/${data.task.task_id}/plan`, {method:"POST",body:JSON.stringify({})}); state.plans.set(data.task.task_id, plan); await selectTask(data.task.task_id); toast("计划已生成；请先审阅影响范围。"); }
    catch (error) { toast(error.message,true); }
    return;
  }
  if (action === "revise") { openTaskDialog(data.task); return; }
  if (action === "run" || action === "prepare") openRunDialog(data, action);
  if (action === "cancel") openCancelDialog(data);
  if (action === "audit") openReviewDialog(data, "audit");
  if (action === "accept") openReviewDialog(data, "accept");
}
function openTaskDialog(task = null) {
  state.editTask = task;
  $("taskDialogTitle").textContent = task ? "修订任务契约" : "新建任务";
  $("saveTaskButton").textContent = task ? "保存修订" : "保存任务契约";
  $("taskDialogError").textContent = "";
  $("contractInput").value = task ? JSON.stringify(task,null,2) : JSON.stringify({task_id:"example-task",title:"新的桥任务",opencode_mode:"shared",goal:"描述你要完成的具体任务",repo:"C:/path/to/clean/git/repository",executor:"opencode",model:"opencode-go/deepseek-v4.1-flash",allowed_paths:["src/"],artifacts:["src/result.txt"],input_refs:[],completion_criteria:["说明可观察的完成条件"],timeout_seconds:300},null,2);
  $("taskDialog").showModal();
}
$("saveTaskButton").addEventListener("click", async () => {
  try {
    const contract = JSON.parse($("contractInput").value);
    const task = state.editTask;
    const path = task ? `/api/tasks/${encodeURIComponent(task.task_id)}/revise` : "/api/tasks";
    const data = await api(path,{method:"POST",body:JSON.stringify(task ? {contract} : {contract})});
    $("taskDialog").close(); state.plans.delete(data.task_id || task?.task_id); await refresh(false);
    const id = data.task_id || task?.task_id; if (id) await selectTask(id); toast(task ? "修订已保存；旧尝试保留。" : "任务契约已保存。 ");
  } catch(error) { $("taskDialogError").textContent = error.message; }
});
function openAction(title, eyebrow, html, confirmText, context) {
  state.action = context; $("actionTitle").textContent=title; $("actionEyebrow").textContent=eyebrow;
  $("actionContent").innerHTML=html; $("actionError").textContent=""; $("confirmActionButton").textContent=confirmText; $("confirmActionButton").disabled=true;
  $("actionDialog").showModal();
  $("actionContent").querySelectorAll("input").forEach(input=>input.addEventListener("input",updateActionReady));
  $("actionContent").querySelectorAll("input").forEach(input=>input.addEventListener("change",updateActionReady));
  updateActionReady();
}
function updateActionReady() {
  const c=state.action; if(!c)return; let ready=false;
  if(c.type==="run" || c.type==="prepare") ready=$("approveRun").checked && $("ackUnmetered").checked && (!c.visibleRequired || $("confirmVisible").checked);
  else if(c.type==="cancel") ready=$("approveCancel").checked && $("confirmPhrase").value.trim()===`CANCEL ${c.id}`;
  else if(c.type==="audit") ready=$("auditFile").files.length===1;
  else if(c.type==="accept") ready=$("auditFile").files.length===1 && $("userFile").files.length===1 && $("confirmAccept").checked;
  $("confirmActionButton").disabled=!ready;
}
function openRunDialog(data, action = "run") {
  const p=state.plans.get(data.task.task_id); if(!p){toast("请先生成并审阅计划。",true);return;}
  const effects=(p.effects||[]).map(x=>`<li>${esc(x)}</li>`).join("");
  const limits=(p.limitations||[]).map(x=>`<li>${esc(x)}</li>`).join("");
  const prepare = action === "prepare", visibleRequired = !prepare && data.task.opencode_mode === "shared";
  openAction(prepare ? "创建 OpenCode 空会话" : "发送提示词并执行","任务授权",`<div class="info-box"><strong>计划哈希</strong><br>${esc(p.plan_sha256)}<br><br><strong>将发生</strong><ul>${effects}</ul></div><div class="warning-box"><strong>预算限制尚未实证。</strong>执行器可能调用模型和消耗额度；桥无法保证原生请求次数、重试或费用上限。<ul>${limits}</ul></div><label><input type="checkbox" id="approveRun">我已审阅该计划，并批准启动这一个任务</label><label><input type="checkbox" id="ackUnmetered">我知悉请求预算尚未被硬限制</label>${visibleRequired ? `<label><input type="checkbox" id="confirmVisible">我已在真实 OpenCode 客户端找到此会话：${esc(data.native?.session_id)}</label>` : ""}${prepare ? "<p>此步骤创建工作区和空会话，不发送模型提示词。</p>" : ""}`,prepare ? "创建空会话" : "发送提示词",{type:action,id:data.task.task_id,plan:p,visibleRequired});
}
function openCancelDialog(data) {
  const id=data.task.task_id, attempt=data.state.current_attempt;
  openAction("中断此任务","取消批准",`<div class="warning-box">共享模式会向此会话发送原生 interrupt，并结束桥的观察进程；不会关闭 OpenCode 服务。私有模式结束该任务进程树。必须回读原生状态确认停稳；现场保留。</div><div class="info-box"><strong>任务：</strong>${esc(id)}<br><strong>当前 attempt：</strong>${esc(attempt)}</div><label><input type="checkbox" id="approveCancel">我批准中断此 attempt</label><label>输入 <strong>CANCEL ${esc(id)}</strong> 确认<input type="text" id="confirmPhrase" autocomplete="off"></label>`,"请求取消",{type:"cancel",id,attempt});
}
function openReviewDialog(data, decision) {
  const accept=decision==="accept";
  const html=`<div class="info-box">证据文件会复制到任务目录 <code>web-evidence</code> 并保留。${accept?"接收要求只读审查证据和用户真实路径证据同时提供。":"此步骤只记录只读审查；验收仍为 BLOCKED，之后需要真实用户路径证据。"}</div><label>只读审查证据<input type="file" id="auditFile" accept=".md,.txt,.json,.log,.png,.jpg,.jpeg"></label>${accept?`<label>用户真实路径证据<input type="file" id="userFile" accept=".md,.txt,.json,.log,.png,.jpg,.jpeg"></label><label><input type="checkbox" id="confirmAccept">我确认所选证据对应真实客户端路径及本任务</label>`:""}`;
  openAction(accept?"提交验收证据":"记录只读审查",accept?"人工接收":"只读审查",html,accept?"审查并接收":"提交审查",{type:decision,id:data.task.task_id});
}
async function evidenceFile(inputId) {
  const file=$(inputId).files[0]; if(!file)throw new Error("请选择证据文件");
  if(file.size>256*1024)throw new Error(`${file.name} 超过 256 KiB 限制`);
  const bytes=new Uint8Array(await file.arrayBuffer()); let binary=""; for(let i=0;i<bytes.length;i+=0x8000)binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
  return {name:file.name,content_base64:btoa(binary)};
}
$("confirmActionButton").addEventListener("click", async () => {
  const c=state.action; if(!c)return; $("confirmActionButton").disabled=true; $("actionError").textContent="正在提交…";
  try {
    let data;
    if(c.type==="run" || c.type==="prepare") data=await api(`/api/tasks/${c.id}/${c.type}`,{method:"POST",body:JSON.stringify({plan_sha256:c.plan.plan_sha256,approve_start:true,ack_unmetered:true,confirm_visible:c.visibleRequired === true})});
    else if(c.type==="cancel") data=await api(`/api/tasks/${c.id}/cancel`,{method:"POST",body:JSON.stringify({attempt_id:c.attempt,approve_cancel:true})});
    else {
      const body={decision:c.type,audit_evidence:await evidenceFile("auditFile")};
      if(c.type==="accept")body.user_evidence=await evidenceFile("userFile");
      data=await api(`/api/tasks/${c.id}/review`,{method:"POST",body:JSON.stringify(body)});
    }
    $("actionDialog").close(); toast(c.type==="prepare"?"正在创建空会话；不会发送提示词。":c.type==="run"?"提示词执行已提交；请查看原生会话。":c.type==="cancel"?"取消请求已记录；请核对停止状态。":"审查记录已提交。 ");
    if(c.type==="run")await new Promise(resolve=>setTimeout(resolve,350)); await refresh();
  } catch(error) { $("actionError").textContent=error.message; $("confirmActionButton").disabled=false; }
});
$("newTaskButton").addEventListener("click",()=>openTaskDialog());
$("emptyNewButton").addEventListener("click",()=>openTaskDialog());
$("refreshButton").addEventListener("click",()=>refresh());
$("searchInput").addEventListener("input",()=>{ renderRows(); if (state.graph) state.graph.setFilter($("searchInput").value); });
setInterval(()=>refresh(),5000);
state.graph = initGraph();
api("/api/runtime").then(r=>{ $("runtimeInfo").textContent=`${r.build} · PID ${r.pid} · bridge ${r.loaded_sha256.bridge.slice(0,12)}`; $("runtimeInfo").title=JSON.stringify(r,null,2); }).catch(e=>toast(e.message,true));
refresh(false);
