"""Standalone model chat with local text history and optional screenshot input."""
from base64 import b64encode
import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSaveFile, QStandardPaths, Qt
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from chat_api import ChatRequest, completions_url
from speech import ReplySpeech


def image_part(image):
    if max(image.width(), image.height()) > 1600:
        image = image.scaled(1600, 1600, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, 'PNG') or data.size() > 8_000_000:
        raise ValueError('截图无法编码，请选择更小的区域。')
    return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + b64encode(bytes(data)).decode('ascii')}}


HISTORY_LIMIT = 4 * 1024 * 1024


def history_path():
    directory = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
    return Path(directory) / 'DSHDragon' / 'chat-history.json'


def load_sessions(path):
    try:
        with path.open('rb') as stream:
            saved = json.loads(stream.read(HISTORY_LIMIT))
    except (OSError, ValueError):
        return []
    if not isinstance(saved, list):
        return []
    sessions = []
    for history in saved[:20]:
        if isinstance(history, list):
            turns = [turn for turn in history[-50:] if isinstance(turn, dict)
                     and all(isinstance(turn.get(key), str) for key in ('question', 'answer'))]
            if turns:
                sessions.append(turns)
    return sessions


class ChatWindow(QDialog):
    def __init__(self, pet):
        super().__init__(pet, Qt.Window)
        self.settings = pet.settings
        self.setWindowTitle('桌宠对话')
        self.resize(650, 540)
        self.history_path = history_path()
        self.sessions = load_sessions(self.history_path)
        self.key = ''
        self.pending = None
        self.image = None
        self.request = ChatRequest(self)
        self.request.delta.connect(self.append)
        self.request.completed.connect(self.complete)
        self.request.failed.connect(self.fail)
        self.request.cancelled.connect(lambda: self.fail('已停止回复。'))
        self.speech = ReplySpeech(self)
        self.speech.failed.connect(self.set_status)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.selector = QComboBox()
        toolbar.addWidget(self.selector, 1)
        self.new_button = QPushButton('新对话')
        self.new_button.clicked.connect(self.new_session)
        toolbar.addWidget(self.new_button)
        self.delete_button = QPushButton('删除对话')
        self.delete_button.clicked.connect(self.delete_session)
        toolbar.addWidget(self.delete_button)
        self.settings_button = QPushButton('模型设置')
        self.settings_button.clicked.connect(self.configure)
        toolbar.addWidget(self.settings_button)
        layout.addLayout(toolbar)

        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        self.history.document().setMaximumBlockCount(5000)
        layout.addWidget(self.history, 1)
        self.attachment = QLabel()
        self.attachment.setAlignment(Qt.AlignCenter)
        self.attachment.hide()
        layout.addWidget(self.attachment)
        self.remove_attachment = QPushButton('移除截图')
        self.remove_attachment.clicked.connect(self.clear_attachment)
        self.remove_attachment.hide()
        layout.addWidget(self.remove_attachment)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText('输入消息后点击发送')
        self.input.setMaximumHeight(110)
        layout.addWidget(self.input)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        controls = QHBoxLayout()
        self.read_aloud = QCheckBox('朗读回复')
        self.read_aloud.setChecked(self.settings.value('chat_read_aloud', False, type=bool))
        self.read_aloud.toggled.connect(self.set_read_aloud)
        controls.addWidget(self.read_aloud)
        controls.addStretch()
        self.cancel_button = QPushButton('停止')
        self.cancel_button.clicked.connect(self.stop)
        controls.addWidget(self.cancel_button)
        self.send_button = QPushButton('发送')
        self.send_button.clicked.connect(self.send)
        controls.addWidget(self.send_button)
        layout.addLayout(controls)

        self.selector.currentIndexChanged.connect(self.render_history)
        self.reload_sessions(0 if self.sessions else -1)
        self.set_busy(False)

    @property
    def endpoint(self):
        return self.settings.value('chat_endpoint', '')

    @property
    def model(self):
        return self.settings.value('chat_model', '')

    def configure(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('模型设置')
        form = QFormLayout(dialog)
        endpoint = QLineEdit(self.endpoint)
        endpoint.setPlaceholderText('https://api.example.com/v1')
        model = QLineEdit(self.model)
        key = QLineEdit(self.key)
        key.setEchoMode(QLineEdit.Password)
        endpoint.textEdited.connect(lambda _text: key.clear())
        description = QLabel('填写支持 Chat Completions 的接口。API Key 仅保留在当前进程中，重启后需重新输入。')
        description.setTextFormat(Qt.PlainText)
        description.setWordWrap(True)
        form.addRow(description)
        form.addRow('接口地址', endpoint)
        form.addRow('模型名称', model)
        form.addRow('API Key（可选）', key)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        while dialog.exec():
            try:
                completions_url(endpoint.text())
                if not model.text().strip():
                    raise ValueError('请填写模型名称。')
            except ValueError as error:
                QMessageBox.warning(dialog, '模型设置', str(error))
                continue
            self.settings.setValue('chat_endpoint', endpoint.text().strip())
            self.settings.setValue('chat_model', model.text().strip())
            self.key = key.text().strip()
            return

    def set_status(self, text):
        self.status.setText(text)

    def set_read_aloud(self, enabled):
        self.settings.setValue('chat_read_aloud', enabled)
        self.cancel_button.setEnabled(self.pending is not None or enabled)
        if not enabled:
            self.speech.stop()

    def reload_sessions(self, index):
        self.selector.blockSignals(True)
        self.selector.clear()
        self.selector.addItem('未保存的新对话', -1)
        for number, session in enumerate(self.sessions):
            name = ' '.join(session[0]['question'].split())[:34]
            self.selector.addItem(name, number)
        self.selector.setCurrentIndex(index + 1)
        self.selector.blockSignals(False)
        self.render_history()

    def selected_history(self):
        index = self.selector.currentData()
        return self.sessions[index] if isinstance(index, int) and index >= 0 else []

    def save(self):
        payload = json.dumps(self.sessions, ensure_ascii=False).encode('utf-8')
        # Keep the active conversation and trim older conversations first.
        while len(payload) >= HISTORY_LIMIT:
            if len(self.sessions) > 1:
                self.sessions.pop()
            else:
                del self.sessions[0][0]
            payload = json.dumps(self.sessions, ensure_ascii=False).encode('utf-8')
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        file = QSaveFile(str(self.history_path))
        if not file.open(QIODevice.WriteOnly):
            return False
        if file.write(payload) != len(payload):
            file.cancelWriting()
            return False
        return file.commit()

    def render_history(self):
        self.history.setPlainText('\n\n'.join(f'你：{turn["question"]}\n桌宠：{turn["answer"]}'
                                             for turn in self.selected_history()))
        self.history.moveCursor(QTextCursor.End)
        self.delete_button.setEnabled(bool(self.selected_history()) and self.pending is None)

    def new_session(self):
        self.clear_attachment()
        self.input.clear()
        self.selector.setCurrentIndex(0)
        self.set_status('')

    def delete_session(self):
        index = self.selector.currentData()
        if not isinstance(index, int) or index < 0:
            return
        if QMessageBox.question(self, '删除对话', '删除当前本地对话记录？') != QMessageBox.Yes:
            return
        del self.sessions[index]
        saved = self.save()
        self.new_session()
        self.reload_sessions(-1)
        if not saved:
            self.set_status('无法写入本地记录，关闭插件后删除可能无法保留。')

    def attach(self, image):
        if self.pending is not None:
            return False
        self.image = image
        self.attachment.setPixmap(QPixmap.fromImage(image).scaled(360, 130, Qt.KeepAspectRatio,
                                                                  Qt.SmoothTransformation))
        self.attachment.show()
        self.remove_attachment.show()
        self.set_status('截图已就绪。发送后会把预览图片提交给所配置的模型。')
        return True

    def clear_attachment(self):
        self.image = None
        self.attachment.clear()
        self.attachment.hide()
        self.remove_attachment.hide()

    def set_busy(self, busy):
        for widget in (self.selector, self.new_button, self.settings_button, self.input,
                       self.send_button, self.remove_attachment):
            widget.setEnabled(not busy)
        self.delete_button.setEnabled(not busy and bool(self.selected_history()))
        self.cancel_button.setEnabled(busy or self.read_aloud.isChecked())

    def send(self):
        question = self.input.toPlainText().strip()
        if self.pending is not None or (not question and self.image is None):
            return
        if len(question) > 4000:
            self.set_status('每条问题最多 4000 字。')
            return
        question = question or '请说明截图中的内容。'
        messages = []
        for turn in self.selected_history()[-6:]:
            messages.extend([{'role': 'user', 'content': turn['question'][:4000]},
                             {'role': 'assistant', 'content': turn['answer'][:5000]}])
        try:
            content = question
            if self.image is not None:
                content = [{'type': 'text', 'text': question}, image_part(self.image)]
            messages.append({'role': 'user', 'content': content})
            self.request.start(self.endpoint, self.model, self.key, messages)
        except (RuntimeError, ValueError) as error:
            self.set_status(str(error))
            return
        self.speech.stop()
        self.pending = question
        self.set_busy(True)
        self.set_status('正在等待模型回复…')
        self.append(f'\n\n你：{question}\n桌宠：')

    def append(self, text):
        self.history.moveCursor(QTextCursor.End)
        self.history.insertPlainText(text)
        self.history.ensureCursorVisible()

    def complete(self, answer):
        history = self.selected_history()
        self.sessions[:] = [history] + [session for session in self.sessions if session is not history][:19]
        history.append({'question': self.pending, 'answer': answer})
        del history[:-50]
        saved = self.save()
        self.pending = None
        self.clear_attachment()
        self.input.clear()
        self.reload_sessions(0)
        self.set_busy(False)
        self.set_status('' if saved else '回复已收到，但本地历史写入失败。')
        if self.read_aloud.isChecked():
            self.speech.speak(answer)

    def fail(self, message):
        self.pending = None
        self.render_history()
        self.set_busy(False)
        self.set_status(message)

    def stop(self):
        self.request.cancel()
        self.speech.stop()

    def done(self, result):
        self.stop()
        self.clear_attachment()
        super().done(result)
