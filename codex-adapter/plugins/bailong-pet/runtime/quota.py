"""Read only Codex rate limits over its documented stdio app-server API."""
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def normalize(result):
    buckets = result.get('rateLimitsByLimitId') or {}
    bucket = buckets.get('codex') or result.get('rateLimits')
    if not isinstance(bucket, dict):
        raise RuntimeError('当前账户没有可读取的 Codex 额度。')
    windows = []
    for key in ('primary', 'secondary'):
        window = bucket.get(key)
        if not isinstance(window, dict):
            continue
        used = window.get('usedPercent')
        if type(used) not in (int, float) or not math.isfinite(used) or not 0 <= used <= 100:
            continue
        minutes = window.get('windowDurationMins')
        label = '5 小时' if minutes == 300 else '一周' if minutes == 10080 else f'{minutes} 分钟' if minutes else '额度窗口'
        resets = window.get('resetsAt')
        if type(resets) not in (int, float) or not math.isfinite(resets) or not 0 < resets < 10**11:
            resets = None
        windows.append({'label': label, 'used_percent': used, 'resets_at': resets})
    if not windows:
        raise RuntimeError('服务没有返回有效的额度数值，请稍后再试。')
    return windows


def format_usage(usage):
    lines = ['Codex 剩余额度']
    for window in usage['windows']:
        lines.append(f"{window['label']}：{100-window['used_percent']:.1f}%")
        reset = window.get('resets_at')
        if reset:
            lines.append('重置：'+datetime.fromtimestamp(reset).astimezone().strftime('%m-%d %H:%M'))
    lines.append('查询于 '+usage['checked_at'][11:19])
    return '\n'.join(lines)


def fetch(timeout=25, cancel=None):
    config = read_json(ROOT/'runtime-config.json', {})
    executable = Path(config.get('codex', '') if isinstance(config, dict) else '')
    # Never search PATH or the task directory for an executable.
    if not executable.is_absolute() or not executable.is_file() or executable.name.lower() != 'codex.exe':
        raise RuntimeError('未配置有效的 Codex 路径，请重新运行安装脚本。')
    messages = queue.Queue(maxsize=128)
    process = subprocess.Popen([str(executable), 'app-server'], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def receive():
        try:
            for line in process.stdout:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict) and 'id' in value:
                    messages.put(value, timeout=1)
        except (OSError, ValueError, queue.Full):
            pass

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()
    deadline = time.monotonic()+timeout

    def send(value):
        process.stdin.write(json.dumps(value)+'\n')
        process.stdin.flush()

    def response(identifier):
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                raise RuntimeError('额度查询已取消。')
            try:
                value = messages.get(timeout=min(.2, max(.001, deadline-time.monotonic())))
            except queue.Empty:
                if process.poll() is not None:
                    raise RuntimeError('Codex 连接提前结束，请确认已登录。')
                continue
            if value.get('id') != identifier:
                continue
            if value.get('error'):
                raise RuntimeError('额度读取失败，请检查 Codex 登录状态及网络后重试。')
            return value.get('result', {})
        raise RuntimeError('额度查询超时，请检查网络或代理后重试。')

    try:
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {
            'name': 'bailong_pet_quota', 'title': '白龙桌宠只读额度查询', 'version': '1.1.0'}}})
        response(1)
        send({'method': 'initialized', 'params': {}})
        send({'id': 2, 'method': 'account/rateLimits/read'})
        return normalize(response(2))
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=3)
        process.stdin.close()
        reader.join(timeout=1)
        process.stdout.close()
