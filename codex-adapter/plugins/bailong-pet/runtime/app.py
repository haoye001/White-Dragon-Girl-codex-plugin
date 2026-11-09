"""Transparent Windows companion. No account access or command execution."""
from __future__ import annotations

import hmac
import json
import queue
import secrets
import threading
import itertools
import random
import time
import tkinter as tk
from collections import OrderedDict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageTk, __version__ as pillow_version
from core import DATA, ROOT, VERSION, animation_catalog, atomic_json, read_json, validate_command
import animation
import quota
from bubble import SpeechBubble

KEY = '#ff00ff'
if int(pillow_version.split('.')[0]) < 13:
    raise RuntimeError('需要 Pillow 13+；请使用 setup.ps1 创建的隔离环境')


class Pet:
    def __init__(self):
        self.catalog = animation_catalog()
        self.root = tk.Tk()
        self.root.title('白龙娘 · Codex 桌面伙伴')
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=KEY)
        self.root.wm_attributes('-transparentcolor', KEY)
        self.root.geometry(f'300x300+{max(0, self.root.winfo_screenwidth()-340)}+{max(0, self.root.winfo_screenheight()-380)}')
        self.bubble = SpeechBubble(self.root)
        self.root.bind('<Configure>', lambda _event: self.bubble.position())
        self.picture = tk.Label(self.root, bg=KEY, borderwidth=0)
        self.picture.place(x=0, y=0, width=300, height=300)
        self.settings = {'auto_interact': True, 'auto_interval_seconds': 45}
        saved = read_json(DATA/'settings.json', {})
        if type(saved.get('auto_interact')) is bool:
            self.settings['auto_interact'] = saved['auto_interact']
        if type(saved.get('auto_interval_seconds')) in (int, float) and 10 <= saved['auto_interval_seconds'] <= 600:
            self.settings['auto_interval_seconds'] = saved['auto_interval_seconds']
        self.next_interaction = 0
        self.auto_count = 0
        self.last_interaction = None
        self.mouse_down = False
        self.click_id = None
        self.suppress_release = False
        self.quota_pending = False
        self.quota_error = None
        self.quota_results = queue.Queue()
        self.usage_generation = 0
        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label='随机互动', command=self.interact)
        actions = tk.Menu(self.menu, tearoff=False)
        for key, item in self.catalog.items():
            actions.add_command(label=item.get('name', key), command=lambda k=key: self.play(k))
        self.menu.add_cascade(label='动作', menu=actions)
        self.auto_enabled = tk.BooleanVar(value=self.settings['auto_interact'])
        self.menu.add_checkbutton(label='定时随机互动', variable=self.auto_enabled,
                                 command=lambda: self.update_settings({'auto_interact': self.auto_enabled.get()}))
        interval_menu = tk.Menu(self.menu, tearoff=False)
        for seconds, label in [(15, '10–20 秒'), (45, '30–60 秒（默认）'), (90, '1–2 分钟'), (180, '2–4 分钟')]:
            interval_menu.add_command(label=label, command=lambda s=seconds: self.update_settings({'auto_interval_seconds': s}))
        self.menu.add_cascade(label='自动互动间隔', menu=interval_menu)
        self.menu.add_command(label='查询 Codex 额度', command=self.request_quota)
        self.menu.add_command(label='显示上次额度', command=self.show_usage)
        self.menu.add_command(label='退出白龙桌宠', command=self.root.destroy)
        self.picture.bind('<ButtonPress-1>', self.press)
        self.picture.bind('<B1-Motion>', self.drag)
        self.picture.bind('<ButtonRelease-1>', self.release)
        self.picture.bind('<Double-Button-1>', self.double_click)
        self.picture.bind('<Button-3>', self.context_menu)
        self.commands = queue.Queue(maxsize=32)
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.cache_limit = 160 * 1024 * 1024
        self.requests = queue.PriorityQueue()
        self.decoded = queue.Queue(maxsize=2)
        self.loading = set()
        self.sequence = itertools.count()
        self.closed = threading.Event()
        self.desired = ('idle', True)
        self.photo_cache = OrderedDict()
        self.last_load_error = None
        threading.Thread(target=self.decode_worker, daemon=True).start()
        self.after_id = None
        self.bubble_id = None
        self.current = None
        self.visible = True
        self.usage = None
        self.busy = False
        self.dragged = False
        self.endpoint_token = secrets.token_urlsafe(32)
        self.server = make_server(self)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        atomic_json(DATA / 'endpoint.json', {'port': self.server.server_port, 'token': self.endpoint_token})
        self.play('idle', loop=True)
        self.specials = {k: v['id'] for k,v in read_json(animation_catalog()['idle']['path'].parents[1] / '素材清单.json', {}).items()
                         if isinstance(v, dict) and 'id' in v}
        self.pinned = {'idle', self.special('dragAnimation'), self.special('landingAnimation')}
        for key in [self.special('dragAnimation'), self.special('landingAnimation'), '01']:
            self.enqueue(key, priority=10)
        self.reset_auto_timer()
        self.root.after(16, self.poll)

    def say(self, text, seconds=8):
        if self.bubble_id:
            self.root.after_cancel(self.bubble_id)
        # Tk labels display literal text; no HTML, shell, URL or Markdown interpretation.
        self.bubble.show(text)
        self.bubble_id = self.root.after(int(seconds*1000), self.bubble.hide)

    def reset_auto_timer(self):
        seconds = self.settings['auto_interval_seconds']
        self.next_interaction = time.monotonic()+random.uniform(seconds*2/3, seconds*4/3)

    def update_settings(self, values):
        validate_command({'action': 'settings', 'settings': values}, self.catalog)
        settings = {**self.settings, **values}
        atomic_json(DATA/'settings.json', settings)
        self.settings = settings
        self.auto_enabled.set(settings['auto_interact'])
        self.reset_auto_timer()
        return self.state()

    def auto_tick(self):
        if (self.settings['auto_interact'] and time.monotonic() >= self.next_interaction
            and self.visible and not self.busy and not self.mouse_down and not self.quota_pending
            and not self.bubble.active and self.current in {'idle', 'idle2'}
            and self.desired[0] == self.current):
            self.interact(automatic=True)

    def context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
            self.reset_auto_timer()

    def request_quota(self):
        if self.quota_pending:
            self.say('正在查询额度，请稍等一下…', 10)
            return
        self.quota_pending = True
        self.quota_error = None
        self.usage_generation += 1
        generation = self.usage_generation
        self.play(self.special('quotaAnimation'))
        self.say('正在查询 Codex 额度…', 30)
        def worker():
            try:
                self.quota_results.put((generation, quota.fetch(cancel=self.closed), None))
            except Exception as exc:
                self.quota_results.put((generation, None, str(exc)))
        self.quota_thread = threading.Thread(target=worker, daemon=True)
        self.quota_thread.start()

    def accept_quota(self):
        try:
            generation, windows, error = self.quota_results.get_nowait()
        except queue.Empty:
            return
        if generation != self.usage_generation:
            return
        self.quota_pending = False
        self.quota_error = error
        if error:
            self.say(error+'\n'+('上次结果仍可从右键菜单查看。' if self.usage else '本次未取得额度，未显示为 0。'), 20)
        else:
            self.set_usage(windows, 'Codex account/rateLimits/read')

    def set_usage(self, windows, source):
        self.usage = {'windows': windows, 'checked_at': datetime.now().astimezone().isoformat(timespec='seconds'), 'source': source}
        self.show_usage()

    def enqueue(self, key, priority=0):
        if key not in self.cache and key not in self.loading:
            self.loading.add(key)
            self.requests.put((priority, next(self.sequence), key))

    def decode_worker(self):
        while not self.closed.is_set():
            try:
                _priority, _order, key = self.requests.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                result = animation.load(self.catalog[key], ROOT/'assets/playback'/f'{key}.frames',
                                        DATA/'frame-cache'/f'{key}.frames')
                error = None
            except Exception as exc:
                result, error = None, str(exc)
            while not self.closed.is_set():
                try:
                    self.decoded.put((key, result, error), timeout=.2)
                    break
                except queue.Full:
                    pass

    def accept_decoded(self):
        try:
            key, result, error = self.decoded.get_nowait()
        except queue.Empty:
            return
        self.loading.discard(key)
        if error:
            self.last_load_error = error
            return
        self.cache[key] = result
        self.cache_bytes += len(result[0]) * animation.FRAME_BYTES
        self.cache.move_to_end(key)
        if self.desired[0] == key:
            self.begin_play(key, self.desired[1])
        # Keep current and requested animation alive, bound all other decoded frames.
        for old in list(self.cache):
            if self.cache_bytes <= self.cache_limit:
                break
            if old not in self.pinned | {self.current, self.desired[0]}:
                removed = self.cache.pop(old)
                self.cache_bytes -= len(removed[0]) * animation.FRAME_BYTES

    def play(self, key, loop=False):
        self.desired = (key, loop)
        if self.current == key and getattr(self, 'loop', None) == loop:
            return  # Repeated work events must not restart the animation.
        if key in self.cache:
            self.cache.move_to_end(key)
            self.begin_play(key, loop)
        else:
            self.enqueue(key)

    def begin_play(self, key, loop):
        frames, delays = self.cache[key]
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self.current = key
        self.loop = loop
        self.active_frames = frames
        self.photo_cache.clear()
        def tick(index=0):
            if index not in self.photo_cache:
                self.photo_cache[index] = ImageTk.PhotoImage(frames[index], master=self.root)
            self.picture.configure(image=self.photo_cache[index])
            self.photo_cache.move_to_end(index)
            while len(self.photo_cache) > 3:
                self.photo_cache.popitem(last=False)
            following = index+1
            if following < len(frames):
                callback = lambda: tick(following)
            elif loop:
                callback = lambda: tick(0)
            else:
                # A previous animation finishing must not overwrite a newer pending click.
                def finish():
                    if self.desired[0] != key:
                        tick(index)
                    else:
                        self.play('work02' if self.busy else 'idle', loop=True)
                callback = finish
            self.after_id = self.root.after(delays[index] if self.visible else 250, callback)
        tick()

    def interact(self, automatic=False):
        key = random.choice([k for k in self.catalog if k.isdecimal() and k != self.last_interaction])
        self.last_interaction = key
        if automatic:
            self.auto_count += 1
        self.reset_auto_timer()
        self.play(key)
        self.say(self.catalog[key].get('line', '主人，我在这里。'))

    def press(self, event):
        self.mouse_down = True
        self.reset_auto_timer()
        self.anchor = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.dragged = False

    def drag(self, event):
        dx, dy = event.x_root-self.anchor[0], event.y_root-self.anchor[1]
        if abs(dx)+abs(dy) > 6:
            if not self.dragged:
                self.play(self.special('dragAnimation'), loop=True)
            self.dragged = True
            self.root.geometry(f'+{max(0,self.anchor[2]+dx)}+{max(0,self.anchor[3]+dy)}')

    def release(self, _event):
        self.mouse_down = False
        if self.suppress_release:
            self.suppress_release = False
            return
        if self.dragged:
            self.dragged = False
            self.play(self.special('landingAnimation'))
        else:
            if self.click_id:
                self.root.after_cancel(self.click_id)
            self.click_id = self.root.after(350, self.single_click)

    def single_click(self):
        self.click_id = None
        self.interact()

    def double_click(self, _event):
        if self.click_id:
            self.root.after_cancel(self.click_id)
            self.click_id = None
        self.suppress_release = True
        self.mouse_down = False
        self.request_quota()

    def special(self, field):
        return self.specials.get(field, 'idle')

    def show_usage(self):
        if not self.usage:
            self.say('双击我，或右键选择“查询 Codex 额度”。')
            return
        self.say(quota.format_usage(self.usage), 25)

    def state(self):
        return {'running': True, 'version': VERSION, 'visible': self.visible, 'animation': self.current,
                'requested_animation': self.desired[0], 'loading': self.desired[0] != self.current,
                'animation_error': self.last_load_error, 'cached_animations': list(self.cache),
                'busy': self.busy, 'usage': self.usage,
                'quota_pending': self.quota_pending, 'quota_error': self.quota_error,
                'settings': self.settings, 'auto_interactions': self.auto_count,
                'bubble_text': self.bubble.text, 'bubble_visible': self.bubble.active,
                'animations': [{'id': k, 'name': v.get('name', k)} for k,v in self.catalog.items()]}

    def command(self, value):
        validate_command(value, self.catalog)
        action = value['action']
        if action == 'stop':
            self.root.after(100, self.root.destroy)
        elif action == 'hide':
            self.root.withdraw(); self.visible = False
            self.bubble.withdraw()
        elif action == 'show':
            self.root.deiconify(); self.visible = True
            self.bubble.position()
        elif action == 'say':
            self.say(value['message'], value.get('seconds', 8))
        elif action == 'play':
            self.play(value['animation'])
        elif action == 'usage':
            self.usage_generation += 1
            self.quota_pending = False
            self.quota_error = None
            self.set_usage(value['windows'], 'Codex get_usage_limits（由当前聊天传入）')
            self.play(self.special('quotaAnimation'))
        elif action == 'query_usage':
            self.request_quota()
        elif action == 'settings':
            return self.update_settings(value['settings'])
        elif action == 'event':
            event = value['event']
            self.busy = event in {'UserPromptSubmit', 'PreToolUse', 'PermissionRequest'}
            self.play('work02' if self.busy else 'idle', loop=True)
            if event == 'PermissionRequest':
                self.say('主人，请在 Codex 中查看权限请求。')
        return self.state()

    def poll(self):
        self.accept_decoded()
        self.accept_quota()
        self.auto_tick()
        try:
            value, done, box = self.commands.get_nowait()
        except queue.Empty:
            pass
        else:
            try:
                box['result'] = self.command(value)
            except Exception as exc:
                box['error'] = str(exc)
            finally:
                done.set()
        self.root.after(16, self.poll)

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.closed.set()
            if getattr(self, 'quota_thread', None):
                self.quota_thread.join(timeout=4)
            self.server.shutdown()
            endpoint = read_json(DATA / 'endpoint.json', {})
            if endpoint.get('token') == self.endpoint_token:
                (DATA / 'endpoint.json').unlink(missing_ok=True)


def make_server(pet):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.path != '/command':
                self.send_error(404); return
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+pet.endpoint_token):
                self.send_error(403); return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384:
                    raise ValueError('请求长度无效')
                value = json.loads(self.rfile.read(size))
                validate_command(value, pet.catalog)
                done, box = threading.Event(), {}
                pet.commands.put_nowait((value, done, box))
                if not done.wait(25):
                    raise TimeoutError('桌宠未响应')
                if 'error' in box:
                    raise ValueError(box['error'])
                payload = json.dumps(box['result'], ensure_ascii=False).encode('utf8')
                self.send_response(200)
            except Exception as exc:
                payload = json.dumps({'error': str(exc)}, ensure_ascii=False).encode('utf8')
                self.send_response(400)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def setup(self):
            super().setup()
            self.connection.settimeout(5)
    return ThreadingHTTPServer(('127.0.0.1', 0), Handler)


if __name__ == '__main__':
    Pet().run()
