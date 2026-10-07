import ctypes
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

if os.name != 'nt':
    print('SKIP: Windows Job Object lifecycle test requires Windows.')
    raise SystemExit(0)

SOURCE = Path(__file__).resolve().parents[1] / 'service.py'
spec = importlib.util.spec_from_file_location('omni_service_test', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.1)
    raise AssertionError('Timed out')

def alive(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    try:
        kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)

with tempfile.TemporaryDirectory(prefix='qwen-omni-lifecycle-') as directory:
    directory = Path(directory)
    fake = directory / 'fake_server.py'
    fake.write_text('''import json,sys,time
from http.server import BaseHTTPRequestHandler,HTTPServer
started=time.monotonic()
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  ready=time.monotonic()-started>.5
  self.send_response(200 if ready else 503); self.end_headers()
  self.wfile.write(json.dumps({'status':'ok' if ready else 'loading'}).encode())
 def log_message(self,*args): pass
HTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()
''', encoding='utf-8')
    class FakeService(module.OmniService):
        def command(self):
            return [sys.executable, str(fake), str(self.config['port'])]
    service = FakeService(directory)
    service.config['server_exe'] = 'llama-server.exe'
    service.config['port'] = free_port()
    try:
        assert service.status()['state'] == 'stopped'
        service.acquire(service.config['port'])
        pid = service.process.pid
        assert service.status()['ready'] and service.status()['owned']
        service.start()
        assert service.process.pid == pid
        try:
            service.stop()
            raise AssertionError('Stopped during active inference')
        except ValueError:
            pass
        service.release()
        try:
            service.save_config(service.config)
            raise AssertionError('Changed running configuration')
        except ValueError:
            pass
        service.stop()
        wait_for(lambda: not alive(pid))
        assert service.status()['state'] == 'stopped'
        service.save_config({'gpu_layers': 16})
        assert json.loads(service.config_path.read_text())['gpu_layers'] == 16
        external = subprocess.Popen([sys.executable, str(fake), str(service.config['port'])], creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            wait_for(lambda: service.health(service.config['port']) == 'ready')
            assert service.status()['state'] == 'external'
            try:
                service.start()
                raise AssertionError('Started over external service')
            except ValueError:
                pass
            service.stop()
            assert external.poll() is None
        finally:
            external.terminate(); external.wait()
        service.config['auto_start'] = False
        try:
            service.acquire(service.config['port'])
            raise AssertionError('auto_start=False ignored')
        except ValueError:
            pass
    finally:
        service.shutdown()

    parent_script = directory / 'parent.py'
    pidfile = directory / 'child.pid'
    parent_script.write_text(f'''import importlib.util,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('test_service',{str(SOURCE)!r})
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class S(m.OmniService):
 def command(self): return [sys.executable,{str(fake)!r},str(self.config['port'])]
s=S({str(directory)!r}); s.config['port']={free_port()}; s.start()
Path({str(pidfile)!r}).write_text(str(s.process.pid))
time.sleep(60)
''', encoding='utf-8')
    parent = subprocess.Popen([sys.executable, str(parent_script)], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        wait_for(pidfile.exists)
        child_pid = int(pidfile.read_text())
        assert alive(child_pid)
        parent.kill(); parent.wait()
        wait_for(lambda: not alive(child_pid))
    finally:
        if parent.poll() is None:
            parent.kill(); parent.wait()
    print('PASS: automatic startup, readiness, service reuse, active-request guard, config persistence, external-service ownership, disabled auto-start, Windows abrupt-parent-exit cleanup')
