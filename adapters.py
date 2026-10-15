"""已核对本机接口的执行器；仅构造命令，不在导入时启动进程。"""
import os
from pathlib import Path
import re

NODE = Path(r"C:\Users\Lenovo\.workbuddy\binaries\node\versions\22.22.2-3\node.exe")
DSH = Path(r"C:\Users\Lenovo\AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\lib\bin.js")
OPENCODE = Path(r"C:\Users\Lenovo\AppData\Roaming\ai.opencode.desktop\cli\2.0.20\opencode-cli.exe")


def build(task, prompt, config):
    adapter = task["executor"]
    if adapter == "dsh":
        node = Path(config.get("node", str(NODE))).resolve()
        entry = Path(config.get("dsh", str(DSH))).resolve()
        if not node.is_file() or not entry.is_file():
            raise ValueError("DSH 或托管 Node 入口不存在")
        if task.get("model"):
            raise ValueError("本机 DSH headless 无模型参数；不能在契约中假装覆盖模型")
        return [str(node), str(entry), "--profile", "headless", "--json", "-"], prompt.encode("utf-8")
    if adapter == "opencode":
        entry = Path(config.get("opencode", str(OPENCODE))).resolve()
        if not entry.is_file():
            raise ValueError("OpenCode CLI 入口不存在")
        model = task.get("model")
        if not isinstance(model, str) or not re.fullmatch(r"[\w.-]+/[\w.#+-]+", model):
            raise ValueError("OpenCode 必须明确指定 provider/model；不使用不明默认值")
        args = [str(entry), "run", "--standalone", "--format", "json", "--model", model]
        agent = task.get("agent")
        if agent:
            if not re.fullmatch(r"[\w.-]+", agent):
                raise ValueError("非法 Agent 名称")
            args += ["--agent", agent]
        return args + [prompt], None
    raise ValueError("只支持 dsh / opencode 执行器")


def facts(config):
    return {
        "dsh": {"entry": config.get("dsh", str(DSH)),
                "entry_exists": Path(config.get("dsh", str(DSH))).is_file(),
                "node_exists": Path(config.get("node", str(NODE))).is_file(),
                "model_selection": "原生 headless 配置；尚未运行验收"},
        "opencode": {"entry": config.get("opencode", str(OPENCODE)),
                     "entry_exists": Path(config.get("opencode", str(OPENCODE))).is_file(),
                     "mode": "--standalone 私有实例"},
        "platform": os.name,
        "upstream_request_limit": "未实证原生请求层；外层仅实现单任务与墙钟超时，未动态验收",
    }


class ProcessTree:
    """Windows Job 限制到自身进程树；不按进程名杀程序。"""
    def __init__(self, process):
        self.process = process
        self.handle = None
        if os.name != "nt":
            return
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_ = [("process_time", c.c_longlong), ("job_time", c.c_longlong),
                        ("flags", w.DWORD), ("min_working_set", c.c_size_t),
                        ("max_working_set", c.c_size_t), ("active_process_limit", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(c.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", c.c_size_t),
                        ("job_memory", c.c_size_t), ("peak_process_memory", c.c_size_t),
                        ("peak_job_memory", c.c_size_t)]
        k = c.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        k.SetInformationJobObject.restype = w.BOOL
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.AssignProcessToJobObject.restype = w.BOOL
        k.CloseHandle.argtypes = [w.HANDLE]
        k.CloseHandle.restype = w.BOOL
        handle = k.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(c.get_last_error(), "无法创建任务进程组")
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(handle, 9, c.byref(info), c.sizeof(info)):
            error = c.get_last_error()
            k.CloseHandle(handle)
            raise OSError(error, "无法设置任务进程组")
        if not k.AssignProcessToJobObject(handle, w.HANDLE(int(process._handle))):
            error = c.get_last_error()
            k.CloseHandle(handle)
            raise OSError(error, "无法登记自身进程；拒绝继续运行")
        self.kernel = k
        self.handle = handle

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        elif os.name != "nt" and self.process.poll() is None:
            import signal
            os.killpg(self.process.pid, signal.SIGTERM)
