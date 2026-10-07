import atexit
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request


PLUGIN_DIR = Path(__file__).parent
DEFAULT_CONFIG = {
    "server_exe": "",
    "model_dir": str(PLUGIN_DIR.parents[1] / "models" / "LLM" / "Qwen3-Omni"),
    "port": 8736,
    "gpu_layers": 24,
    "context_size": 4096,
    "startup_timeout": 600,
    "auto_start": True,
}


class WindowsJob:
    def __init__(self):
        class BasicLimits(ctypes.Structure):
            _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                        ("Flags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                        ("MaxWorkingSet", ctypes.c_size_t), ("ActiveProcesses", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("Priority", wintypes.DWORD),
                        ("Scheduling", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("Basic", BasicLimits), ("IO", ctypes.c_uint64 * 6),
                        ("ProcessMemory", ctypes.c_size_t), ("JobMemory", ctypes.c_size_t),
                        ("PeakProcessMemory", ctypes.c_size_t), ("PeakJobMemory", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class OmniService:
    def __init__(self, directory=PLUGIN_DIR):
        self.directory = Path(directory)
        self.config_path = self.directory / "service_config.json"
        self.log_path = self.directory / "llama-server.log"
        self.config = dict(DEFAULT_CONFIG)
        if self.config_path.exists():
            self.config.update(json.loads(self.config_path.read_text(encoding="utf-8")))
        self.process = None
        self.job = None
        self.lock = threading.RLock()
        self.last_error = ""
        self.active_requests = 0

    def save_config(self, values):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                raise ValueError("先停止托管服务再修改配置。")
            config = {key: values.get(key, self.config[key]) for key in DEFAULT_CONFIG}
            for key, low, high in (("port", 1, 65535), ("gpu_layers", 0, 256),
                                   ("context_size", 1024, 262144), ("startup_timeout", 10, 3600)):
                config[key] = int(config[key])
                if not low <= config[key] <= high:
                    raise ValueError(f"{key} 必须在 {low} 到 {high} 之间。")
            if not isinstance(config["auto_start"], bool):
                raise ValueError("auto_start 必须是布尔值。")
            for key in ("server_exe", "model_dir"):
                config[key] = str(config[key]).strip()
            if Path(config["server_exe"]).name.lower() not in ("llama-server.exe", "llama-server"):
                raise ValueError("请选择 llama-server 可执行文件。")
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.config_path)
            self.config = config
            self.last_error = ""

    def health(self, port):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(f"http://127.0.0.1:{port}/health", timeout=0.6) as response:
                return "ready" if json.load(response).get("status") == "ok" else "loading"
        except urllib.error.HTTPError as exc:
            return "loading" if exc.code == 503 else "unavailable"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return "unavailable"

    def log_tail(self):
        if not self.log_path.exists():
            return ""
        with self.log_path.open("rb") as log:
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 6000))
            return log.read().decode("utf-8", errors="replace")

    def status(self):
        with self.lock:
            owned = self.process is not None and self.process.poll() is None
            health = self.health(self.config["port"])
            if owned:
                state = "running" if health == "ready" else "loading"
            elif health != "unavailable":
                state = "external"
            elif self.process is not None or self.last_error:
                state = "error"
                if not self.last_error and self.process is not None:
                    self.last_error = f"服务已退出，代码 {self.process.returncode}。"
            else:
                state = "stopped"
            return {"state": state, "ready": health == "ready", "owned": owned,
                    "pid": self.process.pid if owned else None, "config": dict(self.config),
                    "error": self.last_error, "active_requests": self.active_requests,
                    "log": self.log_tail()}

    def command(self):
        config = self.config
        if not config["server_exe"]:
            raise ValueError("请先在浮窗的服务配置中设置 llama-server 完整路径并保存。")
        model = Path(config["model_dir"]) / "Qwen3-Omni-30B-A3B-Instruct-Q4_K_M.gguf"
        mmproj = Path(config["model_dir"]) / "mmproj-Qwen3-Omni-30B-A3B-Instruct-Q8_0.gguf"
        for path in (Path(config["server_exe"]), model, mmproj):
            if not path.is_file():
                raise FileNotFoundError(f"缺少文件：{path}")
        return [config["server_exe"], "--model", str(model), "--mmproj", str(mmproj),
                "--alias", "qwen3-omni", "--host", "127.0.0.1", "--port", str(config["port"]),
                "--ctx-size", str(config["context_size"]), "--parallel", "1",
                "--n-gpu-layers", str(config["gpu_layers"]), "--jinja"]

    def start(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", self.config["port"])) == 0:
                    raise ValueError("端口已被外部服务占用。先关闭手动启动的服务，再由工具栏启动。")
            command = self.command()
            if self.job is not None:
                self.job.close()
                self.job = None
            self.process = None
            self.last_error = ""
            env = os.environ.copy()
            exe_dir = str(Path(self.config["server_exe"]).parent)
            env["PATH"] = exe_dir + os.pathsep + env.get("PATH", "")
            try:
                if os.name == "nt":
                    self.job = WindowsJob()
                with self.log_path.open("wb") as log:
                    self.process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                                    env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                if self.job is not None:
                    self.job.assign(self.process)
            except Exception as exc:
                if self.process is not None and self.process.poll() is None:
                    self.process.kill()
                    self.process.wait()
                if self.job is not None:
                    self.job.close()
                    self.job = None
                self.last_error = str(exc)
                raise

    def stop(self):
        with self.lock:
            if self.active_requests:
                raise ValueError("音频正在推理，等工作流结束后再停止服务。")
            self.shutdown()
            self.last_error = ""

    def shutdown(self):
        with self.lock:
            if self.job is not None:
                self.job.close()
                self.job = None
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None

    def acquire(self, port):
        with self.lock:
            health = self.health(port)
            if health != "ready":
                if port != self.config["port"]:
                    raise ValueError("节点端口与工具栏配置不一致，请修改节点 port。")
                if self.process is None or self.process.poll() is not None:
                    if not self.config["auto_start"]:
                        raise ValueError("服务未就绪，请在 Qwen Omni 工具栏启动，或启用自动启动。")
                    self.start()
            self.active_requests += 1
        try:
            deadline = time.monotonic() + self.config["startup_timeout"]
            while self.health(port) != "ready":
                with self.lock:
                    if self.process is None or self.process.poll() is not None:
                        raise RuntimeError("托管服务退出。请查看工具栏日志。\n" + self.log_tail())
                if time.monotonic() >= deadline:
                    raise TimeoutError("模型加载超时，请查看工具栏日志。服务保留运行，可稍后再次执行。")
                time.sleep(0.5)
        except Exception:
            self.release()
            raise

    def release(self):
        with self.lock:
            self.active_requests -= 1


service = OmniService()
atexit.register(service.shutdown)
