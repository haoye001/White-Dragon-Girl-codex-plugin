"""Optional floating dashboard for media, reminders and Codex activity."""
from datetime import datetime
import queue
import threading

from PySide6.QtCore import QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from now_playing import current_line, fetch_lyrics, parse_lrc, read_windows_track


class MediaDashboard(QObject):
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self.track = None
        self.track_state = '正在读取系统媒体…'
        self.lines = ()
        self.lyric_state = ''
        self.media_results = queue.Queue()
        self.lyric_results = queue.Queue()
        self.media_pending = False
        self.lyric_pending = False
        self.generation = 0
        self.poll_count = 0
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.tick)
        self.island = Island(pet, self)

    def show(self):
        if not self.island.isVisible():
            self.island.move(self.pet.pos() + QPoint(90, -110))
            screen = self.island.screen().availableGeometry()
            self.island.move(max(screen.left(), min(self.island.x(), screen.right() - self.island.width() + 1)),
                             max(screen.top(), self.island.y()))
        self.island.show()
        self.island.raise_()

    def tick(self):
        self.accept_track()
        self.accept_lyrics()
        if self.poll_count % 4 == 0 and not self.media_pending:
            self.media_pending = True

            def read():
                try:
                    track = read_windows_track()
                except ImportError:
                    self.media_results.put((None, '系统媒体组件尚未安装'))
                except (OSError, RuntimeError, TimeoutError):
                    self.media_results.put((None, '暂时无法读取系统媒体'))
                else:
                    self.media_results.put((track, '没有可读取的系统媒体'))

            threading.Thread(target=read, daemon=True, name='DSH Windows media').start()
        self.poll_count += 1
        self.island.refresh()

    def accept_track(self):
        try:
            track, self.track_state = self.media_results.get_nowait()
        except queue.Empty:
            return
        old_key = self.track.key if self.track else None
        self.track = track
        if old_key != (track.key if track else None):
            self.generation += 1
            self.lines = ()
            self.lyric_state = ''
        self.media_pending = False

    def load_local_lyrics(self):
        if self.track is None:
            self.pet.notify('桌面灵动岛', '请先播放一首歌。')
            return
        generation = self.generation
        path, _ = QFileDialog.getOpenFileName(self.island, '加载当前歌曲的歌词', '', 'LRC 歌词 (*.lrc)')
        if not path or generation != self.generation:
            return
        try:
            with open(path, 'rb') as stream:
                lines = parse_lrc(stream.read(262_144).decode('utf-8-sig'))
        except (OSError, ValueError):
            self.pet.notify('桌面灵动岛', '无法读取歌词文件。请选择 UTF-8 编码的 LRC。')
            return
        self.generation += 1
        self.lines = lines
        self.lyric_state = '等待歌词开始…' if lines else '没有找到带时间戳的歌词'
        self.island.refresh()

    def lookup_lyrics(self):
        if self.track is None:
            self.pet.notify('桌面灵动岛', '请先播放一首歌。')
            return
        if self.lyric_pending:
            return
        track = self.track
        generation = self.generation
        self.lyric_pending = True
        self.lyric_state = '正在从 LRCLIB 查找歌词…'

        def read():
            try:
                lines = fetch_lyrics(track)
            except (OSError, TypeError, ValueError, AttributeError):
                lines = ()
            self.lyric_results.put((generation, lines))

        threading.Thread(target=read, daemon=True, name='DSH lyric lookup').start()

    def accept_lyrics(self):
        try:
            generation, lines = self.lyric_results.get_nowait()
        except queue.Empty:
            return
        self.lyric_pending = False
        if generation == self.generation:
            self.lines = lines
            self.lyric_state = '等待歌词开始…' if lines else '未找到同步歌词或服务不可用'


class Island(QWidget):
    def __init__(self, pet, media):
        super().__init__(pet, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.pet = pet
        self.media = media
        self.offset = None
        self.setWindowTitle('桌面灵动岛')
        self.setStyleSheet('Island {background:#25243d;border:1px solid #66608e;border-radius:12px}'
                           'QLabel,QToolButton {color:#f1efff;background:transparent}')
        layout = QVBoxLayout(self)
        header = QToolButton()
        header.setText('桌面灵动岛')
        header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        header.setArrowType(Qt.DownArrow)
        header.setCheckable(True)
        header.setChecked(True)
        close = QToolButton()
        close.setText('关闭')
        close.clicked.connect(self.hide)
        bar = QHBoxLayout()
        bar.addWidget(header, 1)
        bar.addWidget(close)
        layout.addLayout(bar)
        self.details = QWidget()
        body = QVBoxLayout(self.details)
        self.media_label = QLabel()
        self.lyric_label = QLabel()
        self.todo_label = QLabel()
        self.activity_label = QLabel()
        for label in (self.media_label, self.lyric_label, self.todo_label, self.activity_label):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            body.addWidget(label)
        controls = QHBoxLayout()
        for title, callback in [('加载 LRC', media.load_local_lyrics), ('在线找歌词', media.lookup_lyrics)]:
            button = QToolButton()
            button.setText(title)
            button.clicked.connect(callback)
            controls.addWidget(button)
        body.addLayout(controls)
        layout.addWidget(self.details)

        def collapse(expanded):
            self.details.setVisible(expanded)
            header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
            self.adjustSize()

        header.toggled.connect(collapse)
        self.setFixedWidth(300)

    def showEvent(self, event):
        super().showEvent(event)
        self.media.poll_count = 0
        self.media.timer.start()
        self.media.tick()

    def hideEvent(self, event):
        self.media.timer.stop()
        super().hideEvent(event)

    def refresh(self):
        track = self.media.track
        if track:
            status = '播放中' if track.playing else '已暂停'
            self.media_label.setText(f'{status} · {track.title}' + (f' — {track.artist}' if track.artist else ''))
            elapsed = track.elapsed()
            if self.media.lines and elapsed >= self.media.lines[0][0]:
                self.lyric_label.setText(current_line(self.media.lines, elapsed))
            else:
                self.lyric_label.setText(self.media.lyric_state)
        else:
            self.media_label.setText(self.media.track_state)
            self.lyric_label.clear()
        pending = [todo for todo in self.pet.todos if not todo.get('archived')]
        if pending:
            next_item = min(pending, key=lambda todo: todo['due'])
            due = datetime.fromtimestamp(next_item['due']).strftime('%m-%d %H:%M')
            self.todo_label.setText(f'待办 {len(pending)} 项 · {due} {next_item["text"]}')
        else:
            self.todo_label.setText('待办 · 无')
        status, count = self.pet.activity_state
        labels = {'idle': '空闲', 'thinking': '思考中', 'working': '工作中', 'attention': '待确认'}
        self.activity_label.setText('Codex · ' + labels[status] + (f' · {count} 个会话' if count else ''))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.offset = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.offset = None
        super().mouseReleaseEvent(event)
