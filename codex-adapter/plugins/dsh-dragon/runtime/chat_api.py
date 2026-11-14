"""Cancelable Chat Completions requests for the desktop chat and vision tools."""
from ipaddress import ip_address
import json
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


def completions_url(value):
    try:
        address = urlsplit(value.strip())
        port = address.port
    except ValueError as error:
        raise ValueError('模型接口地址无效。') from error
    host = address.hostname
    if not host or address.username is not None or address.query or address.fragment or port == 0:
        raise ValueError('请填写模型服务的 HTTPS 地址，或本机模型的 HTTP 地址。')
    if address.scheme != 'https':
        local = host == 'localhost'
        try:
            local = local or ip_address(host).is_loopback
        except ValueError:
            pass
        if address.scheme != 'http' or not local:
            raise ValueError('远程模型必须使用 HTTPS。HTTP 只用于本机模型。')
    path = address.path.rstrip('/')
    if not path.endswith('/chat/completions'):
        path += '/chat/completions'
    return urlunsplit((address.scheme, address.netloc, path, '', ''))


class ChatRequest(QObject):
    delta = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.network = QNetworkAccessManager(self)
        self.reply = None
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.end(error='模型请求超时，请稍后重试。'))

    def start(self, endpoint, model, key, messages):
        if self.reply is not None:
            raise RuntimeError('已有模型请求正在进行。')
        url = QUrl(completions_url(endpoint))
        if not url.isValid() or not url.host():
            raise ValueError('模型接口地址无效。')
        if not model.strip():
            raise ValueError('请先设置模型名称。')
        request = QNetworkRequest(url)
        request.setAttribute(QNetworkRequest.RedirectPolicyAttribute, QNetworkRequest.ManualRedirectPolicy)
        request.setRawHeader(b'Content-Type', b'application/json')
        request.setRawHeader(b'Accept', b'text/event-stream, application/json')
        if key:
            if any(ord(char) < 32 or ord(char) > 126 for char in key):
                raise ValueError('API Key 包含无效字符。')
            request.setRawHeader(b'Authorization', ('Bearer ' + key).encode('utf-8'))
        payload = json.dumps({'model': model, 'messages': messages, 'stream': True},
                             ensure_ascii=False).encode('utf-8')
        self.buffer = b''
        self.output = ''
        self.sse = False
        self.finished_choice = False
        self.reply = self.network.post(request, payload)
        self.reply.setReadBufferSize(64_000)
        self.reply.readyRead.connect(self.read)
        self.reply.finished.connect(self.finish)
        self.timeout.start(90_000)

    def append(self, text):
        if not isinstance(text, str) or not text:
            return
        if len(self.output) + len(text) > 48_000:
            raise ValueError('回复超出桌宠可显示的长度。')
        self.output += text
        self.delta.emit(text)

    def read(self, final=False):
        if self.reply is None:
            return
        data = bytes(self.reply.readAll())
        status = self.reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if status is not None and status != 200:
            return
        self.buffer += data
        if len(self.buffer) > 512_000:
            self.end(error='模型返回的数据过大。')
            return
        is_stream = b'text/event-stream' in bytes(self.reply.rawHeader('Content-Type')).lower()
        if not (is_stream or self.sse or self.buffer.startswith(b'data:')):
            return
        self.sse = True
        if final and self.buffer:
            self.buffer += b'\n'
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if not line.startswith(b'data:'):
                continue
            event = line[5:].strip()
            if not event:
                continue
            if event == b'[DONE]':
                self.end(result=self.output)
                return
            try:
                data = json.loads(event)
                if data.get('error'):
                    self.end(error='模型服务中断了回复，请检查接口配置后重试。')
                    return
                for choice in data.get('choices') or []:
                    if choice.get('index', 0) == 0:
                        self.append(choice.get('delta', {}).get('content'))
                        self.finished_choice |= bool(choice.get('finish_reason'))
            except (ValueError, TypeError, AttributeError):
                self.end(error='模型返回了无法读取的流式数据。')
                return

    def finish(self):
        self.read(final=True)
        if self.reply is None:
            return
        status = self.reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if status != 200 or self.reply.error() != QNetworkReply.NoError:
            detail = f'（HTTP {status}）' if status else ''
            self.end(error=f'模型请求失败{detail}，请检查地址、模型和访问凭据。')
            return
        if not self.sse:
            try:
                self.append(json.loads(self.buffer)['choices'][0]['message']['content'])
            except (ValueError, TypeError, KeyError, IndexError):
                self.end(error='模型返回了无法读取的回复。')
                return
        elif not self.finished_choice:
            self.end(error='流式回复提前中断，请重试。')
            return
        self.end(result=self.output)

    def end(self, result=None, error=None):
        reply, self.reply = self.reply, None
        if reply is None:
            return
        self.timeout.stop()
        if reply.isRunning():
            reply.abort()
        reply.deleteLater()
        self.buffer = b''
        self.output = ''
        if error:
            self.failed.emit(error)
        elif result is None:
            self.cancelled.emit()
        elif not result.strip():
            self.failed.emit('模型没有返回可显示的文字。')
        else:
            self.completed.emit(result)

    def cancel(self):
        self.end()
