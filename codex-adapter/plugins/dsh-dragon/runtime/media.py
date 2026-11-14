"""Decode on worker threads and share decoded frames between matching idle clips."""
import queue
from contextlib import closing
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from time import monotonic

import cv2
from PySide6.QtGui import QImage, QPixmap

FRAME_BYTES = 640 * 360 * 4
CACHE_LIMIT = 96 * 1024 * 1024


class Clip:
    def __init__(self, path, speed, chroma, loop, cache_slots):
        self.path = path
        self.chroma = chroma
        self.loop = loop
        self.cache_slots = cache_slots
        self.frame = None
        self.deadline = 0
        self.users = 0
        self.finished = False
        self.frames = queue.Queue(maxsize=3)
        self.cancelled = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        self.ffmpeg = None
        if path.suffix.lower() == '.webm':
            local_ffmpeg = Path(sys.executable).with_name('ffmpeg.exe')
            self.ffmpeg = str(local_ffmpeg) if local_ffmpeg.is_file() else shutil.which('ffmpeg')
        if path.suffix.lower() == '.webm' and not self.ffmpeg:
            raise RuntimeError('播放透明 WebM 需要将 FFmpeg 加入 PATH')
        self.interval = 100 / (24 * speed)
        self.speed = speed
        threading.Thread(target=self.decode, daemon=True, name='DSH animation decoder').start()

    def enqueue(self, frame):
        while not self.cancelled.is_set():
            try:
                self.frames.put(frame, timeout=0.05)
                return True
            except queue.Full:
                pass
        return False

    def source_frames(self):
        if self.ffmpeg:
            with self.process_lock:
                if self.cancelled.is_set():
                    return
                process = subprocess.Popen(
                    [self.ffmpeg, '-nostdin', '-v', 'error', '-c:v', 'libvpx-vp9', '-i', str(self.path),
                     '-an', '-vf', 'fps=24,scale=640:360', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.process = process
            try:
                while not self.cancelled.is_set():
                    pixels = process.stdout.read(FRAME_BYTES)
                    if len(pixels) != FRAME_BYTES:
                        break
                    yield pixels
            finally:
                with self.process_lock:
                    self.process = None
                    if process.poll() is None:
                        process.kill()
                process.stdout.close()
                process.wait()
        else:
            capture = cv2.VideoCapture(str(self.path))
            try:
                if not capture.isOpened():
                    return
                self.interval = 100 / (max(1, capture.get(cv2.CAP_PROP_FPS)) * self.speed)
                while not self.cancelled.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        break
                    yield self.chroma(frame).tobytes()
            finally:
                capture.release()

    def decode(self):
        cached = []
        caching = self.loop
        try:
            while not self.cancelled.is_set():
                received = False
                with closing(self.source_frames()) as frames:
                    for frame in frames:
                        received = True
                        if not self.enqueue(frame):
                            return
                        if caching:
                            if self.cache_slots.acquire(blocking=False):
                                cached.append(frame)
                            else:
                                for _ in cached:
                                    self.cache_slots.release()
                                cached.clear()
                                caching = False
                if not self.loop or not received:
                    break
                if cached:
                    while not self.cancelled.is_set():
                        for frame in cached:
                            if not self.enqueue(frame):
                                return
        except (OSError, cv2.error):
            pass
        finally:
            for _ in cached:
                self.cache_slots.release()
            self.enqueue(None)

    def read(self):
        """Consume a due frame on the GUI thread, without waiting for the decoder."""
        now = monotonic()
        if now < self.deadline or self.finished:
            return self.frame
        try:
            pixels = self.frames.get_nowait()
        except queue.Empty:
            return self.frame
        if pixels is None:
            self.finished = True
            return self.frame
        # Keep cadence on the media timeline even if the GUI timer wakes a little late.
        self.deadline = max(now + self.interval / 2, self.deadline + self.interval)
        self.frame = QPixmap.fromImage(QImage(pixels, 640, 360, 2560, QImage.Format_RGBA8888))
        return self.frame

    def close(self):
        self.cancelled.set()
        with self.process_lock:
            if self.process and self.process.poll() is None:
                self.process.kill()


class ClipPool:
    def __init__(self, chroma):
        self.clips = {}
        self.chroma = chroma
        self.cache_slots = threading.BoundedSemaphore(CACHE_LIMIT // FRAME_BYTES)

    def acquire(self, key):
        if key not in self.clips:
            self.clips[key] = Clip(key[0], key[1], self.chroma, key[2] is None, self.cache_slots)
        clip = self.clips[key]
        clip.users += 1
        return clip

    def release(self, key):
        if key not in self.clips:
            return
        clip = self.clips[key]
        clip.users -= 1
        if not clip.users:
            clip.close()
            del self.clips[key]

    def close(self):
        for clip in self.clips.values():
            clip.close()
        self.clips.clear()
