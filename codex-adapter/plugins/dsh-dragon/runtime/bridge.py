"""Minimal line-delimited MCP transport. Never reads Codex credentials or chat logs."""
import json
from pathlib import Path
import subprocess
import sys
import time
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalSocket

# MCP stdio must use UTF-8 even on a Chinese Windows console (default CP936).
if sys.stdin is not None:
    sys.stdin.reconfigure(encoding='utf-8')
if sys.stdout is not None:
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
APP = QCoreApplication.instance() or QCoreApplication([])


def request(data):
    socket = QLocalSocket()
    socket.connectToServer('dsh-dragon-codex-v1')
    if not socket.waitForConnected(500):
        return {'running': False}
    socket.write((json.dumps(data) + '\n').encode())
    socket.waitForBytesWritten(1000)
    if not socket.waitForReadyRead(3000):
        return {'error': 'Pet response timeout'}
    return json.loads(bytes(socket.readLine()).decode())


def control(args):
    if args.get('command') == 'start':
        if not request({'command': 'state'}).get('running'):
            pythonw = Path(sys.executable).with_name('pythonw.exe')
            subprocess.Popen([str(pythonw), str(ROOT / 'runtime' / 'pet.py')],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            for _ in range(30):
                time.sleep(.2)
                state = request({'command': 'state'})
                if state.get('running'):
                    return state
            raise RuntimeError('Pet failed to start')
        return request({'command': 'show'})
    return request(args)


def dispatch(message):
    method = message.get('method')
    if method == 'initialize':
        return {'protocolVersion': message.get('params', {}).get('protocolVersion', '2024-11-05'),
                'capabilities': {'tools': {}}, 'serverInfo': {'name': 'dsh-dragon', 'version': '1.0.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': [{'name': 'dragon_control', 'description': 'Control the supplied dragon desktop pet; state returns all animation names.',
                'inputSchema': {'type': 'object', 'properties': {
                    'command': {'type': 'string', 'enum': ['start', 'stop', 'show', 'hide', 'state', 'play', 'say']},
                    'animation': {'type': 'string'}, 'text': {'type': 'string', 'maxLength': 100}},
                    'required': ['command'], 'additionalProperties': False}}]}
    if method == 'tools/call':
        params = message['params']
        if params['name'] != 'dragon_control':
            raise ValueError('Unknown tool')
        result = control(params.get('arguments', {}))
        return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}], 'isError': 'error' in result}
    raise ValueError('Unknown method')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        args = {'command': sys.argv[1]}
        if len(sys.argv) > 2:
            args['animation' if sys.argv[1] == 'play' else 'text'] = sys.argv[2]
        print(json.dumps(control(args), ensure_ascii=False))
    else:
        for line in sys.stdin:
            message = {}
            try:
                message = json.loads(line)
                if 'id' not in message:
                    continue
                reply = {'jsonrpc': '2.0', 'id': message['id'], 'result': dispatch(message)}
            except Exception as exc:
                reply = {'jsonrpc': '2.0', 'id': message.get('id'), 'error': {'code': -32603, 'message': str(exc)}}
            print(json.dumps(reply, ensure_ascii=False), flush=True)
