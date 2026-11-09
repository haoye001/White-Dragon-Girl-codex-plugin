"""Pre-render original artwork once; preserve originals and lossless RGBA pixels."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'plugins/bailong-pet/runtime'))
import animation
from core import animation_catalog

results = []
for key, item in animation_catalog().items():
    path = ROOT/'plugins/bailong-pet/assets/playback'/f'{key}.frames'
    fingerprint = animation.signature(item)
    start = time.perf_counter()
    try:
        frames, delays = animation.read_frames(path, fingerprint)
    except (OSError, ValueError):
        frames, delays = animation.render(item)
        animation.save_frames(path, fingerprint, frames, delays)
    prepared = time.perf_counter()
    again, again_delays = animation.read_frames(path, fingerprint)
    assert again_delays == delays
    assert frames[0].tobytes() == again[0].tobytes()
    assert frames[-1].tobytes() == again[-1].tobytes()
    row = {'id': key, 'frames': len(frames), 'prepare_seconds': round(prepared-start, 3),
           'read_seconds': round(time.perf_counter()-prepared, 3), 'bytes': path.stat().st_size}
    results.append(row)
    print(json.dumps(row), flush=True)
    del frames, again
(ROOT/'animation-benchmark.json').write_text(json.dumps(results, indent=2), encoding='utf8')
