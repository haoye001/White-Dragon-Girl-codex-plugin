"""Start selected companions once per Codex desktop lifetime."""
import argparse
import ctypes
from pathlib import Path
import subprocess
import sys
import time
import psutil

ROOT = Path(__file__).resolve().parents[1]
BRIDGES = {
    'dsh-dragon': ROOT / 'runtime' / 'bridge.py',
    'bailong-pet': ROOT.parent / 'bailong-pet' / 'runtime' / 'bridge.py',
}


def codex_running():
    for process in psutil.process_iter(['name', 'exe']):
        try:
            name = (process.info['name'] or '').lower()
            path = (process.info['exe'] or '').lower()
            if name == 'chatgpt.exe' and 'openai.codex_' in path:
                return True
            if name == 'codex.exe' and 'codex' in path and process.num_threads() > 0:
                # CLI processes must not trigger desktop autostart.
                continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('plugins', nargs='*')
    plugins = parser.parse_args().plugins or ['dsh-dragon']
    if any(plugin not in BRIDGES for plugin in plugins):
        parser.error('Unknown companion')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, 'Local\\DSHDragonCodexMonitorV1')
    if ctypes.get_last_error() == 183:
        sys.exit(0)
    active = False
    python = Path(sys.executable).with_name('python.exe')
    while True:
        running = codex_running()
        if running != active:
            for plugin in dict.fromkeys(plugins):
                try:
                    subprocess.run([str(python), str(BRIDGES[plugin]),
                                    'start' if running else 'stop'], timeout=65,
                                    creationflags=subprocess.CREATE_NO_WINDOW,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            active = running
        time.sleep(2)
