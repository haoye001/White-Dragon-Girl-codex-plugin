"""Measure real UI heartbeat and animation-switch latency, with no user data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time

market = Path(__file__).resolve().parents[1]
runtime = Path(sys.argv[1]) if len(sys.argv) > 1 else market/'plugins/bailong-pet/runtime'
sys.path.insert(0, str(runtime))
output = Path(sys.argv[2]) if len(sys.argv) > 2 else market/'desktop-benchmark.json'

with tempfile.TemporaryDirectory(prefix='bailong-performance-') as temporary:
    os.environ['BAILONG_PLUGIN_DATA'] = temporary
    import bridge
    from app import Pet
    pet = Pet()
    pet.root.withdraw()
    pet.visible = False
    gaps, errors, measurements = [], [], []
    previous = [time.perf_counter()]

    def heartbeat():
        now = time.perf_counter()
        gaps.append(now-previous[0])
        previous[0] = now
        pet.root.after(10, heartbeat)

    def exercise():
        try:
            # Let initial idle become available; clock measurement excludes GUI construction.
            deadline = time.monotonic()+15
            while not bridge.request({'action': 'state'})['animation']:
                assert time.monotonic() < deadline
                time.sleep(.01)
            for key in ['01', '24', 'work02', '01']:
                start = time.perf_counter()
                reply = bridge.request({'action': 'play', 'animation': key})
                acknowledgement = time.perf_counter()-start
                deadline = time.monotonic()+15
                while reply['animation'] != key:
                    assert time.monotonic() < deadline, key
                    time.sleep(.01)
                    reply = bridge.request({'action': 'state'})
                measurements.append({'animation': key, 'command_ms': round(acknowledgement*1000, 1),
                                     'first_frame_ms': round((time.perf_counter()-start)*1000, 1)})
                time.sleep(.15)
            # Decode results for older requests must not override the last selection.
            for key in ['04', '05', '09']:
                bridge.request({'action': 'play', 'animation': key})
            deadline = time.monotonic()+15
            while bridge.request({'action': 'state'})['animation'] != '09':
                assert time.monotonic() < deadline
                time.sleep(.02)
            time.sleep(.5)
            state = bridge.request({'action': 'state'})
            assert state['animation'] == '09'
            if 'requested_animation' in state:
                assert state['requested_animation'] == '09'
        except BaseException as exc:
            errors.append(exc)
        finally:
            bridge.request({'action': 'stop'})

    pet.root.after(10, heartbeat)
    worker = threading.Thread(target=exercise, daemon=True)
    worker.start()
    pet.root.after(90000, pet.root.destroy)
    pet.run()
    worker.join(timeout=3)
    if errors:
        raise errors[0]
    assert not worker.is_alive()
    result = {'runtime': str(runtime), 'switches': measurements,
              'ui_heartbeat_max_gap_ms': round(max(gaps)*1000, 1),
              'ui_heartbeat_p95_gap_ms': round(sorted(gaps)[int(len(gaps)*.95)]*1000, 1),
              'samples': len(gaps)}
    output.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result, indent=2))
    if runtime == market/'plugins/bailong-pet/runtime':
        assert max(gaps) < .2, 'GUI event loop blocked for over 200 ms'
        assert max(x['command_ms'] for x in measurements) < 150, 'Slow command acknowledgement'
