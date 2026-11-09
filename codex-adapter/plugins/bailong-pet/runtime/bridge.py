"""MCP stdio server and passive hook adapter, using only Python stdlib."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager

from core import DATA, ROOT, VERSION, animation_catalog, read_json, validate_command


def request(value, timeout=30):
    endpoint = read_json(DATA / 'endpoint.json', {})
    port, token = endpoint.get('port'), endpoint.get('token')
    if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str) or len(token) < 32:
        raise RuntimeError('白龙桌宠尚未启动')
    req = urllib.request.Request(f'http://127.0.0.1:{port}/command',
        data=json.dumps(value, ensure_ascii=False).encode('utf8'),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+token})
    # Never send a local bearer token to a system-configured HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError('桌宠拒绝了请求：'+str(exc.code)) from exc


@contextmanager
def launch_lock():
    import msvcrt
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / 'launch.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        deadline = time.monotonic()+35
        while True:
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('桌宠正在启动，请稍后重试')
                time.sleep(.1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def start():
    if os.name != 'nt':
        raise RuntimeError('此桌宠插件目前仅支持 Windows')
    with launch_lock():
        try:
            return request({'action': 'state'}, 1)
        except (OSError, ValueError, RuntimeError):
            pass
        python = sys.executable
        pythonw = os.path.join(os.path.dirname(python), 'pythonw.exe')
        executable = pythonw if os.path.isfile(pythonw) else python
        with (DATA / 'runtime.log').open('a', encoding='utf8') as log:
            process = subprocess.Popen([executable, str(ROOT / 'runtime' / 'app.py')], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('桌宠启动失败；请查看 '+str(DATA / 'runtime.log'))
            try:
                return request({'action': 'state'}, 1)
            except (OSError, ValueError, RuntimeError):
                time.sleep(.15)
        process.terminate()
        raise RuntimeError('桌宠启动超时；请查看 '+str(DATA / 'runtime.log'))


CONTROL = {'type': 'object', 'properties': {
    'action': {'type': 'string', 'enum': ['start', 'stop', 'show', 'hide', 'say', 'play']},
    'message': {'type': 'string', 'minLength': 1, 'maxLength': 1000},
    'seconds': {'type': 'number', 'minimum': 1, 'maximum': 60},
    'animation': {'type': 'string', 'description': '先查询 bailong_state 获取动作 ID'}
}, 'required': ['action'], 'additionalProperties': False}
USAGE = {'type': 'object', 'properties': {'windows': {'type': 'array', 'minItems': 1, 'maxItems': 8,
    'items': {'type': 'object', 'properties': {
        'label': {'type': 'string', 'minLength': 1, 'maxLength': 50},
        'used_percent': {'type': 'number', 'minimum': 0, 'maximum': 100},
        'resets_at': {'type': ['number', 'null'], 'description': 'Unix 秒数；未提供则 null'}
    }, 'required': ['label', 'used_percent'], 'additionalProperties': False}}},
    'required': ['windows'], 'additionalProperties': False}
TOOLS = [
    {'name': 'bailong_control', 'description': '启动、退出、显示、隐藏白龙娘桌宠，让她说话或播放随包动作。仅控制桌宠，不执行任务或访问账号。',
     'inputSchema': CONTROL, 'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'bailong_state', 'description': '查看白龙娘桌宠运行状态、动作列表和上次传入的额度。不会自动启动。',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'readOnlyHint': True, 'openWorldHint': False}},
    {'name': 'bailong_display_usage', 'description': '将当前聊天通过 Codex get_usage_limits 读到的真实额度显示到桌宠。此工具不查询账号；严禁编造数值。',
     'inputSchema': USAGE, 'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}},
    {'name': 'bailong_usage', 'description': '通过已配置的本机 Codex 后台查询真实剩余额度并在气泡显示。立即返回查询中，稍后可用 bailong_state 查看结果；不创建对话、不生成模型回复。',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': True}},
    {'name': 'bailong_settings', 'description': '开启或关闭白龙娘定时随机互动，设置平均互动间隔（秒，实际为其 2/3 至 4/3）。只持久化这两项偏好。',
     'inputSchema': {'type': 'object', 'properties': {'settings': {'type': 'object', 'properties': {
         'auto_interact': {'type': 'boolean'}, 'auto_interval_seconds': {'type': 'number', 'minimum': 10, 'maximum': 600}},
         'additionalProperties': False, 'minProperties': 1}}, 'required': ['settings'], 'additionalProperties': False},
     'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False}}
]


def tool_call(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError('arguments 必须是对象')
    if name == 'bailong_state':
        try:
            return request({'action': 'state'}, 2)
        except (OSError, ValueError, RuntimeError):
            return {'running': False, 'animations': [{'id': k, 'name': v.get('name', k)}
                    for k,v in animation_catalog().items()]}
    if name == 'bailong_display_usage':
        value = {'action': 'usage', 'windows': arguments.get('windows')}
    elif name == 'bailong_usage':
        value = {'action': 'query_usage'}
    elif name == 'bailong_settings':
        value = {'action': 'settings', 'settings': arguments.get('settings')}
    elif name == 'bailong_control':
        if arguments.get('action') == 'start':
            return start()
        value = arguments
        if value.get('action') in {'state', 'usage', 'event', 'settings', 'query_usage'}:
            raise ValueError('该操作不属于 bailong_control')
    else:
        raise ValueError('未知工具')
    validate_command(value, animation_catalog())
    # Closing or hiding an absent pet must not start a new GUI.
    if value['action'] in {'stop', 'hide'}:
        try:
            return request(value, 2)
        except (OSError, ValueError, RuntimeError):
            return {'running': False}
    start()
    return request(value)


def handle(message):
    if not isinstance(message, dict):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
    if 'id' not in message:
        return None
    response = {'jsonrpc': '2.0', 'id': message['id']}
    method = message.get('method')
    if method == 'initialize':
        response['result'] = {'protocolVersion': message.get('params', {}).get('protocolVersion', '2024-11-05'),
            'capabilities': {'tools': {}}, 'serverInfo': {'name': 'bailong-pet', 'version': VERSION}}
    elif method == 'ping':
        response['result'] = {}
    elif method == 'tools/list':
        response['result'] = {'tools': TOOLS}
    elif method == 'tools/call':
        try:
            params = message.get('params', {})
            value = tool_call(params.get('name'), params.get('arguments', {}))
            response['result'] = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}
        except Exception as exc:
            response['result'] = {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
    else:
        response['error'] = {'code': -32601, 'message': 'Method not found'}
    return response


def mcp():
    for line in sys.stdin:
        try:
            if len(line) > 65536:
                raise ValueError('Request too large')
            response = handle(json.loads(line))
        except (ValueError, TypeError) as exc:
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': str(exc)}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


def hook():
    # Process only event names. Prompts, tool args and outputs are never forwarded or saved.
    try:
        value = json.loads(sys.stdin.read(262144))
        event = value.get('hook_event_name')
        if event in {'UserPromptSubmit', 'PreToolUse', 'Stop', 'Interrupt', 'SessionEnd', 'PermissionRequest'}:
            request({'action': 'event', 'event': event}, 2)
    except Exception:
        pass  # Passive status reporting must not change tool approval or block work.


if __name__ == '__main__':
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf8')
        sys.stdout.reconfigure(encoding='utf8')
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['mcp', 'start', 'state', 'stop', 'hook'])
    mode = parser.parse_args().mode
    if mode == 'mcp':
        mcp()
    elif mode == 'hook':
        hook()
    else:
        result = start() if mode == 'start' else tool_call('bailong_state', {}) if mode == 'state' else tool_call('bailong_control', {'action': 'stop'})
        print(json.dumps(result, ensure_ascii=False))
