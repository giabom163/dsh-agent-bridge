# Agent Bridge Demo

本地命令行工具＋随项目交付的 Skill。Codex 写任务，DSH／OpenCode 在独立 worktree 实现；桥记录状态和产物。Python 标准库，无需安装依赖。真实模型链路已各有一次成功记录（DSH 原生 `write` 生成产物；OpenCode Go 生成报告），但用户真实路径验收与独立只读审计仍为 **BLOCKED**；取消、原生请求数和费用上限未实证，没有自动执行测试。

## 本机入口与边界

- 默认采用本机已核对的托管 Node、全局 DSH CLI 和 OpenCode v2.0.20 CLI；可通过 `--config <json>` 覆盖 `node`、`dsh`、`opencode` 三个入口路径，配置由本运行器读取。
- DSH 使用 `--profile headless --json -`，stdin 传入任务；模型选择来自原生配置，尚未执行验收。
- OpenCode 新前端默认 `opencode_mode: "shared"`：先创建本机后台服务空会话，再用 `run --session <原生ID> --format json --model provider/model`（每次先核对后台服务地址，复用 CLI 自管认证） 发送提示词。固定使用现有 V2 Console 工作区连接，不改凭据。旧契约缺省仍为 `standalone`，明确选择时继续支持私有实例。
- Windows 用 Job 对象登记自己的进程树。登记是在创建进程之后，早期子进程竞态和取消停稳尚未实测；POSIX 分支也未实测。
- 单任务、墙钟超时、基线与输入哈希、过期结果拒收已实现；原生内部请求数量、重试和 20 秒节流未实证，不承诺硬额度限制。普通开发任务与最多两次探测的规则分开，不自动发探测。
- worktree 不是权限沙箱；事后路径检查会拒收可观察的越界改动，但不能证明进程没碰外部路径。Git 忽略文件不纳入快照。不得用于不可信执行者。
- Windows 长路径：worktree 绝对路径 ≥216 字符时 git 会报 `fatal: '$GIT_DIR' too big`（本机 git 2.55.0.windows.2 实测，退出码 128；`-c core.longpaths=true` 无效，`LongPathsEnabled=1` 也不解除）。桥在 ≥200 字符时自动把工作区改放到短根 `%LOCALAPPDATA%\agent-bridge\wt\<attempt-id>`，真实路径记在 `attempt.json` 的 `worktree`，原路径记在 `worktree_relocated_from`，并在 `events.jsonl` 写 `worktree_relocated`。
- 调用 git 前会剥离继承自父会话的 `GIT_DIR`／`GIT_WORK_TREE`／`GIT_INDEX_FILE`／`GIT_OBJECT_DIRECTORY`／`GIT_COMMON_DIR`／`GIT_ALTERNATE_OBJECT_DIRECTORIES`：这些变量会让 git 指向错误仓库，或直接触发同一个 too big 报错。执行器进程自身继承的环境未做清理，属已知限制。
- 构建后的模拟/假执行仅作辅助检查；若无法验证目标行为，必须执行最小范围真实执行器验收。启动前须明确真实配置读取路径、执行器/模型、仓库和文件范围、产物、请求/额度不确定性及进程影响，并取得该范围的用户批准。429 后至少冷却 5 分钟且不自动重试。

## 本地浏览器控制台

可在本仓库目录启动无第三方依赖的本地控制台：

```powershell
& $bridgePython -B .\webui.py --limit 3
```

服务只绑定 `127.0.0.1:8765`，默认读取本目录 `data/`。在浏览器打开启动输出中的地址，可查看任务、提交/修订契约、生成计划、批准单个执行、请求取消、记录只读审查，以及附上两类证据后提交人工接收。计划和状态查询不会启动执行器；运行、取消、接收都需要在页面逐项确认。证据文件会复制到任务目录并保留。

运行操作会创建 detached worktree 并启动 DSH 或 OpenCode；可能消耗模型额度。桥目前没有原生请求次数或费用硬限制。共享模式停止控制台可能中断观察，但不会停止 OpenCode 后台服务，也不能据此宣称任务已停。关闭页面不会停止后台任务；需在页面请求取消并核对原生停稳记录。若控制台意外退出，可重开同一 store，点击“回读原生状态”；不会重复发送提示词，也不会自动补造文件回收结果。

旧控制台已有真实浏览器记录；本次共享会话改版仍待真实客户端验收，不能沿用旧版记录当作通过。它不能替代独立审查与用户真实路径证据。不要把“接收”用于虚构或测试证据。

## 用户手动入口

在此项目目录打开 PowerShell：

```powershell
$bridgePython = 'C:\Users\Lenovo\.workbuddy\binaries\python\versions\3.13.12\python.exe'
& $bridgePython -B .\bridge.py --limit 3 doctor
```

doctor 只查看入口是否存在，不启动模型、服务或 UI。所有操作要求 `--limit 1–3`；一次 run 只执行一个任务，不会批量派活。

创建你自己的 `task.json`，将 repo 替换为真实、干净且已提交的 Git 仓库根目录：

```json
{
  "task_id": "daily-source",
  "title": "日报模板来源与时间窗口",
  "opencode_mode": "shared",
  "goal": "给已有日报模板增加来源和时间窗口；保持现有样式",
  "repo": "D:/your-real-project",
  "executor": "opencode",
  "model": "opencode-go/deepseek-v4.1-flash",
  "allowed_paths": ["report.html"],
  "artifacts": ["report.html"],
  "input_refs": ["report.html"],
  "completion_criteria": ["页面显示来源和时间窗口", "说明改动及未执行的验证"],
  "timeout_seconds": 300
}
```

上述模型沿用已连接的 OpenCode V2 Console 工作区；桥不配置 CC Switch 或重建 key。示例只说明格式，不代表你已有此仓库或模板。选 DSH 时把 executor 改为 dsh 并移除 model。输入必须是已跟踪的普通文件；忽略文件不会随 worktree 带入。不存在的输入、脏仓库、没有 HEAD 的仓库都会阻塞；桥不自行提交你的源码。

```powershell
& $bridgePython -B .\bridge.py --limit 3 submit .\task.json
& $bridgePython -B .\bridge.py --limit 3 plan daily-source
```

plan 展示动作、作用范围和限制，并返回真实 plan_sha256。用户明确批准这次动作后，手动将下条命令的哈希替换为刚取得的值：

```powershell
& $bridgePython -B .\bridge.py --limit 3 prepare daily-source --plan-sha256 '<真实计划哈希>' --approve-start --ack-unmetered
# 在原生客户端找到同一服务、工作区和会话后，再执行：
& $bridgePython -B .\bridge.py --limit 3 run daily-source --plan-sha256 '<同一真实计划哈希>' --approve-start --ack-unmetered --confirm-visible
```

prepare 新增 detached worktree 和有标题的原生空会话，不发送模型提示词；run 才可能消耗额度。前端显示 ID、服务和实际目录；不能把 API 回读成功当作客户端可见。共享模式取消/超时先发 session.interrupt，只结束本次 CLI 观察进程，不关闭共享服务。原生 idle 时间未确认时状态为 stop_unconfirmed/BLOCKED，禁止重派、修订和接收。两个标记是你对该具体动作及未实证的请求预算限制的确认；Agent 不能自动代填批准。运行器前台等待，可在另一个终端只读查看状态。

```powershell
& $bridgePython -B .\bridge.py --limit 3 status daily-source
# 仅在你明确批准停止该任务进程树后，将 attempt_id 换成 status 中的当前值：
& $bridgePython -B .\bridge.py --limit 3 cancel daily-source --attempt-id '<当前尝试编号>' --approve-cancel
```

cancel 写入请求，运行器处理后才能确认停止；若运行器崩溃或窗口被强制关闭，状态可能仍是 running。不要强行改状态或按进程名杀软件，先报告并只读核对 PID、任务记录和 worktree。取消、超时、失败均保留现场，不自动删目录。

## 结果、修订和人工验收

默认记录在 `data/tasks/<task-id>/`：契约版本、state.json、events.jsonl，以及 attempts 中的工作区、日志、result.json、前后哈希和 diff。工作区默认是 `attempts/<attempt-id>/workspace`；只有该绝对路径 ≥200 字符时才改放短根，`review` 与离线检查一律按 `attempt.json` 记录的真实路径核对，不按固定相对路径猜。新增未跟踪文件由哈希清单和实际文件展示；普通 Git diff 不包含它们。

完成后是 awaiting_review，acceptance 仍为 BLOCKED。退出码非零、缺产物、可观察越界或采集错误会记录 FAIL。DSH 记录原生 sessionId；OpenCode 采集 sessionID 和工具 error 警告。共享会话元数据保存在 native-session.json，发送意图保存在 prompt-intent.json：即使发送失败或中途崩溃也不自动重发。只从原生 session.get 回读 tokens，不估计请求数或费用。任务提示词完整内联契约，不要求读取 worktree 外文件。

有修改意见，将原契约复制为有实际修改的新版本，保持 task_id，手动调用：

```powershell
& $bridgePython -B .\bridge.py --limit 3 revise daily-source .\task-revised.json
& $bridgePython -B .\bridge.py --limit 3 plan daily-source
```

修订保留旧契约和尝试，新一轮使用新工作区。已接收、运行中、已准备的空会话及原生停止未确认任务禁止修订；保留原始会话和现场，不自动清理。

只读审计形成非空证据文件，用户通过真实客户端验证后提供自己的证据文件。人工接收：

```powershell
& $bridgePython -B .\bridge.py --limit 3 review daily-source --decision audit --audit-evidence .\audit.md
& $bridgePython -B .\bridge.py --limit 3 review daily-source --decision accept --audit-evidence .\audit.md --user-evidence .\user-evidence.md
```

桥核对退出状态、结果哈希、工作区是否又变动、证据文件及哈希，然后保存人工接收决定；不会判断两个任意文件就足以证明真实验收。证据内容须由独立只读审计和用户确认。接收不自动合并、不提交、不删除 worktree。

## 手动验证

`tests/manual_checks.py` 提供四个不调用模型的检查：路径越界拒绝、假执行者真实文件修改和回收、被改写结果的拒收，以及长路径回归。长路径回归须显式选择（`--only long_worktree_path`），因为 `--limit` 上限为 3，默认只跑到前三项。只在用户手动执行时于 data 内创建测试仓库、worktree 和本脚本的短时 Python 子进程；不启动真实软件或服务，不自动清理现场。取消、过期结果等其余行为没有动态检查证据。

```powershell
& $bridgePython -B .\tests\manual_checks.py --limit 3
```

这些检查只是辅助，不能代替真实 DSH／OpenCode 客户端路径。真实任务、取消和用户验收仍需各自证据。配套 Skill 在 `skills/agent-bridge/SKILL.md`，未安装到全局；可先让 Codex 读取该文件使用。

本机小范围检查记录：经用户明确授权，路径拒绝通过；另两项首次在 worktree 准备阶段报 `fatal: '$GIT_DIR' too big`。缩短夹具目录后，只复测文件回收和结果改写拒收，两项通过。**该绕法已由桥的短根回退取代**：`long_worktree_path` 用刻意超过 216 字符的夹具验证回退后仍能准备、执行与回收（本机通过）。支持 `--only file_roundtrip tampered_result_rejection long_worktree_path` 选择复测范围，不自动扩大测试。现场位于 data，未清理；这不是原生模型链路的 PASS。

## 共享会话改版的验收边界

- `/api/runtime` 固定记录启动时真正加载的 bridge/adapters/控制台/静态文件哈希、PID、store；文件后来变了不会冒充已加载新版本。浏览器页脚显示摘要。
- 新任务须明确 `title`、`opencode_mode: "shared"` 和已核实模型。先生成计划、创建空会话，在真实 OpenCode 客户端定位后勾选可见，再发送提示词。没有客户端证据则 BLOCKED。
- 桥通过本机 CLI 完成服务认证，不记录配对口令。只允许无凭据的 `http://127.0.0.1:<实际端口>`，不开放远程服务、改 CORS 或安全配置。
- 保留 DSH 长路径回退与 Git 环境修复。本次没有自动运行测试或新模型任务；语法构建检查不等于实机验收。
- 控制台意外退出后，仍可读取既有会话和日志。缺结果的孤立执行需要审查与补采，不自动改状态、重发或伪造成功。

本机 2.0.20 显式 `--server` 只读核验失败：`requires a password; set OPENCODE_PASSWORD`。桥因此使用已认证的默认后台连接，操作前核对 `service status`；不复制服务密码、不修改安全设置。
