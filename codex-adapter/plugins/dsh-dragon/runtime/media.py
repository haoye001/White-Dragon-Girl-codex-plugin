"""Share sequential animation frames between pets playing the same clip and rate."""
import shutil
import subprocess
from time import monotonic

import cv2
from PySide6.QtGui import QImage, QPixmap


class Clip:
    def __init__(self, path, speed, chroma):
        self.process = self.capture = None
        self.chroma = chroma
        self.frame = None
        self.deadline = 0
        self.users = 0
        if path.suffix.lower() == '.webm':
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                raise RuntimeError('播放透明 WebM 需要将 FFmpeg 加入 PATH')
            repeat = ['-stream_loop', '-1'] if (
                path.stem in ('idle', '待机呼吸休闲') or path.parent.name == 'idle') else []
            self.process = subprocess.Popen(
                [ffmpeg, '-nostdin', '-v', 'error', *repeat, '-c:v', 'libvpx-vp9', '-i', str(path),
                 '-an', '-vf', 'fps=24,scale=640:360', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            fps = 24
        else:
            self.capture = cv2.VideoCapture(str(path))
            if not self.capture.isOpened():
                self.capture.release()
                raise RuntimeError(f'无法打开视频：{path.name}')
            fps = max(1, self.capture.get(cv2.CAP_PROP_FPS))
        self.interval = 100 / (fps * speed)

    def read(self, loop=False):
        now = monotonic()
        if now < self.deadline:
            return self.frame
        self.deadline = now + self.interval
        if self.process:
            pixels = self.process.stdout.read(640 * 360 * 4)
            ok = len(pixels) == 640 * 360 * 4
        else:
            ok, frame = self.capture.read()
            if not ok and loop:
                self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.capture.read()
            pixels = self.chroma(frame).tobytes() if ok else b''
        self.frame = QPixmap.fromImage(QImage(pixels, 640, 360, 2560, QImage.Format_RGBA8888)) if ok else None
        return self.frame

    def close(self):
        if self.capture:
            self.capture.release()
        if self.process:
            self.process.kill()
            self.process.stdout.close()
            self.process.wait()


class ClipPool:
    def __init__(self, chroma):
        self.clips = {}
        self.chroma = chroma

    def acquire(self, key):
        if key not in self.clips:
            self.clips[key] = Clip(key[0], key[1], self.chroma)
        clip = self.clips[key]
        clip.users += 1
        return clip

    def release(self, key):
        clip = self.clips[key]
        clip.users -= 1
        if not clip.users:
            clip.close()
            del self.clips[key]
