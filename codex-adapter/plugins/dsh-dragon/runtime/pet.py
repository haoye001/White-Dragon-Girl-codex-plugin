"""Codex desktop adapter: local video playback, chroma removal and loopback IPC."""
import json
import os
from pathlib import Path
import random
import sys

import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPixmap, QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QWidget, QMenu

ROOT = Path(__file__).resolve().parents[1]
SOCKET = 'dsh-dragon-codex-v1'


def chroma(frame):
    """Only remove green hue; preserve the character's pale hair and blue effects."""
    rgb = cv2.cvtColor(cv2.resize(frame, (640, 360)), cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    green = ((hsv[:, :, 0] > 34) & (hsv[:, :, 0] < 88)
             & (hsv[:, :, 1] > 45) & (hsv[:, :, 2] > 40))
    rgba = np.dstack((rgb, np.where(green, 0, 255).astype(np.uint8)))
    return rgba


class Pet(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(480, 320)
        area = QApplication.primaryScreen().availableGeometry()
        self.move(area.right() - 480, area.bottom() - 320)
        self.actions = {p.stem: p for p in (ROOT / 'assets' / 'videos').glob('*.mp4')}
        self.idle = '待机呼吸休闲'
        self.current = ''
        self.cap = None
        self.pixmap = QPixmap()
        self.offset = None
        self.dragged = False
        self.message = ''
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.play(self.idle)
        self.auto = QTimer(self)
        self.auto.timeout.connect(self.interact)
        self.auto.start(45000)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.accept)
        if not self.server.listen(SOCKET):
            raise RuntimeError('Another pet is already running')
        self.connections = set()

    def play(self, name):
        if name not in self.actions:
            raise ValueError('Unknown animation: ' + name)
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(str(self.actions[name]))
        if not self.cap.isOpened():
            raise RuntimeError('Cannot open video: ' + name)
        self.current = name
        self.timer.start(round(1000 / max(1, self.cap.get(cv2.CAP_PROP_FPS))))

    def tick(self):
        ok, frame = self.cap.read()
        if not ok:
            self.play(self.idle)
            return
        rgba = chroma(frame)
        self.pixmap = QPixmap.fromImage(QImage(rgba.data, 640, 360, 2560, QImage.Format_RGBA8888).copy())
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 50, 480, 270, self.pixmap)
        if self.message:
            painter.setPen(Qt.white)
            painter.setBrush(Qt.darkGray)
            painter.drawRoundedRect(35, 2, 410, 45, 12, 12)
            painter.drawText(45, 5, 390, 40, Qt.AlignCenter | Qt.TextWordWrap, self.message[:100])

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.offset = event.globalPosition().toPoint() - self.pos()
            self.start_pos = event.globalPosition().toPoint()
            self.dragged = False

    def mouseMoveEvent(self, event):
        if self.offset is not None:
            if (event.globalPosition().toPoint() - self.start_pos).manhattanLength() > 6:
                if not self.dragged:
                    if '被鼠标拖拽悬空反馈' in self.actions:
                        self.play('被鼠标拖拽悬空反馈')
                self.dragged = True
                self.move(event.globalPosition().toPoint() - self.offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.offset is not None:
            self.offset = None
            if not self.dragged:
                replies = [n for n in self.actions if n.startswith('点击回应')]
                if replies:
                    self.play(random.choice(replies))
            else:
                self.play(self.idle)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        animations = menu.addMenu('播放动作（全部素材）')
        for name in sorted(self.actions):
            action = animations.addAction(name)
            action.triggered.connect(lambda checked=False, n=name: self.play(n))
        toggle = menu.addAction('自动互动')
        toggle.setCheckable(True)
        toggle.setChecked(self.auto.isActive())
        toggle.triggered.connect(lambda enabled: self.auto.start(45000) if enabled else self.auto.stop())
        menu.addAction('退出桌宠', QApplication.quit)
        menu.exec(event.globalPos())

    def interact(self):
        if self.current == self.idle and self.offset is None:
            self.play(random.choice(list(self.actions)))

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.connections.add(socket)
            socket.readyRead.connect(lambda s=socket: self.receive(s))
            socket.disconnected.connect(lambda s=socket: (self.connections.discard(s), s.deleteLater()))

    def receive(self, socket):
        if not socket.canReadLine():
            return
        try:
            data = json.loads(bytes(socket.readLine()).decode())
            command = data.get('command', 'state')
            if command == 'play':
                self.play(data['animation'])
            elif command == 'say':
                self.message = str(data.get('text', ''))[:100]
                QTimer.singleShot(8000, self.clear_message)
            elif command == 'hide':
                self.hide()
            elif command == 'show':
                self.show()
            elif command == 'stop':
                QTimer.singleShot(100, QApplication.quit)
            elif command != 'state':
                raise ValueError('Unsupported command')
            result = {'running': True, 'animation': self.current, 'animations': sorted(self.actions)}
        except Exception as exc:
            result = {'error': str(exc)}
        socket.write((json.dumps(result, ensure_ascii=False) + '\n').encode())
        socket.flush()
        socket.disconnectFromServer()

    def clear_message(self):
        self.message = ''
        self.update()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    probe = QLocalSocket()
    probe.connectToServer(SOCKET)
    if probe.waitForConnected(300):
        sys.exit(0)
    QLocalServer.removeServer(SOCKET)
    pet = Pet()
    pet.show()
    sys.exit(app.exec())
