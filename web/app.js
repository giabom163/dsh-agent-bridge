const $ = (id) => document.getElementById(id);
const state = { tasks: [], selected: null, plans: new Map(), action: null, editTask: null };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
function prettyTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString("zh-CN", {month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false});
}
function labelStatus(value) {
  return ({ready:"待规划",rework:"待重新规划",running:"执行中",cancel_requested:"取消中",awaiting_review:"待审查",awaiting_user:"待用户验收",accepted:"已接收",failed:"失败",cancelled:"已取消"})[value] || value || "未知";
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
    $("taskCount").textContent = state.tasks.length;
    renderMetrics(); renderRows();
    if (state.selected && keep && state.tasks.some(x => x.task_id === state.selected)) await selectTask(state.selected);
    else if (!state.selected) $("detailPanel").innerHTML = placeholder();
  } catch (error) { toast(error.message, true); }
}
function renderMetrics() {
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
  $("emptyState").classList.toggle("visible", state.tasks.length === 0);
  $("taskRows").innerHTML = rows.map(row => `<tr class="task-row ${state.selected === row.task_id ? "selected" : ""}" data-id="${esc(row.task_id)}"><td><div class="task-title">${esc(row.task.goal)}</div><div class="task-id">${esc(row.task_id)} · r${esc(row.state.revision)}</div></td><td><span class="executor">${esc(row.task.executor)}</span></td><td><span class="badge ${esc(row.state.status)}">${esc(labelStatus(row.state.status))}</span></td><td class="update-time">${esc(prettyTime(row.state.finished_at || row.state.started_at || row.state.created_at))}</td><td class="row-open">›</td></tr>`).join("");
  document.querySelectorAll(".task-row").forEach(el => el.addEventListener("click", () => selectTask(el.dataset.id)));
}
function placeholder() { return `<div class="detail-placeholder"><div class="placeholder-art"><i></i><i></i><i></i></div><strong>选择一个任务</strong><span>计划、执行结果和审查记录会显示在这里。</span></div>`; }
function actionButtons(data) {
  const s = data.state.status, id = data.task.task_id;
  const planButton = ["ready","rework"].includes(s) ? `<button class="primary-button small-button" data-action="plan">生成计划</button>` : "";
  const runButton = ["ready","rework"].includes(s) && state.plans.has(id) ? `<button class="primary-button small-button" data-action="run">批准并执行</button>` : "";
  const cancelButton = s === "running" && data.state.current_attempt ? `<button class="danger-button small-button" data-action="cancel">请求取消</button>` : "";
  const auditButton = s === "awaiting_review" ? `<button class="primary-button small-button" data-action="audit">提交只读审查</button>` : "";
  const acceptButton = s === "awaiting_user" ? `<button class="primary-button small-button" data-action="accept">附证据并接收</button>` : "";
  const reviseButton = !["running","accepted"].includes(s) ? `<button class="secondary-button small-button" data-action="revise">修订契约</button>` : "";
  return planButton + runButton + cancelButton + auditButton + acceptButton + reviseButton;
}
async function selectTask(id) {
  state.selected = id; renderRows();
  try {
    const data = await api(`/api/tasks/${encodeURIComponent(id)}`); renderDetail(data);
  } catch (error) { toast(error.message, true); }
}
function renderDetail(data) {
  const task = data.task, s = data.state, plan = state.plans.get(task.task_id);
  const result = data.result;
  const effects = plan ? `<div class="detail-section"><h3>执行计划 · ${esc(plan.plan_sha256.slice(0,12))}…</h3><div class="detail-text">${esc(plan.effects.join("\n"))}</div><div class="detail-subtle" style="margin-top:6px">${esc(plan.limitations.join("\n"))}</div></div>` : "";
  const resultSection = result ? `<div class="detail-section"><h3>机器结果 · ${esc(result.acceptance || "BLOCKED")}</h3><div class="detail-text">退出码：${esc(result.exit_code)}\n状态：${esc(labelStatus(s.status))}\n变更文件：${esc((result.changes || []).map(x=>x.path).join(", ") || "无")}${result.native_errors?.length ? `\n错误：${esc(result.native_errors.map(x=>x.message).join("; "))}` : ""}</div></div>` : "";
  const job = data.job?.running ? `<div class="detail-section"><h3>桥任务</h3><div class="detail-text">执行器正在运行。刷新可读取最新状态。</div></div>` : "";
  $("detailPanel").innerHTML = `<div class="detail-head"><div><h2>${esc(task.goal)}</h2><p>${esc(task.task_id)} · revision ${esc(s.revision)}</p></div><button class="icon-button detail-close" id="detailClose" title="关闭">×</button></div>
    <div class="detail-meta"><div class="meta-box"><span>状态</span><b><span class="badge ${esc(s.status)}">${esc(labelStatus(s.status))}</span></b></div><div class="meta-box"><span>执行器</span><b>${esc(task.executor)}${task.model ? ` · ${esc(task.model)}` : ""}</b></div><div class="meta-box"><span>验收</span><b>${esc(s.acceptance || "BLOCKED")}</b></div><div class="meta-box"><span>最后更新</span><b>${esc(prettyTime(s.finished_at || s.started_at || s.created_at))}</b></div></div>
    <div class="detail-section"><h3>任务目标</h3><div class="detail-text">${esc(task.goal)}</div></div>
    <div class="detail-section"><h3>允许修改</h3><div class="detail-text">${esc((task.allowed_paths || []).join("\n"))}</div></div>
    <div class="detail-actions">${actionButtons(data)}</div><div class="detail-subtle">启动会新增 worktree 并运行新执行器，可能调用模型；桥未实证原生请求数量和预算限制。</div>${effects}${job}${resultSection}`;
  $("detailClose").addEventListener("click", () => {state.selected=null; renderRows(); $("detailPanel").innerHTML=placeholder();});
  document.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => handleAction(button.dataset.action, data)));
}
async function handleAction(action, data) {
  if (action === "plan") {
    try { const plan = await api(`/api/tasks/${data.task.task_id}/plan`, {method:"POST",body:JSON.stringify({})}); state.plans.set(data.task.task_id, plan); await selectTask(data.task.task_id); toast("计划已生成；请先审阅影响范围。"); }
    catch (error) { toast(error.message,true); }
    return;
  }
  if (action === "revise") { openTaskDialog(data.task); return; }
  if (action === "run") openRunDialog(data);
  if (action === "cancel") openCancelDialog(data);
  if (action === "audit") openReviewDialog(data, "audit");
  if (action === "accept") openReviewDialog(data, "accept");
}
function openTaskDialog(task = null) {
  state.editTask = task;
  $("taskDialogTitle").textContent = task ? "修订任务契约" : "新建任务";
  $("saveTaskButton").textContent = task ? "保存修订" : "保存任务契约";
  $("taskDialogError").textContent = "";
  $("contractInput").value = task ? JSON.stringify(task,null,2) : JSON.stringify({task_id:"example-task",goal:"描述你要完成的具体任务",repo:"C:/path/to/clean/git/repository",executor:"opencode",model:"provider/model",allowed_paths:["src/"],artifacts:["src/result.txt"],input_refs:[],completion_criteria:["说明可观察的完成条件"],timeout_seconds:300},null,2);
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
  if(c.type==="run") ready=$("approveRun").checked && $("ackUnmetered").checked && $("confirmPhrase").value.trim()===`RUN ${c.id}`;
  else if(c.type==="cancel") ready=$("approveCancel").checked && $("confirmPhrase").value.trim()===`CANCEL ${c.id}`;
  else if(c.type==="audit") ready=$("auditFile").files.length===1;
  else if(c.type==="accept") ready=$("auditFile").files.length===1 && $("userFile").files.length===1 && $("confirmAccept").checked;
  $("confirmActionButton").disabled=!ready;
}
function openRunDialog(data) {
  const p=state.plans.get(data.task.task_id); if(!p){toast("请先生成并审阅计划。",true);return;}
  const effects=(p.effects||[]).map(x=>`<li>${esc(x)}</li>`).join("");
  const limits=(p.limitations||[]).map(x=>`<li>${esc(x)}</li>`).join("");
  openAction("确认启动执行器","执行批准",`<div class="info-box"><strong>计划哈希</strong><br>${esc(p.plan_sha256)}<br><br><strong>将发生</strong><ul>${effects}</ul></div><div class="warning-box"><strong>预算限制尚未实证。</strong>执行器可能调用模型和消耗额度；桥无法保证原生请求次数、重试或费用上限。<ul>${limits}</ul></div><label><input type="checkbox" id="approveRun">我已审阅该计划，并批准启动这一个任务</label><label><input type="checkbox" id="ackUnmetered">我知悉请求预算尚未被硬限制</label><label>输入 <strong>RUN ${esc(data.task.task_id)}</strong> 确认<input type="text" id="confirmPhrase" autocomplete="off"></label>`,"批准并启动",{type:"run",id:data.task.task_id,plan:p});
}
function openCancelDialog(data) {
  const id=data.task.task_id, attempt=data.state.current_attempt;
  openAction("结束此任务进程树","取消批准",`<div class="warning-box">取消请求会结束桥登记的该任务进程树，现场和 worktree 会保留。请求写入后，仍需观察状态确认进程已停稳。</div><div class="info-box"><strong>任务：</strong>${esc(id)}<br><strong>当前 attempt：</strong>${esc(attempt)}</div><label><input type="checkbox" id="approveCancel">我批准结束此 attempt 的桥任务进程树</label><label>输入 <strong>CANCEL ${esc(id)}</strong> 确认<input type="text" id="confirmPhrase" autocomplete="off"></label>`,"请求取消",{type:"cancel",id,attempt});
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
    if(c.type==="run") data=await api(`/api/tasks/${c.id}/run`,{method:"POST",body:JSON.stringify({plan_sha256:c.plan.plan_sha256,approve_start:true,ack_unmetered:true})});
    else if(c.type==="cancel") data=await api(`/api/tasks/${c.id}/cancel`,{method:"POST",body:JSON.stringify({attempt_id:c.attempt,approve_cancel:true})});
    else {
      const body={decision:c.type,audit_evidence:await evidenceFile("auditFile")};
      if(c.type==="accept")body.user_evidence=await evidenceFile("userFile");
      data=await api(`/api/tasks/${c.id}/review`,{method:"POST",body:JSON.stringify(body)});
    }
    $("actionDialog").close(); toast(c.type==="run"?"批准已提交；桥正在启动执行器。":c.type==="cancel"?"取消请求已记录；请核对停止状态。":"审查记录已提交。 ");
    if(c.type==="run")await new Promise(resolve=>setTimeout(resolve,350)); await refresh();
  } catch(error) { $("actionError").textContent=error.message; $("confirmActionButton").disabled=false; }
});
$("newTaskButton").addEventListener("click",()=>openTaskDialog());
$("emptyNewButton").addEventListener("click",()=>openTaskDialog());
$("refreshButton").addEventListener("click",()=>refresh());
$("searchInput").addEventListener("input",renderRows);
setInterval(()=>refresh(),5000);
refresh(false);
