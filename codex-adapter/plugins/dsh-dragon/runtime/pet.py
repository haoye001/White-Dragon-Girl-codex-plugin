"""Codex desktop adapter: local video playback, chroma removal and loopback IPC."""
import json
import ctypes
from ctypes import wintypes
from pathlib import Path
import random
import re
import sys
from time import monotonic, time
if sys.platform == 'win32':
    import winsound

import cv2
import numpy as np
from PySide6.QtCore import QAbstractNativeEventFilter, QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QSettings, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QLinearGradient, QPainter, QPixmap, QPolygon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget, QMenu, QInputDialog, QMessageBox, QStyle, QSystemTrayIcon
from activity import Activity
from media import ClipPool
from dialogs import TodoDialog, edit_hotkey, edit_menu, edit_settings
from island import MediaDashboard
from widgets import DesktopWidgets

ROOT = Path(__file__).resolve().parents[1]
SOCKET = 'dsh-dragon-codex-v1'


class VisibilityHotkey(QAbstractNativeEventFilter):
    """Register a single Windows hotkey independent of the pet window."""
    def __init__(self, pet):
        super().__init__()
        self.pet = pet
        self.registered = False
        self.user32 = ctypes.WinDLL('user32') if sys.platform == 'win32' else None
        self.sequence = pet.settings.value('visibility_sequence', 'Ctrl+Alt+P')

    @staticmethod
    def key_codes(sequence):
        parts = sequence.split('+')
        modifiers = {'Ctrl': 2, 'Alt': 1, 'Shift': 4, 'Meta': 8}
        if (len(parts) < 2 or len(set(parts[:-1])) != len(parts) - 1
                or any(part not in modifiers for part in parts[:-1])
                or not re.fullmatch('[A-Z0-9]', parts[-1])):
            raise ValueError('请选择带修饰键的单个字母或数字快捷键。')
        return 0x4000 | sum(modifiers[part] for part in parts[:-1]), ord(parts[-1])

    def enable(self):
        if self.registered:
            return True
        try:
            modifiers, key = self.key_codes(self.sequence)
        except ValueError:
            return False
        if not self.user32 or not self.user32.RegisterHotKey(None, 1, modifiers, key):
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
    todos_changed = Signal()

    def __init__(self, owner=None, slot=0):
        super().__init__()
        self.owner = owner
        self.slot = slot
        self.children_pets = {}
        self.pool = owner.pool if owner else ClipPool(chroma)
        if owner is None:
            QApplication.instance().aboutToQuit.connect(self.pool.close)
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
        self.bubble_font = min(24, max(10, self.settings.value('bubble_font', 14, type=int)))
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
        self.timer.setTimerType(Qt.PreciseTimer)
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
        self.widgets = DesktopWidgets(self)
        self.activity = Activity()
        self.activity_state = ('idle', 0)
        self.dashboard = MediaDashboard(self)
        self.chat_window = None
        self.screen_watcher = None
        self.selecting_screenshot = False
        self.activity_timer = QTimer(self)
        self.activity_timer.timeout.connect(self.refresh_activity)
        self.activity_timer.start(15_000)
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
        dialog = TodoDialog(self)
        self.todos_changed.connect(dialog.refresh)
        try:
            dialog.exec()
        finally:
            self.todos_changed.disconnect(dialog.refresh)
            dialog.deleteLater()

    def save_todos(self):
        self.settings.setValue('todos', json.dumps(self.todos, ensure_ascii=False))
        self.todos_changed.emit()

    def check_todos(self):
        now = time()
        reminders = []
        changed = False
        for todo in self.todos:
            if todo.get('archived'):
                continue
            remaining = todo['due'] - now
            if remaining <= 0:
                todo['archived'] = True
                changed = True
                if remaining >= -600:
                    reminders.append(todo['text'])
            elif remaining <= todo.get('lead', 0) * 60 and not todo.get('warned'):
                todo['warned'] = True
                changed = True
                reminders.append('即将到期：' + todo['text'])
        if changed:
            self.save_todos()
        if not reminders:
            return
        self.notify('白龙待办提醒', '\n'.join(reminders))

    def notify(self, title, text, duration=8000):
        if self.isVisible():
            self.say(text, duration)
        elif self.tray:
            self.tray.showMessage(title, text, msecs=duration)
        else:
            self.show()
            self.say(text, duration)

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
        self.timer.setInterval(8)
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
        menu.addAction('查询 Codex 额度', self.widgets.request_quota)
        menu.addAction('桌面灵动岛', self.dashboard.show)
        menu.addAction('桌宠对话', self.open_chat)
        menu.addAction('截图问答', self.queue_screenshot)
        menu.addAction('开启 / 停止主动识屏', self.toggle_screen_watcher)
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
        if self.owner is None and getattr(self, 'screen_watcher', None) is not None:
            self.screen_watcher.pause()
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
        frame = self.cap.read()
        if self.cap.finished:
            self.release_clip()
            if self.current == self.idle:
                self.timer.stop()
                self.say('待机动画无法解码，请切换角色或检查素材。')
                return
            self.play(self.idle)
            return
        if frame is not None and frame is not self.pixmap:
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
            font.setPixelSize(self.bubble_font)
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
                    self.play_click_sound()
                replies = [n for n in self.actions if n.startswith('点击回应')]
                if replies:
                    self.play(random.choice(replies))
            else:
                self.play(self.idle)
                self.release_drag()

    def release_drag(self):
        screens = QApplication.screens()
        center = self.geometry().center()
        screen = QApplication.screenAt(center) or min(
            screens, key=lambda item: (item.availableGeometry().center() - center).manhattanLength())
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
        host = self.owner or self
        if host.settings.value('pet_collisions', False, type=bool):
            for other in (host, *host.children_pets.values()):
                if other is not self and other.isVisible() and not other.locked and other.offset is None:
                    overlap = self.geometry().adjusted(100, 85, -100, -35).intersected(
                        other.geometry().adjusted(100, 85, -100, -35))
                    if not overlap.isEmpty():
                        other.move_away_from(self, overlap.width())
        self.update()

    def move_away_from(self, pet, distance):
        area = (QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()).availableGeometry()
        direction = 1 if self.x() >= pet.x() else -1
        target = max(area.left(), min(self.x() + direction * distance, area.right() - self.width() + 1))
        self.move(target, self.y())
        self.settings.setValue('position', self.pos())

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
        host.widgets.add_actions(menu)
        menu.addAction('桌面灵动岛', host.dashboard.show)
        menu.addAction('桌宠对话', host.open_chat)
        menu.addAction('截图问答', host.queue_screenshot)
        if sys.platform == 'win32':
            vision = menu.addMenu('主动识屏')
            enabled = host.screen_watcher is not None and host.screen_watcher.timer.isActive()
            vision.addAction('停止识屏' if enabled else '开启识屏', host.toggle_screen_watcher)
            vision.addAction('识屏设置…', host.configure_screen_watcher)
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
        adjustments.addAction('气泡字号', lambda: self.adjust('bubble_font', '气泡字号（像素）', 10, 24))
        adjustments.addAction('修改自言自语台词', self.edit_self_talk)
        if sys.platform == 'win32':
            adjustments.addAction('设置全局显隐快捷键…', host.configure_visibility_hotkey)
            adjustments.addAction('选择点击音效…', self.choose_click_sound)
            if self.settings.value('click_wav', ''):
                adjustments.addAction('恢复默认点击音效', lambda: self.settings.remove('click_wav'))
        collisions = adjustments.addAction('多宠轻碰撞')
        collisions.setCheckable(True)
        collisions.setChecked(host.settings.value('pet_collisions', False, type=bool))
        collisions.toggled.connect(lambda enabled: host.settings.setValue('pet_collisions', enabled))
        copy = menu.addAction('复制当前画面')
        copy.setEnabled(not self.pixmap.isNull())
        copy.triggered.connect(lambda: QApplication.clipboard().setPixmap(self.pixmap))
        configurable = {action.text(): action for action in menu.actions()}
        labels = list(dict.fromkeys(self.settings.value('menu_order', [], type=list) + list(configurable)))
        labels = [label for label in labels if label in configurable]
        hidden = set(self.settings.value('hidden_menu', [], type=list))
        groups = self.menu_groups()
        submenus = {}
        for label in labels:
            action = configurable[label]
            menu.removeAction(action)
            if label in hidden:
                continue
            group = groups.get(label)
            if group and group not in submenus:
                submenus[group] = menu.addMenu(group)
            submenus.get(group, menu).addAction(action)
        shortcut.setText(f'全局显隐快捷键（{self.hotkey.sequence}）')
        menu.addAction('桌宠设置', self.configure_settings)
        menu.addAction('配置菜单', lambda: self.configure_menu(labels, hidden))
        menu.addAction('退出桌宠', QApplication.quit)
        menu.exec(event.globalPos())

    def menu_groups(self):
        raw = self.settings.value('menu_groups', '{}')
        try:
            groups = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        if not isinstance(groups, dict):
            return {}
        return {label: group for label, group in groups.items() if isinstance(group, str) and group}

    def configure_menu(self, labels, hidden):
        result = edit_menu(self, labels, hidden, self.menu_groups())
        if result is not None:
            order, hidden, groups = result
            self.settings.setValue('menu_order', order)
            self.settings.setValue('hidden_menu', hidden)
            self.settings.setValue('menu_groups', json.dumps(groups, ensure_ascii=False))

    def configure_settings(self):
        result = edit_settings(self)
        if result is None:
            return
        numbers, switches = result
        for key, value in numbers.items():
            if getattr(self, key) != value:
                self.apply_adjustment(key, value)
        self.set_auto(switches.pop('auto'))
        self.set_locked(switches.pop('locked'))
        for key, enabled in switches.items():
            self.settings.setValue(key, enabled)

    def chat(self):
        if self.chat_window is None:
            from chat_window import ChatWindow
            self.chat_window = ChatWindow(self)
            QApplication.instance().aboutToQuit.connect(self.chat_window.stop)
        return self.chat_window

    def open_chat(self):
        chat = self.chat()
        chat.show()
        chat.raise_()
        chat.activateWindow()

    def queue_screenshot(self):
        if self.selecting_screenshot:
            return
        self.selecting_screenshot = True
        QTimer.singleShot(120, self.capture_question)

    def capture_question(self):
        from screen_tools import select_screenshot
        chat = self.chat()
        try:
            if chat.pending is not None:
                self.notify('截图问答', '请等待当前回复结束，或先停止回复。')
                return
            image = select_screenshot()
        except RuntimeError as error:
            self.notify('截图问答', str(error))
            return
        finally:
            self.selecting_screenshot = False
        if image is not None:
            chat.attach(image)
            self.open_chat()

    def watcher(self):
        if self.screen_watcher is None:
            from screen_tools import ScreenWatcher
            self.screen_watcher = ScreenWatcher(self, self.chat())
            QApplication.instance().aboutToQuit.connect(self.screen_watcher.stop)
        return self.screen_watcher

    def toggle_screen_watcher(self):
        self.watcher().toggle()

    def configure_screen_watcher(self):
        self.watcher().configure()

    def set_auto(self, enabled):
        self.auto_enabled = enabled
        if enabled and self.isVisible():
            self.auto.start()
        else:
            self.auto.stop()
        self.settings.setValue('auto', enabled)

    def set_visibility_hotkey(self, enabled):
        if enabled and not self.hotkey.enable():
            QMessageBox.warning(self, '快捷键注册失败', f'{self.hotkey.sequence} 可能已被其他应用占用。')
            return
        if not enabled:
            self.hotkey.disable()
        self.settings.setValue('visibility_hotkey', enabled)

    def configure_visibility_hotkey(self):
        sequence = edit_hotkey(self, QKeySequence(self.hotkey.sequence))
        if sequence is None or sequence == self.hotkey.sequence:
            return
        try:
            self.hotkey.key_codes(sequence)
        except ValueError as error:
            QMessageBox.warning(self, '快捷键无效', str(error))
            return
        old = self.hotkey.sequence
        enabled = self.hotkey.registered
        self.hotkey.disable()
        self.hotkey.sequence = sequence
        if enabled and not self.hotkey.enable():
            self.hotkey.sequence = old
            self.hotkey.enable()
            QMessageBox.warning(self, '快捷键注册失败', f'{sequence} 可能已被其他应用占用。')
            return
        self.settings.setValue('visibility_sequence', sequence)

    def set_locked(self, enabled):
        self.locked = enabled
        self.settings.setValue('locked', enabled)

    def adjust(self, key, label, minimum, maximum):
        defaults = {'interval': 45, 'bubble_font': 14}
        value, accepted = QInputDialog.getInt(
            self, label, label, self.settings.value(key, defaults.get(key, 100), type=int),
            minimum, maximum)
        if accepted:
            self.apply_adjustment(key, value)

    def apply_adjustment(self, key, value):
        self.settings.setValue(key, value)
        if key == 'opacity':
            self.opacity = value
            self.update()
        elif key == 'speed':
            self.speed = value
            self.play(self.current)
        elif key == 'bubble_font':
            self.bubble_font = value
            self.update()
        else:
            self.interval = value
            self.auto.setInterval(value * 1000)

    def choose_click_sound(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择点击音效', '', 'WAV 音频 (*.wav)')
        if path:
            self.settings.setValue('click_wav', path)
            self.settings.setValue('click_sound', True)
            self.play_click_sound()

    def play_click_sound(self):
        if sys.platform == 'win32':
            path = Path(self.settings.value('click_wav', ''))
            if path.is_file() and path.suffix.lower() == '.wav':
                try:
                    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                    return
                except RuntimeError:
                    pass
        QApplication.beep()

    def edit_self_talk(self):
        text, accepted = QInputDialog.getMultiLineText(
            self, '自言自语台词', '每行一条。清空可恢复内置台词。',
            '\n'.join(self.settings.value('self_talk_lines', [], type=list)))
        if accepted:
            lines = [line.strip()[:100] for line in text.splitlines() if line.strip()][:100]
            self.settings.setValue('self_talk_lines', lines)

    def interact(self):
        if self.current == self.idle and self.offset is None and self.cap is not None:
            self.play(random.choice(list(self.actions)))
            if not self.message and self.settings.value('self_talk', False, type=bool):
                lines = self.settings.value('self_talk_lines', [], type=list)
                self.say(random.choice(lines or ['休息一下吧。', '我在这里陪着你。', '今天也一起加油。']))

    def say(self, message, duration=8000):
        self.message = message[:100]
        self.bubble_timer.start(duration)
        self.update()

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.connections.add(socket)
            socket.readyRead.connect(lambda s=socket: self.receive(s))
            socket.disconnected.connect(lambda s=socket: (self.connections.discard(s), s.deleteLater()))

    def refresh_activity(self, state=None, event=None):
        state = state if state is not None else self.activity.current()
        previous = self.activity_state
        self.activity_state = state
        status, count = state
        changed = state != previous
        if status == 'idle':
            if changed or event == 'idle':
                self.play(self.idle)
                self.clear_message()
            return
        if not changed and event != status:
            return
        messages = {'thinking': '正在思考', 'working': '正在处理任务', 'attention': '有事项需要确认'}
        if status == 'working' and '写代码' in self.actions and self.current != '写代码':
            self.play('写代码')
        message = messages[status] if count == 1 else f'{count} 个会话{messages[status]}'
        self.say(message)

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
                state = self.activity.update(status, data.get('session_id', ''), data.get('turn_id', ''))
                self.refresh_activity(state, status)
            elif command == 'hide':
                self.hide()
            elif command == 'show':
                self.show()
            elif command == 'stop':
                QTimer.singleShot(100, QApplication.quit)
            elif command != 'state':
                raise ValueError('Unsupported command')
            result = {'running': True, 'animation': self.current, 'animations': sorted(self.actions),
                      'activity': self.activity_state[0], 'activity_sessions': self.activity_state[1]}
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
