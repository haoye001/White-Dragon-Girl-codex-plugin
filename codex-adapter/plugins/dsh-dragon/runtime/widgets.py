"""Local desktop utilities and the optional read-only Codex quota client."""
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import queue
import threading

from PySide6.QtCore import QObject, QProcess, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog
from weather import CityNotFound, current_weather

try:
    from lunar_python import Solar
except ImportError:
    Solar = None


SOLAR_HOLIDAYS = {(1, 1): '元旦', (5, 1): '劳动节', (6, 1): '儿童节', (10, 1): '国庆节'}
FORTUNES = (
    '今日宜把难题拆小。先完成能看见结果的一步。',
    '今日宜留一点空白。放松片刻，回来会看得更清楚。',
    '今日宜整理灵感。随手记下的问题，可能是下一步的线索。',
    '今日宜向前试一步。做个小实验，比反复猜更有用。',
    '今日宜与人分享。把手头的思路讲一遍，或许会听到新答案。',
    '今日宜回顾进度。那些已经解决的小问题，也值得庆祝。',
    '今日宜收个好尾。给明天的自己留一句清楚的下一步。',
)


def daily_fortune(day):
    index = int.from_bytes(sha256(day.isoformat().encode('ascii')).digest()[:4], 'big')
    return FORTUNES[index % len(FORTUNES)]


def festivals(day):
    names = []
    holiday = SOLAR_HOLIDAYS.get((day.month, day.day))
    if holiday:
        names.append(holiday)
    if Solar is not None:
        lunar = Solar.fromYmd(day.year, day.month, day.day).getLunar()
        if lunar.getMonth() > 0:
            names.extend(lunar.getFestivals())
        term = lunar.getJieQi()
        if term:
            names.append(term)
    return list(dict.fromkeys(names))


class DesktopWidgets(QObject):
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self.settings = pet.settings
        self.closed = threading.Event()
        self.quota_result = queue.Queue()
        self.quota_poll = QTimer(self)
        self.quota_poll.setInterval(100)
        self.quota_poll.timeout.connect(self.accept_quota)
        self.calendar_timer = QTimer(self)
        self.calendar_timer.timeout.connect(self.check_calendar)
        self.calendar_timer.start(15_000)
        self.weather_result = queue.Queue()
        self.weather_poll = QTimer(self)
        self.weather_poll.setInterval(100)
        self.weather_poll.timeout.connect(self.accept_weather)
        QApplication.instance().aboutToQuit.connect(self.closed.set)

    def add_actions(self, menu):
        menu.addAction('查询 Codex 额度', self.request_quota)
        tools = menu.addMenu('桌面小工具')
        tools.addAction('每日一签', self.draw_fortune)
        tools.addAction('今日节日与节气', self.show_festivals)
        tools.addAction('设置生日提醒', self.set_birthday)
        tools.addAction('查看天气…', self.request_weather)
        for key, label in [('festival_reminders', '节日与节气提醒'), ('hourly_chime', '整点报时')]:
            action = tools.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.settings.value(key, False, type=bool))
            action.toggled.connect(lambda enabled, setting=key: self.settings.setValue(setting, enabled))
        launchers = tools.addMenu('快捷启动')
        for entry in self.settings.value('quick_apps', [], type=list):
            path = Path(entry)
            action = launchers.addAction(path.stem, lambda program=path: self.launch(program))
            action.setToolTip(str(path))
        launchers.addAction('配置应用…', self.configure_launchers)
        if self.settings.value('quick_apps', [], type=list):
            launchers.addAction('清空快捷启动', lambda: self.settings.setValue('quick_apps', []))

    def draw_fortune(self):
        self.pet.notify('白龙每日一签', daily_fortune(date.today()))

    def show_festivals(self):
        names = festivals(date.today())
        text = '今天是' + '、'.join(names) if names else '今天没有节日或节气提醒。'
        if Solar is None:
            text += '\n当前仅显示公历节日。'
        self.pet.notify('白龙日历', text)

    def set_birthday(self):
        value, accepted = QInputDialog.getText(self.pet, '生日提醒', '输入公历生日（MM-DD），清空可取消。',
                                              text=self.settings.value('birthday', ''))
        if not accepted:
            return
        value = value.strip()
        if value:
            try:
                value = datetime.strptime('2000-' + value, '%Y-%m-%d').strftime('%m-%d')
            except ValueError:
                self.pet.notify('白龙日历', '请输入有效的月日，例如 06-18。')
                return
        self.settings.setValue('birthday', value)

    def check_calendar(self, now=None):
        now = now or datetime.now()
        today = now.date().isoformat()
        messages = []
        if (self.settings.value('festival_reminders', False, type=bool)
                and self.settings.value('festival_seen', '') != today):
            self.settings.setValue('festival_seen', today)
            names = festivals(now.date())
            if names:
                messages.append('今天是' + '、'.join(names))
        if (self.settings.value('birthday', '') == now.strftime('%m-%d')
                and self.settings.value('birthday_seen', '') != today):
            self.settings.setValue('birthday_seen', today)
            messages.append('生日快乐！愿你今天有很多好事。')
        slot = now.strftime('%Y-%m-%d %H')
        if (now.minute == 0 and self.settings.value('hourly_chime', False, type=bool)
                and self.settings.value('chime_seen', '') != slot):
            self.settings.setValue('chime_seen', slot)
            QApplication.beep()
            messages.append(f'现在是 {now.hour:02d}:00。')
        if messages:
            self.pet.notify('白龙日历', '\n'.join(messages))

    def configure_launchers(self):
        paths, _ = QFileDialog.getOpenFileNames(self.pet, '选择快捷启动应用', '', 'Windows 应用 (*.exe)')
        if paths:
            self.settings.setValue('quick_apps', list(dict.fromkeys(paths)))

    def launch(self, path):
        if not path.is_absolute() or path.suffix.lower() != '.exe' or not path.is_file():
            self.pet.notify('快捷启动', f'找不到应用：{path.name}')
            return
        started, _ = QProcess.startDetached(str(path), [], str(path.parent))
        if not started:
            self.pet.notify('快捷启动', f'启动失败：{path.name}')

    def request_quota(self):
        if self.quota_poll.isActive():
            return
        try:
            import codex_quota
        except ImportError:
            self.pet.notify('Codex 额度', '额度组件尚未安装，请运行插件安装脚本。')
            return
        self.pet.notify('Codex 额度', '正在查询 Codex 额度…')
        self.quota_poll.start()

        def worker():
            try:
                windows = codex_quota.fetch(cancel=self.closed)
                result = codex_quota.format_usage({
                    'windows': windows, 'checked_at': datetime.now().astimezone().isoformat()})
            except (OSError, RuntimeError, ValueError) as error:
                result = str(error) if isinstance(error, RuntimeError) else '无法读取额度，请检查 Codex 安装与登录状态。'
            self.quota_result.put(result)

        threading.Thread(target=worker, daemon=True, name='DSH Codex quota').start()

    def accept_quota(self):
        try:
            result = self.quota_result.get_nowait()
        except queue.Empty:
            return
        self.quota_poll.stop()
        self.pet.notify('Codex 额度', result, duration=25_000)

    def request_weather(self):
        if self.weather_poll.isActive():
            self.pet.notify('白龙天气', '正在查询天气…')
            return
        city, accepted = QInputDialog.getText(self.pet, '查看天气', '输入城市名称',
                                             text=self.settings.value('weather_city', '成都'))
        city = city.strip()[:80]
        if not accepted or not city:
            return
        self.settings.setValue('weather_city', city)
        self.pet.notify('白龙天气', '正在查询天气…')
        self.weather_poll.start()

        def worker():
            try:
                text = current_weather(city)
            except CityNotFound as error:
                text = str(error)
            except OSError:
                text = '暂时连不上天气服务，已尝试重连。请稍后再试。'
            except (ValueError, KeyError, TypeError, AttributeError, IndexError):
                text = '天气服务返回了无法读取的数据，请稍后再试。'
            self.weather_result.put(text)

        threading.Thread(target=worker, daemon=True, name='DSH weather').start()

    def accept_weather(self):
        try:
            result = self.weather_result.get_nowait()
        except queue.Empty:
            return
        self.weather_poll.stop()
        self.pet.notify('白龙天气', result, duration=15_000)
