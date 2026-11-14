"""Codex desktop adapter: local video playback, chroma removal and loopback IPC."""
import json
import ctypes
from ctypes import wintypes
from pathlib import Path
import random
import sys
from time import monotonic, time

import cv2
import numpy as np
from PySide6.QtCore import QAbstractNativeEventFilter, QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QSettings, QTimer
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap, QPolygon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QInputDialog, QMessageBox, QStyle, QSystemTrayIcon
from media import ClipPool

ROOT = Path(__file__).resolve().parents[1]
SOCKET = 'dsh-dragon-codex-v1'


class VisibilityHotkey(QAbstractNativeEventFilter):
    """Register Ctrl+Alt+P on the GUI thread, independent of the pet window."""
    def __init__(self, pet):
        super().__init__()
        self.pet = pet
        self.registered = False
        self.user32 = ctypes.WinDLL('user32') if sys.platform == 'win32' else None

    def enable(self):
        if self.registered:
            return True
        if not self.user32 or not self.user32.RegisterHotKey(None, 1, 0x4003, ord('P')):
            return False
        app = QApplication.instance()
        app.installNativeEventFilter(self)
        app.aboutToQuit.connect(self.disable)
        self.registered = True
        return True

    def disable(self):
        if self.registered:
            self.user32.UnregisterHotKey(None, 1)
            app = QApplication.instance()
            app.removeNativeEventFilter(self)
            app.aboutToQuit.disconnect(self.disable)
            self.registered = False

    def nativeEventFilter(self, event_type, message):
        if event_type == b'windows_dispatcher_MSG':
            event = wintypes.MSG.from_address(int(message))
            if event.message == 0x0312 and event.wParam == 1:
                self.pet.setVisible(not self.pet.isVisible())
                return True, 0
        return False, 0


def chroma(frame):
    """Only remove green hue; preserve the character's pale hair and blue effects."""
    rgb = cv2.cvtColor(cv2.resize(frame, (640, 360)), cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    green = ((hsv[:, :, 0] > 34) & (hsv[:, :, 0] < 88)
             & (hsv[:, :, 1] > 45) & (hsv[:, :, 2] > 40))
    rgba = np.dstack((rgb, np.where(green, 0, 255).astype(np.uint8)))
    return rgba


class Pet(QWidget):
    def __init__(self, owner=None, slot=0):
        super().__init__()
        self.owner = owner
        self.slot = slot
        self.children_pets = {}
        self.pool = owner.pool if owner else ClipPool(chroma)
        self.clip_key = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.resize(480, 320)
        profile = 'Codex Material Pet' if not slot else f'Codex Material Pet {slot}'
        self.settings = QSettings('DSH Dragon', profile)
        self.locked = self.settings.value('locked', False, type=bool)
        self.speed = self.settings.value('speed', 100, type=int)
        self.interval = self.settings.value('interval', 45, type=int)
        self.opacity = min(100, max(20, self.settings.value('opacity', 100, type=int)))
        area = QApplication.primaryScreen().availableGeometry()
        default = area.bottomRight() - QPoint(479, 319)
        position = self.settings.value('position', default, type=QPoint)
        self.move(position if any(screen.availableGeometry().contains(position + self.rect().center())
                                  for screen in QApplication.screens()) else default)
        self.roles = {'默认白龙': ROOT / 'assets' / 'videos'}
        self.roles.update({path.name: path for path in (ROOT / 'assets' / 'characters').glob('*')
                           if path.is_dir() and path.name not in self.roles})
        self.role = self.settings.value('role', '默认白龙')
        self.actions = {}
        self.current = ''
        self.cap = None
        self.pixmap = QPixmap()
        self.offset = None
        self.dragged = False
        self.facing = 1
        self.angle = 0
        self.edge_angle = 0
        self.last_drag = None
        self.glide = QPropertyAnimation(self, b'pos', self)
        self.glide.setDuration(280)
        self.glide.setEasingCurve(QEasingCurve.OutCubic)
        self.glide.finished.connect(self.finish_move)
        self.spin_timer = QTimer(self)
        self.spin_timer.timeout.connect(self.spin_frame)
        self.message = ''
        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.timeout.connect(self.clear_message)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        try:
            self.switch_role(self.role)
        except (ValueError, RuntimeError):
            self.switch_role('默认白龙')
        self.auto = QTimer(self)
        self.auto.timeout.connect(self.interact)
        self.auto.setInterval(self.interval * 1000)
        self.set_auto(self.settings.value('auto', True, type=bool))
        if owner:
            self.setAttribute(Qt.WA_DeleteOnClose)
            self.tray = None
            self.hotkey = owner.hotkey
            return
        try:
            self.todos = json.loads(self.settings.value('todos', '[]'))
            if not isinstance(self.todos, list):
                self.todos = []
        except (TypeError, ValueError):
            self.todos = []
        self.todo_timer = QTimer(self)
        self.todo_timer.timeout.connect(self.check_todos)
        self.todo_timer.start(1000)
        self.hotkey = VisibilityHotkey(self)
        if self.settings.value('visibility_hotkey', False, type=bool):
            self.hotkey.enable()
        self.create_tray()
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.accept)
        if not self.server.listen(SOCKET):
            raise RuntimeError('Another pet is already running')
        self.connections = set()

    def switch_role(self, role):
        if role not in self.roles:
            raise ValueError('未知角色')
        actions = {path.stem: path for path in sorted(self.roles[role].rglob('*'))
                   if path.is_file() and path.suffix.lower() in {'.mp4', '.webm'}}
        idle = next((name for name in ('待机呼吸休闲', 'idle') if name in actions), None)
        if idle is None:
            idle = next((name for name, path in actions.items() if path.parent.name == 'idle'), None)
        if idle is None:
            raise ValueError('角色缺少 idle.webm 或待机呼吸休闲.mp4')
        previous = self.actions, getattr(self, 'idle', None)
        self.actions, self.idle = actions, idle
        try:
            self.play(idle)
        except (ValueError, RuntimeError):
            self.actions, self.idle = previous
            raise
        self.role = role
        self.settings.setValue('role', role)

    def select_role(self, role):
        try:
            self.switch_role(role)
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, '无法切换角色', str(error))

    def spawn_pet(self):
        slot = next((n for n in range(1, 8) if n not in self.children_pets), None)
        if slot is None:
            return
        pet = Pet(self, slot)
        if not pet.settings.contains('position'):
            area = (QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()).availableGeometry()
            pet.move(max(area.left(), self.x() - 72 * slot), max(area.top(), self.y() - 48 * slot))
        self.children_pets[slot] = pet
        pet.destroyed.connect(lambda: self.children_pets.pop(slot, None))
        pet.show()

    def edit_todos(self):
        text, accepted = QInputDialog.getText(self, '待办提醒', '提醒事项（清空可取消）',
                                             text=self.todos[0]['text'] if self.todos else '')
        if not accepted:
            return
        if text.strip():
            minutes, accepted = QInputDialog.getInt(self, '待办提醒', '多少分钟后提醒？', 5, 1, 10080)
            if not accepted:
                return
            self.todos = [{'text': text.strip()[:100], 'due': time() + minutes * 60}]
        else:
            self.todos = []
        self.settings.setValue('todos', json.dumps(self.todos, ensure_ascii=False))

    def check_todos(self):
        if not self.todos or self.todos[0]['due'] > time():
            return
        text = self.todos.pop(0)['text']
        self.settings.setValue('todos', json.dumps(self.todos, ensure_ascii=False))
        if self.isVisible():
            self.say(text)
        elif self.tray:
            self.tray.showMessage('白龙待办提醒', text)
        else:
            self.show()
            self.say(text)

    def play(self, name):
        if name not in self.actions:
            raise ValueError('Unknown animation: ' + name)
        key = (self.actions[name], self.speed, None if name == self.idle else object())
        capture = self.pool.acquire(key)
        self.release_clip()
        self.clip_key, self.cap = key, capture
        self.current = name
        self.update_frame_interval()

    def update_frame_interval(self):
        self.timer.setInterval(max(1, round(1000 * self.cap.interval)))
        if self.isVisible():
            self.timer.start()

    def create_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon(str(ROOT / 'assets' / 'tray.png'))
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('DSH 白龙 · Codex 素材版')
        menu = QMenu(self)
        menu.addAction('显示桌宠', self.show)
        menu.addAction('隐藏桌宠', self.hide)
        passthrough = menu.addAction('鼠标穿透')
        passthrough.setCheckable(True)
        passthrough.toggled.connect(self.set_passthrough)
        menu.addAction('退出桌宠', QApplication.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def set_passthrough(self, enabled):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowTransparentForInput, enabled)
        if visible:
            self.show()

    def showEvent(self, event):
        super().showEvent(event)
        if self.cap is None:
            try:
                self.play(self.current)
            except RuntimeError as error:
                self.say(str(error))
                return
        self.timer.start()
        if self.auto_enabled:
            self.auto.start()

    def hideEvent(self, event):
        self.timer.stop()
        self.release_clip()
        self.auto.stop()
        self.glide.stop()
        self.spin_timer.stop()
        self.angle = 0
        super().hideEvent(event)

    def release_clip(self):
        if self.clip_key is not None:
            self.pool.release(self.clip_key)
            self.clip_key = self.cap = None

    def dragEnterEvent(self, event):
        if '吃Token' in self.actions and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dropEvent(self, event):
        if '吃Token' in self.actions and any(url.isLocalFile() for url in event.mimeData().urls()):
            self.play('吃Token')
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def tick(self):
        frame = self.cap.read(loop=self.current == self.idle)
        if frame is None:
            self.release_clip()
            if self.current == self.idle:
                self.timer.stop()
                self.say('待机动画无法解码，请切换角色或检查素材。')
                return
            self.play(self.idle)
            return
        self.pixmap = frame
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.save()
        painter.setOpacity(self.opacity / 100)
        painter.translate(240, 185)
        painter.rotate(self.angle or self.edge_angle)
        painter.scale(self.facing, 1)
        painter.drawPixmap(-240, -135, 480, 270, self.pixmap)
        painter.restore()
        if self.message:
            font = painter.font()
            font.setPixelSize(14)
            painter.setFont(font)
            flags = Qt.AlignCenter | Qt.TextWordWrap
            text = QRect(63, 0, 354, 120)
            height = painter.boundingRect(text, flags, self.message).height() + 16
            box = QRect(44, 3, 392, height)
            gradient = QLinearGradient(box.topLeft(), box.bottomRight())
            gradient.setColorAt(0, QColor('#f8fdff'))
            gradient.setColorAt(1, QColor('#dedcff'))
            painter.setPen(QColor('#aca6db'))
            painter.setBrush(gradient)
            painter.drawRoundedRect(box, 15, 15)
            painter.setBrush(QColor('#ebe9ff'))
            painter.drawPolygon(QPolygon([QPoint(231, box.bottom()), QPoint(249, box.bottom()),
                                          QPoint(239, box.bottom() + 9)]))
            painter.setPen(QColor('#7864ba'))
            painter.drawText(52, 20, '✦')
            painter.drawText(416, box.bottom() - 8, '✧')
            painter.setPen(QColor('#30284f'))
            painter.drawText(box.adjusted(19, 6, -19, -6), flags, self.message)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.glide.stop()
            self.offset = event.globalPosition().toPoint() - self.pos()
            self.start_pos = event.globalPosition().toPoint()
            self.dragged = False
            self.last_drag = None
            self.drag_velocity = QPoint()

    def mouseMoveEvent(self, event):
        if self.offset is not None:
            can_drag = not self.locked or bool(event.modifiers() & Qt.ShiftModifier)
            if can_drag and (event.globalPosition().toPoint() - self.start_pos).manhattanLength() > 6:
                if not self.dragged:
                    if '被鼠标拖拽悬空反馈' in self.actions:
                        self.play('被鼠标拖拽悬空反馈')
                self.dragged = True
                target = event.globalPosition().toPoint() - self.offset
                now = monotonic()
                if self.last_drag is not None:
                    previous, timestamp = self.last_drag
                    delta = target - previous
                    self.drag_velocity = delta * (0.10 / max(0.016, now - timestamp))
                    if abs(delta.x()) > 2:
                        self.facing = 1 if delta.x() > 0 else -1
                self.last_drag = (target, now)
                self.edge_angle = 0
                self.move(target)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.offset is not None:
            self.offset = None
            if not self.dragged:
                if self.settings.value('click_sound', False, type=bool):
                    QApplication.beep()
                replies = [n for n in self.actions if n.startswith('点击回应')]
                if replies:
                    self.play(random.choice(replies))
            else:
                self.play(self.idle)
                self.release_drag()

    def release_drag(self):
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        velocity = self.drag_velocity if monotonic() - self.last_drag[1] < 0.12 else QPoint()
        target = self.pos() + QPoint(max(-160, min(160, velocity.x())), max(-120, min(120, velocity.y())))
        target.setX(max(area.left(), min(target.x(), area.right() - self.width() + 1)))
        target.setY(max(area.top(), min(target.y(), area.bottom() - self.height() + 1)))
        if target == self.pos():
            self.finish_move()
            return
        self.glide.setStartValue(self.pos())
        self.glide.setEndValue(target)
        self.glide.start()

    def finish_move(self):
        area = (QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()).availableGeometry()
        if self.settings.value('edge_probe', False, type=bool):
            if self.x() <= area.left():
                self.edge_angle = 25
            elif self.geometry().right() >= area.right():
                self.edge_angle = -25
        self.settings.setValue('position', self.pos())
        self.update()

    def spin(self):
        self.spin_started = monotonic()
        self.spin_timer.start(16)

    def spin_frame(self):
        progress = min(1, (monotonic() - self.spin_started) / 0.7)
        self.angle = progress * 360 if progress < 1 else 0
        if progress == 1:
            self.spin_timer.stop()
        self.update()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        host = self.owner or self
        roles = menu.addMenu('切换角色')
        for role in self.roles:
            roles.addAction(role, lambda name=role: self.select_role(name))
        menu.addAction('新增桌宠', host.spawn_pet)
        if self.owner:
            menu.addAction('关闭这只桌宠', self.close)
        else:
            menu.addAction('待办提醒', self.edit_todos)
        animations = menu.addMenu('播放动作（全部素材）')
        for name in sorted(self.actions):
            action = animations.addAction(name)
            action.triggered.connect(lambda checked=False, n=name: self.play(n))
        toggle = menu.addAction('自动互动')
        toggle.setCheckable(True)
        toggle.setChecked(self.auto_enabled)
        toggle.triggered.connect(self.set_auto)
        for key, label in [('click_sound', '点击音效'), ('self_talk', '随机自言自语'),
                           ('edge_probe', '边缘探头')]:
            option = menu.addAction(label)
            option.setCheckable(True)
            option.setChecked(self.settings.value(key, False, type=bool))
            option.toggled.connect(lambda enabled, name=key: self.settings.setValue(name, enabled))
        lock = menu.addAction('锁定位置（Shift 临时拖动）')
        lock.setCheckable(True)
        lock.setChecked(self.locked)
        lock.triggered.connect(self.set_locked)
        menu.addAction('黄金回旋', self.spin)
        shortcut = menu.addAction('全局显隐快捷键（Ctrl+Alt+P）')
        shortcut.setCheckable(True)
        shortcut.setChecked(self.hotkey.registered)
        shortcut.setEnabled(self.hotkey.user32 is not None)
        shortcut.toggled.connect(host.set_visibility_hotkey)
        adjustments = menu.addMenu('显示与播放')
        adjustments.addAction('不透明度', lambda: self.adjust('opacity', '不透明度（%）', 20, 100))
        adjustments.addAction('播放速率', lambda: self.adjust('speed', '播放速率（%）', 25, 300))
        adjustments.addAction('自动互动间隔', lambda: self.adjust('interval', '自动互动间隔（秒）', 5, 3600))
        copy = menu.addAction('复制当前画面')
        copy.setEnabled(not self.pixmap.isNull())
        copy.triggered.connect(lambda: QApplication.clipboard().setPixmap(self.pixmap))
        configurable = {action.text(): action for action in menu.actions()}
        hidden = set(self.settings.value('hidden_menu', [], type=list))
        for label in hidden & configurable.keys():
            configurable[label].setVisible(False)
        menu.addAction('配置菜单', lambda: self.configure_menu(configurable))
        menu.addAction('退出桌宠', QApplication.quit)
        menu.exec(event.globalPos())

    def configure_menu(self, actions):
        text, accepted = QInputDialog.getMultiLineText(
            self, '配置菜单', '每行填写一个要隐藏的菜单项名称。\n可选：' + '、'.join(actions),
            '\n'.join(self.settings.value('hidden_menu', [], type=list)))
        if accepted:
            self.settings.setValue('hidden_menu', [line.strip() for line in text.splitlines()
                                                   if line.strip() in actions])

    def set_auto(self, enabled):
        self.auto_enabled = enabled
        if enabled and self.isVisible():
            self.auto.start()
        else:
            self.auto.stop()
        self.settings.setValue('auto', enabled)

    def set_visibility_hotkey(self, enabled):
        if enabled and not self.hotkey.enable():
            QMessageBox.warning(self, '快捷键注册失败', 'Ctrl+Alt+P 可能已被其他应用占用。')
            return
        if not enabled:
            self.hotkey.disable()
        self.settings.setValue('visibility_hotkey', enabled)

    def set_locked(self, enabled):
        self.locked = enabled
        self.settings.setValue('locked', enabled)

    def adjust(self, key, label, minimum, maximum):
        value, accepted = QInputDialog.getInt(
            self, label, label, self.settings.value(key, 100 if key != 'interval' else 45, type=int),
            minimum, maximum)
        if not accepted:
            return
        self.settings.setValue(key, value)
        if key == 'opacity':
            self.opacity = value
            self.update()
        elif key == 'speed':
            self.speed = value
            self.play(self.current)
        else:
            self.interval = value
            self.auto.setInterval(value * 1000)

    def interact(self):
        if self.current == self.idle and self.offset is None:
            self.play(random.choice(list(self.actions)))
            if not self.message and self.settings.value('self_talk', False, type=bool):
                self.say(random.choice(['休息一下吧。', '我在这里陪着你。', '今天也一起加油。']))

    def say(self, message):
        self.message = message[:100]
        self.bubble_timer.start(8000)
        self.update()

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
                self.say(str(data.get('text', '')))
            elif command == 'activity':
                status = data.get('activity')
                messages = {'thinking': '正在思考', 'working': '正在处理任务', 'attention': '有事项需要确认'}
                if status == 'idle':
                    self.play(self.idle)
                    self.clear_message()
                elif status in messages:
                    if status == 'working' and '写代码' in self.actions:
                        self.play('写代码')
                    self.say(messages[status])
                else:
                    raise ValueError('Unknown activity')
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
    # The Qt.Tool pet window is excluded from the last-primary-window check.
    # Only the explicit menu and IPC exit commands should stop the event loop.
    app.setQuitOnLastWindowClosed(False)
    probe = QLocalSocket()
    probe.connectToServer(SOCKET)
    if probe.waitForConnected(300):
        sys.exit(0)
    QLocalServer.removeServer(SOCKET)
    pet = Pet()
    pet.show()
    sys.exit(app.exec())
