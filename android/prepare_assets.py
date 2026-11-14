"""Resize the bundled white-dragon animations for the Android overlay."""
from pathlib import Path
import json

from PIL import Image, ImageSequence

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "codex-adapter/plugins/bailong-pet/assets/animations"
OUTPUT = ROOT / "assets"
FILENAMES = {"01": "wave", "20": "heart", "18": "celebrate", "14": "sleepy"}


def entries(value):
    if isinstance(value, dict):
        if "id" in value and "file" in value:
            yield value
        else:
            for child in value.values():
                yield from entries(child)
    elif isinstance(value, list):
        for child in value:
            yield from entries(child)

OUTPUT.mkdir(exist_ok=True)
manifest = json.loads((SOURCE / "素材清单.json").read_text(encoding="utf-8-sig"))
catalog = []
for item in entries(manifest):
    action = FILENAMES.get(item["id"], item["id"])
    destination = OUTPUT / f"{action}.webp"
    catalog.append({"file": destination.name, "name": item.get("name", "待机")})
    if destination.exists():
        continue
    source = SOURCE / item.get("playbackFile", item["file"])
    frames, delays = [], []
    with Image.open(source) as image:
        for frame in ImageSequence.Iterator(image):
            resized = frame.convert("RGBA")
            resized.thumbnail((384, 384), Image.Resampling.LANCZOS)
            frames.append(resized)
            delays.append(max(30, frame.info.get("duration", 80)))
    temporary = destination.with_suffix(".tmp")
    frames[0].save(temporary, format="WEBP", save_all=True, append_images=frames[1:],
                   duration=delays, loop=0, quality=82, method=4)
    temporary.replace(destination)
    print(destination.name, flush=True)

(OUTPUT / "animations.json").write_text(
    json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
