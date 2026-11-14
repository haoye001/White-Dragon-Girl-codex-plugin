"""Resize the bundled white-dragon animations for the Android overlay."""
from pathlib import Path

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "codex-adapter/plugins/bailong-pet/assets/animations"
OUTPUT = ROOT / "assets"
ANIMATIONS = {
    "idle": "待机",
    "wave": "差分01-招手-最新版",
    "heart": "差分20-比心",
    "celebrate": "差分18-庆祝",
    "sleepy": "差分14-困倦-最新版",
}

OUTPUT.mkdir(exist_ok=True)
for action, folder in ANIMATIONS.items():
    source, = (SOURCE / folder).glob("*.webp")
    frames, delays = [], []
    with Image.open(source) as image:
        for frame in ImageSequence.Iterator(image):
            resized = frame.convert("RGBA")
            resized.thumbnail((384, 384), Image.Resampling.LANCZOS)
            frames.append(resized)
            delays.append(max(30, frame.info.get("duration", 80)))
    frames[0].save(OUTPUT / f"{action}.webp", save_all=True, append_images=frames[1:],
                   duration=delays, loop=0, quality=82, method=4)
