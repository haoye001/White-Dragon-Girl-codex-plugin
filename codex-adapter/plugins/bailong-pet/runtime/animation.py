"""Bounded, pre-rendered animation files; no Tk calls on decoder threads."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import time
import zlib

from PIL import Image
from core import MAX_FRAMES, MAX_PIXELS

SIDE = 300
FRAME_BYTES = SIDE * SIDE * 4
MAGIC = b'BLFRAME1'


def signature(item):
    # Fingerprint artwork bytes rather than copied file mtimes across plugin installs.
    digest = hashlib.sha256(item['path'].read_bytes()).hexdigest()
    spec = [digest, SIDE, item.get('renderScale', 1), item.get('renderOffset', [0, 0])]
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def render(item):
    frames, delays = [], []
    with Image.open(item['path'], formats=['WEBP']) as image:
        if image.width * image.height > MAX_PIXELS or image.n_frames > MAX_FRAMES:
            raise ValueError('动画尺寸或帧数超过安全限制')
        scale = max(.5, min(1.5, float(item.get('renderScale', 1))))
        side = round(SIDE * scale)
        offset = item.get('renderOffset', [0, 0])
        for index in range(image.n_frames):
            image.seek(index)
            frame = image.convert('RGBA')
            frame.thumbnail((side, side), Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', (SIDE, SIDE))
            canvas.paste(frame, ((SIDE-frame.width)//2+round(float(offset[0])*SIDE),
                                 SIDE-frame.height+round(float(offset[1])*SIDE)))
            frames.append(canvas)
            delays.append(max(30, min(1000, image.info.get('duration', 80))))
    return frames, delays


def save_frames(path, fingerprint, frames, delays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps({'fingerprint': fingerprint, 'delays': delays}).encode()
    temporary = path.with_suffix('.tmp')
    try:
        with temporary.open('wb') as stream:
            stream.write(MAGIC + struct.pack('<I', len(header)) + header)
            for frame in frames:
                packed = zlib.compress(frame.tobytes(), 1)
                stream.write(struct.pack('<I', len(packed)))
                stream.write(packed)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_frames(path, fingerprint):
    with Path(path).open('rb') as stream:
        if stream.read(8) != MAGIC:
            raise ValueError('Invalid animation cache')
        length = struct.unpack('<I', stream.read(4))[0]
        if not 0 < length <= 8192:
            raise ValueError('Invalid animation header')
        header = json.loads(stream.read(length))
        delays = header['delays']
        if header.get('fingerprint') != fingerprint or not isinstance(delays, list) or not 1 <= len(delays) <= MAX_FRAMES:
            raise ValueError('Stale animation cache')
        if any(type(delay) is not int or not 30 <= delay <= 1000 for delay in delays):
            raise ValueError('Invalid animation timing')
        frames = []
        for _ in delays:
            size = struct.unpack('<I', stream.read(4))[0]
            if not 0 < size <= FRAME_BYTES+1024:
                raise ValueError('Invalid frame length')
            packed = stream.read(size)
            decoder = zlib.decompressobj()
            raw = decoder.decompress(packed, FRAME_BYTES+1)
            if len(raw) != FRAME_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('Invalid decoded frame')
            frames.append(Image.frombytes('RGBA', (SIDE, SIDE), raw))
        if stream.read(1):
            raise ValueError('Unexpected trailing data')
    return frames, delays


def load(item, prepared, writable):
    fingerprint = signature(item)
    for path in (prepared, writable):
        try:
            return read_frames(path, fingerprint)
        except (OSError, ValueError, KeyError, TypeError, struct.error, zlib.error):
            pass
    frames, delays = render(item)
    try:
        save_frames(writable, fingerprint, frames, delays)
    except OSError:
        pass  # Read-only/full disk must not prevent in-memory playback.
    return frames, delays
